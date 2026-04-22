from __future__ import annotations


DEFAULT_RESOURCE_DRIFT_THRESHOLDS = {
    "cpu_percent_delta": 20.0,
    "memory_percent_delta": 10.0,
    "disk_percent_delta": 5.0,
    "gpu_utilization_delta": 25.0,
    "gpu_memory_delta_mb": 512.0,
}


def _delta(current, previous):
    if current is None or previous is None:
        return None
    return float(current) - float(previous)


def build_resource_drift(
    current_snapshot: dict,
    previous_snapshot: dict | None,
    *,
    thresholds: dict | None = None,
) -> dict:
    limits = dict(DEFAULT_RESOURCE_DRIFT_THRESHOLDS)
    if thresholds:
        limits.update({key: value for key, value in thresholds.items() if value is not None})

    if previous_snapshot is None:
        return {
            "state": "baseline",
            "cpu_percent_delta": None,
            "memory_percent_delta": None,
            "disk_percent_delta": None,
            "gpu_deltas": [],
            "alerts": [],
            "thresholds": limits,
        }

    drift = {
        "state": "stable",
        "cpu_percent_delta": _delta(
            current_snapshot.get("cpu_percent"),
            previous_snapshot.get("cpu_percent"),
        ),
        "memory_percent_delta": _delta(
            current_snapshot.get("memory_percent"),
            previous_snapshot.get("memory_percent"),
        ),
        "disk_percent_delta": _delta(
            current_snapshot.get("disk_percent"),
            previous_snapshot.get("disk_percent"),
        ),
        "gpu_deltas": [],
        "alerts": [],
        "thresholds": limits,
    }

    for metric_name, label in (
        ("cpu_percent_delta", "cpu usage drift exceeds threshold"),
        ("memory_percent_delta", "memory usage drift exceeds threshold"),
        ("disk_percent_delta", "disk usage drift exceeds threshold"),
    ):
        metric_value = drift.get(metric_name)
        threshold_value = limits.get(metric_name)
        if metric_value is None or threshold_value is None:
            continue
        if abs(metric_value) >= float(threshold_value):
            drift["alerts"].append(label)

    previous_gpus = {
        int(gpu.get("index")): gpu
        for gpu in (previous_snapshot.get("gpus") or [])
        if gpu.get("index") is not None
    }
    for gpu in current_snapshot.get("gpus") or []:
        gpu_index = gpu.get("index")
        if gpu_index is None:
            continue
        previous_gpu = previous_gpus.get(int(gpu_index), {})
        utilization_delta = _delta(
            gpu.get("utilization_percent"),
            previous_gpu.get("utilization_percent"),
        )
        memory_delta_mb = _delta(
            gpu.get("memory_used_mb"),
            previous_gpu.get("memory_used_mb"),
        )
        drift["gpu_deltas"].append(
            {
                "index": int(gpu_index),
                "utilization_delta_percent": utilization_delta,
                "memory_delta_mb": memory_delta_mb,
            }
        )
        if (
            utilization_delta is not None
            and abs(utilization_delta) >= float(limits["gpu_utilization_delta"])
        ):
            drift["alerts"].append(
                f"gpu {int(gpu_index)} utilization drift exceeds threshold"
            )
        if (
            memory_delta_mb is not None
            and abs(memory_delta_mb) >= float(limits["gpu_memory_delta_mb"])
        ):
            drift["alerts"].append(
                f"gpu {int(gpu_index)} memory drift exceeds threshold"
            )

    if drift["alerts"]:
        drift["state"] = "warning"
    return drift
