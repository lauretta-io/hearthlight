from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socketserver
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import cv2
except ModuleNotFoundError:  # pragma: no cover - local dependency check at runtime
    cv2 = None

from hearthlight.runtime import assert_local_worker_dependencies_reachable, resolve_local_worker_env
from shared.utils.input_sources import (
    SOURCE_KIND_VIDEO_UPLOAD,
    coerce_source_value,
    configure_capture_timeouts,
    open_capture,
    probe_source_connection,
)
from shared.utils.local_worker_runtime import DEFAULT_LOCAL_WORKER_PORT

ROOT_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT_DIR / "shared" / "output" / "local_runtime"
PID_PATH = STATE_DIR / "supervisor.pid"
LOG_PATH = STATE_DIR / "supervisor.log"
PREVIEW_TIMEOUT_MS = int(os.environ.get("SOURCE_PREVIEW_TIMEOUT_MS", "5000"))
PREVIEW_FRAME_DELAY_SECONDS = float(os.environ.get("SOURCE_PREVIEW_FRAME_DELAY_SECONDS", "0.1"))
PREVIEW_JPEG_QUALITY = int(os.environ.get("SOURCE_PREVIEW_JPEG_QUALITY", "80"))
HOST = os.environ.get("HEARTHLIGHT_LOCAL_WORKER_BIND_HOST", "0.0.0.0")
PORT = int(os.environ.get("HEARTHLIGHT_LOCAL_WORKER_PORT", str(DEFAULT_LOCAL_WORKER_PORT)))

logger = logging.getLogger(__name__)


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _write_pid() -> None:
    _ensure_state_dir()
    PID_PATH.write_text(str(os.getpid()))


def _remove_pid() -> None:
    if PID_PATH.exists():
        PID_PATH.unlink()


def _encode_preview_frame(frame) -> bytes | None:
    assert cv2 is not None
    success, encoded = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), PREVIEW_JPEG_QUALITY],
    )
    if not success:
        return None
    return encoded.tobytes()


