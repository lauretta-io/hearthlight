from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.util import find_spec
import json
import logging
from pathlib import Path
import shutil
import subprocess
from threading import Event, Lock, Thread
import time

from ..constants import ModuleNames
from .dependency_health import get_unhealthy_dependencies

PSUTIL_AVAILABLE = find_spec("psutil") is not None
if PSUTIL_AVAILABLE:
    import psutil  # type: ignore
else:
    psutil = None


DEFAULT_THRESHOLDS = {
    "cpu_percent": 95.0,
    "memory_percent": 95.0,
    "disk_percent": 95.0,
    "gpu_percent": 95.0,
    "gpu_memory_percent": 95.0,
}

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_gpu_metrics() -> list[dict]:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return []
    command = [
        nvidia_smi,
        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return []

    gpus = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 5:
            continue
        index, name, utilization, memory_used, memory_total = parts
        try:
            gpus.append(
                {
                    "index": int(index),
                    "name": name,
                    "utilization_percent": float(utilization),
                    "memory_used_mb": float(memory_used),
                    "memory_total_mb": float(memory_total),
                }
            )
        except ValueError:
            continue
    return gpus


def collect_resource_snapshot(
    module_status: dict[str, str],
    *,
    disk_path: str | Path = ".",
    webapp_status: str = "running",
) -> dict:
    cpu_percent = None
    memory_percent = None
    if psutil is not None:
        cpu_percent = float(psutil.cpu_percent(interval=None))
        memory_percent = float(psutil.virtual_memory().percent)

    disk_percent = None
    try:
        if psutil is not None:
            disk_percent = float(psutil.disk_usage(str(disk_path)).percent)
        else:
            total, used, _ = shutil.disk_usage(str(disk_path))
            disk_percent = (used / total) * 100 if total else 0.0
    except Exception:
        disk_percent = None

    enriched_module_status = {ModuleNames.WEBAPP: webapp_status}
    enriched_module_status.update(module_status)
    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "disk_percent": disk_percent,
        "gpus": collect_gpu_metrics(),
        "module_status": enriched_module_status,
        "updated_at": utc_now_iso(),
    }


def evaluate_admission(
    snapshot: dict,
    *,
    requires_gpu: bool,
    enabled_source_count: int,
    module_status: dict[str, str],
    thresholds: dict | None = None,
) -> dict:
    limits = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        limits.update({k: v for k, v in thresholds.items() if v is not None})

    if enabled_source_count <= 0:
        return {"allowed": False, "reason": "at least one enabled source is required", "thresholds": limits}

    dependency_errors = get_unhealthy_dependencies(snapshot.get("dependency_status"))
    if dependency_errors:
        return {
            "allowed": False,
            "reason": dependency_errors[0],
            "thresholds": limits,
            "dependency_errors": dependency_errors,
        }

    degraded_modules = [
        module_name
        for module_name, status in module_status.items()
        if status == "error"
    ]
    if degraded_modules:
        return {
            "allowed": False,
            "reason": f"modules in error state: {', '.join(sorted(degraded_modules))}",
            "thresholds": limits,
        }

    if requires_gpu and not snapshot.get("gpus"):
        return {
            "allowed": False,
            "reason": "gpu-backed AI resources are unavailable",
            "thresholds": limits,
        }

    metric_checks = [
        ("cpu_percent", snapshot.get("cpu_percent"), limits["cpu_percent"]),
        ("memory_percent", snapshot.get("memory_percent"), limits["memory_percent"]),
        ("disk_percent", snapshot.get("disk_percent"), limits["disk_percent"]),
    ]
    for metric_name, current, limit in metric_checks:
        if current is not None and limit is not None and current >= limit:
            return {
                "allowed": False,
                "reason": f"{metric_name} exceeds threshold",
                "thresholds": limits,
            }

    for gpu in snapshot.get("gpus", []):
        utilization = gpu.get("utilization_percent")
        total_memory = gpu.get("memory_total_mb") or 0
        used_memory = gpu.get("memory_used_mb") or 0
        memory_percent = (used_memory / total_memory) * 100 if total_memory else 0.0
        if utilization is not None and utilization >= limits["gpu_percent"]:
            return {
                "allowed": False,
                "reason": f"gpu {gpu['index']} utilization exceeds threshold",
                "thresholds": limits,
            }
        if total_memory and memory_percent >= limits["gpu_memory_percent"]:
            return {
                "allowed": False,
                "reason": f"gpu {gpu['index']} memory exceeds threshold",
                "thresholds": limits,
            }

    return {"allowed": True, "reason": None, "thresholds": limits}


def serialize_json(data: dict | list | None) -> str | None:
    if data is None:
        return None
    return json.dumps(data)


@dataclass
class PersistedEvent:
    event_type: str
    severity: str
    message: str
    metadata: dict | None = None


class ResourceMonitor(Thread):
    def __init__(
        self,
        snapshot_supplier,
        persistence_callback,
        *,
        sample_interval: float = 5.0,
        persist_interval: float = 15.0,
    ):
        super().__init__(name="ResourceMonitor", daemon=True)
        self.snapshot_supplier = snapshot_supplier
        self.persistence_callback = persistence_callback
        self.sample_interval = sample_interval
        self.persist_interval = persist_interval
        self.stop_event = Event()
        self.lock = Lock()
        self.latest_snapshot: dict | None = None
        self.last_persisted_at = 0.0

    def run(self):
        while not self.stop_event.is_set():
            try:
                snapshot = self.snapshot_supplier()
            except Exception:
                logger.exception("Failed to collect resource snapshot")
                self.stop_event.wait(self.sample_interval)
                continue
            with self.lock:
                self.latest_snapshot = snapshot
            if time.time() - self.last_persisted_at >= self.persist_interval:
                try:
                    self.persistence_callback(snapshot)
                    self.last_persisted_at = time.time()
                except Exception:
                    logger.exception("Failed to persist resource snapshot")
            self.stop_event.wait(self.sample_interval)

    def get_snapshot(self) -> dict | None:
        with self.lock:
            if self.latest_snapshot is None:
                return None
            return dict(self.latest_snapshot)

    def stop(self):
        self.stop_event.set()
