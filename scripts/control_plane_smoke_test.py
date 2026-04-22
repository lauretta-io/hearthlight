#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.utils.docker_cli import build_docker_env, find_docker_binary


def build_headers(api_key: str | None, *, content_type: str | None = None) -> dict[str, str]:
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def send_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload=None,
    api_key: str | None = None,
):
    body = None
    headers = build_headers(api_key, content_type="application/json")
    if payload is not None:
        body = json.dumps(payload).encode()
    req = request.Request(base_url + path, data=body, headers=headers, method=method)
    with request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode())


def send_multipart(
    base_url: str,
    path: str,
    *,
    field_name: str,
    filename: str,
    data: bytes,
    api_key: str | None = None,
):
    boundary = "codexboundary7d1318d9"
    parts = [
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{filename}"\r\n'
        ).encode(),
        b"Content-Type: video/mp4\r\n\r\n",
        data,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    headers = build_headers(
        api_key,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    req = request.Request(
        base_url + path,
        data=body,
        headers=headers,
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def expect(condition: bool, message: str):
    if not condition:
        raise RuntimeError(message)


def run_compose(docker_binary: str, *args: str):
    env = build_docker_env(docker_binary)
    env.setdefault("RELOAD", "")
    subprocess.run(
        [docker_binary, "compose", *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )


def wait_for_endpoint(
    base_url: str,
    path: str,
    *,
    api_key: str | None,
    expected_status: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
):
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            payload = send_json(base_url, path, api_key=api_key)
            if payload.get("status") == expected_status:
                return payload
            last_error = f"{path} returned {payload!r}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(poll_interval_seconds)
    raise RuntimeError(
        f"timed out waiting for {path} to report {expected_status}: {last_error}"
    )


def main():
    parser = argparse.ArgumentParser(description="Smoke test the mixed-source control plane")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=os.environ.get("WEBAPP_API_KEY"))
    parser.add_argument("--skip-start", action="store_true")
    parser.add_argument("--manage-compose", action="store_true")
    parser.add_argument("--docker-binary")
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    docker_binary = None
    upload_id = None
    started = False

    try:
        if args.manage_compose:
            docker_binary = args.docker_binary or find_docker_binary()
            expect(
                docker_binary is not None,
                "docker CLI could not be found; install Docker Desktop or pass --docker-binary",
            )
            run_compose(docker_binary, "up", "-d", "db", "rabbitmq", "webapp")

        wait_for_endpoint(
            base_url,
            "/healthz",
            api_key=args.api_key,
            expected_status="ok",
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )
        wait_for_endpoint(
            base_url,
            "/readyz",
            api_key=args.api_key,
            expected_status="ready",
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )

        fake_mp4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
        upload_response = send_multipart(
            base_url,
            "/sources/uploads",
            field_name="file",
            filename="smoke.mp4",
            data=fake_mp4,
            api_key=args.api_key,
        )
        upload_id = upload_response["upload"]["id"]

        sources_payload = [
            {
                "kind": "camera_url",
                "label": "Smoke Camera",
                "tasks": ["PERSON", "BAG"],
                "enabled": True,
                "order": 0,
                "source_value": "rtsp://smoke.example/live",
            },
            {
                "kind": "webcam",
                "label": "Smoke Webcam",
                "tasks": ["GUN"],
                "enabled": True,
                "order": 1,
                "source_value": 0,
            },
            {
                "kind": "video_upload",
                "label": "Smoke Upload",
                "tasks": ["PERSON"],
                "enabled": True,
                "order": 2,
                "upload_id": upload_id,
            },
        ]
        saved_sources = send_json(
            base_url,
            "/sources",
            method="PUT",
            payload=sources_payload,
            api_key=args.api_key,
        )
        expect(len(saved_sources) == 3, "expected three saved sources")

        resources = send_json(base_url, "/system/resources", api_key=args.api_key)
        if args.skip_start:
            expect(
                "admission" in resources and "reason" in resources["admission"],
                "resource snapshot is missing admission state",
            )
        else:
            expect(resources["admission"]["allowed"] is True, "admission should be open")
        expect("model_health" in resources, "resource snapshot is missing model health")

        models = send_json(base_url, "/models", api_key=args.api_key)
        expect(models, "expected at least one registered model")
        detector_models = send_json(base_url, "/models/detector", api_key=args.api_key)
        expect(detector_models, "expected at least one detector model")

        bindings = send_json(base_url, "/model-bindings", api_key=args.api_key)
        expect(bindings, "expected default model bindings")
        saved_bindings = send_json(
            base_url,
            "/model-bindings",
            method="PUT",
            payload=[
                binding
                for binding in bindings
                if binding.get("binding_scope") == "default"
            ],
            api_key=args.api_key,
        )
        expect(saved_bindings, "expected model binding update response")

        model_health = send_json(base_url, "/system/model-health", api_key=args.api_key)
        expect(model_health, "expected model health response")

        status = send_json(base_url, "/status", api_key=args.api_key)
        expect(len(status["sources"]) == 3, "status did not include three sources")

        compat_sources = send_json(base_url, "/camera_streams", api_key=args.api_key)
        expect(len(compat_sources) == 3, "camera_streams compatibility view is incomplete")

        if not args.skip_start:
            started_response = send_json(
                base_url,
                "/start",
                method="POST",
                payload={},
                api_key=args.api_key,
            )
            started = True
            expect(
                started_response.get("status") == "starting",
                "start did not return starting",
            )
            status = send_json(base_url, "/status", api_key=args.api_key)
            expect(
                status.get("status") in {"initializing", "running"},
                "status did not transition after start",
            )
            expect(status.get("run_id"), "run_id was not set after start")

        print("PASS: control-plane smoke test succeeded")
    except error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"HTTP {exc.code}: {body}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            if started:
                send_json(
                    base_url,
                    "/stop",
                    method="POST",
                    payload={},
                    api_key=args.api_key,
                )
        except Exception:
            pass
        try:
            send_json(base_url, "/sources", method="PUT", payload=[], api_key=args.api_key)
        except Exception:
            pass
        if upload_id is not None:
            try:
                req = request.Request(
                    base_url + f"/sources/uploads/{upload_id}",
                    headers=build_headers(args.api_key),
                    method="DELETE",
                )
                with request.urlopen(req, timeout=20):
                    pass
            except Exception:
                pass
        if args.manage_compose and docker_binary is not None:
            try:
                run_compose(docker_binary, "down")
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