class LocalWorkerSupervisor:
    def __init__(self, root_dir: Path = ROOT_DIR):
        self.root_dir = root_dir
        self.env = assert_local_worker_dependencies_reachable(root_dir)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.processes: dict[str, subprocess.Popen] = {}
        self.reasons: dict[str, str] = {}
        self.httpd: ThreadingHTTPServer | None = None
        self.server_thread: threading.Thread | None = None
        self.poll_thread: threading.Thread | None = None

    def _python(self) -> str:
        venv_python = self.root_dir / ".venv" / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)
        return sys.executable

    def _worker_commands(self) -> dict[str, list[str]]:
        python = self._python()
        return {
            "INGESTOR": [python, "-um", "src.ingestor.main"],
            "REID": [python, "-um", "hearthlight.local_reid_passthrough"],
            "ANOMALY": [python, "-um", "src.anomaly.main"],
        }

    def start_workers(self) -> None:
        with self.lock:
            for module_name, command in self._worker_commands().items():
                existing = self.processes.get(module_name)
                if existing is not None and existing.poll() is None:
                    continue
                _ensure_state_dir()
                log_path = STATE_DIR / f"{module_name.lower()}.log"
                log_handle = log_path.open("ab")
                process = subprocess.Popen(
                    command,
                    cwd=self.root_dir,
                    env=self.env,
                    stdout=log_handle,
                    stderr=log_handle,
                )
                self.processes[module_name] = process
                self.reasons.pop(module_name, None)

    def stop_workers(self) -> None:
        with self.lock:
            for process in self.processes.values():
                if process.poll() is None:
                    process.terminate()
            deadline = time.time() + 10.0
            for process in self.processes.values():
                if process.poll() is not None:
                    continue
                timeout = max(0.0, deadline - time.time())
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
            self.processes.clear()

    def poll_workers(self) -> None:
        while not self.stop_event.wait(1.0):
            with self.lock:
                for module_name, process in list(self.processes.items()):
                    return_code = process.poll()
                    if return_code is None:
                        continue
                    self.reasons[module_name] = f"local worker process exited with code {return_code}"

    def health_snapshot(self) -> dict:
        workers = {}
        with self.lock:
            for module_name in ("INGESTOR", "REID", "ANOMALY"):
                process = self.processes.get(module_name)
                alive = process is not None and process.poll() is None
                workers[module_name] = {
                    "running": alive,
                    "pid": process.pid if process is not None and alive else None,
                    "reason": None if alive else self.reasons.get(module_name, "local CPU workers not started"),
                }
        ready = all(worker["running"] for worker in workers.values())
        return {
            "status": "ready" if ready else "degraded",
            "runtime": "hybrid-local-cpu",
            "opencv_available": cv2 is not None,
            "workers": workers,
        }

    def probe_source(self, *, kind: str, source_value, upload_path: str | None = None) -> str | None:
        return probe_source_connection(
            kind,
            source_value,
            upload_path=upload_path,
            timeout_ms=PREVIEW_TIMEOUT_MS,
        )

    def preview_stream(self, *, kind: str, source_value, upload_path: str | None = None):
        if cv2 is None:
            raise RuntimeError("opencv capture backend is unavailable")
        resolved_source = coerce_source_value(kind, source_value, upload_path)
        if kind == SOURCE_KIND_VIDEO_UPLOAD and not Path(str(resolved_source)).exists():
            raise RuntimeError("uploaded media file is missing on disk")

        capture = cv2.VideoCapture()
        configure_capture_timeouts(capture, PREVIEW_TIMEOUT_MS)
        opened = open_capture(capture, resolved_source)
        if not opened or not capture.isOpened():
            capture.release()
            raise RuntimeError("source preview could not be opened on host")
        try:
            while not self.stop_event.is_set():
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                encoded = _encode_preview_frame(frame)
                if encoded is None:
                    continue
                yield encoded
                time.sleep(PREVIEW_FRAME_DELAY_SECONDS)
        finally:
            capture.release()

    def serve(self, host: str = HOST, port: int = PORT) -> None:
        self.start_workers()
        self.poll_thread = threading.Thread(target=self.poll_workers, name="LocalWorkerPoller", daemon=True)
        self.poll_thread.start()
        supervisor = self

        class Handler(BaseHTTPRequestHandler):
            def _write_json(self, status_code: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/healthz":
                    self._write_json(HTTPStatus.OK, supervisor.health_snapshot())
                    return
                if parsed.path != "/preview.mjpeg":
                    self._write_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
                    return
                query = parse_qs(parsed.query)
                kind = (query.get("kind") or [""])[0]
                source_value = (query.get("source_value") or [None])[0]
                if kind == "webcam" and source_value is not None:
                    try:
                        source_value = int(source_value)
                    except ValueError:
                        pass
                upload_path = (query.get("upload_path") or [None])[0]
                try:
                    preview_frames = supervisor.preview_stream(
                        kind=kind,
                        source_value=source_value,
                        upload_path=upload_path,
                    )
                    first_encoded = next(preview_frames, None)
                    if first_encoded is None:
                        raise RuntimeError("source preview could not be opened on host")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.end_headers()
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(first_encoded)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                    for encoded in preview_frames:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                        self.wfile.write(encoded)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                except BrokenPipeError:
                    return
                except Exception as exc:
                    self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {"detail": str(exc)})

            def do_POST(self):  # noqa: N802
                parsed = urlparse(self.path)
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw_body = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw_body.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"detail": "invalid json payload"})
                    return
                if parsed.path == "/probe":
                    detail = supervisor.probe_source(
                        kind=str(payload.get("kind") or ""),
                        source_value=payload.get("source_value"),
                        upload_path=payload.get("upload_path"),
                    )
                    self._write_json(
                        HTTPStatus.OK,
                        {"ok": detail is None, "detail": detail},
                    )
                    return
                if parsed.path == "/shutdown":
                    self._write_json(HTTPStatus.OK, {"status": "stopping"})
                    threading.Thread(target=supervisor.shutdown, daemon=True).start()
                    return
                self._write_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})

            def log_message(self, format, *args):  # noqa: A003
                logger.debug("local-worker-http " + format, *args)

        class ReusableThreadingHTTPServer(ThreadingHTTPServer):
            allow_reuse_address = True

        self.httpd = ReusableThreadingHTTPServer((host, port), Handler)
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, name="LocalWorkerHTTP", daemon=True)
        self.server_thread.start()
        while not self.stop_event.wait(0.5):
            pass

    def shutdown(self) -> None:
        self.stop_event.set()
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.stop_workers()


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def start_supervisor() -> int:
    _ensure_state_dir()
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text().strip())
        except ValueError:
            pid = 0
        if pid and _process_is_alive(pid):
            return 0
        _remove_pid()
    python = str(ROOT_DIR / ".venv" / "bin" / "python")
    if not Path(python).exists():
        python = sys.executable
    with LOG_PATH.open("ab") as log_handle:
        process = subprocess.Popen(
            [python, "-m", "hearthlight.local_workers", "serve"],
            cwd=ROOT_DIR,
            env=resolve_local_worker_env(ROOT_DIR),
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    deadline = time.time() + 20.0
    while time.time() < deadline:
        if PID_PATH.exists():
            return 0
        if process.poll() is not None:
            break
        time.sleep(0.25)
    return 1


def stop_supervisor() -> int:
    if not PID_PATH.exists():
        return 0
    try:
        pid = int(PID_PATH.read_text().strip())
    except ValueError:
        _remove_pid()
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        _remove_pid()
        return 0
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if not _process_is_alive(pid):
            _remove_pid()
            return 0
        time.sleep(0.25)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    _remove_pid()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local hybrid CPU worker supervisor")
    parser.add_argument("command", choices=["serve", "start", "stop"], nargs="?", default="serve")
    args = parser.parse_args(argv)

    if args.command == "start":
        return start_supervisor()
    if args.command == "stop":
        return stop_supervisor()

    logging.basicConfig(level=logging.INFO)
    supervisor = LocalWorkerSupervisor(ROOT_DIR)
    signal.signal(signal.SIGTERM, lambda *_: supervisor.shutdown())
    signal.signal(signal.SIGINT, lambda *_: supervisor.shutdown())
    _write_pid()
    try:
        supervisor.serve()
    finally:
        supervisor.shutdown()
        _remove_pid()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
