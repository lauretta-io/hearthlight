# Security And Robustness Notes

This document covers the main defensive controls currently implemented in the backend.

## Tooling Robustness

Local operator tooling now attempts to discover the Docker Desktop CLI binary automatically when
`docker` is not on `PATH`. This reduces false-negative startup failures on macOS desktops where
the engine is running but the shell environment has not been updated.

The compose stack also now waits for healthy Postgres and RabbitMQ containers before starting the
services that depend on them. This reduces race-condition failures during `reset-db`, `webapp`,
and core module startup.

Optional FOIA services are gated behind a `foia` compose profile so the default backend startup
path does not accidentally rely on missing FOIA build contexts or env files.

For Apple Silicon / Linux arm64 builds, the `webapp` image now installs CPU `onnxruntime` instead
of the unavailable `onnxruntime-gpu` wheel and skips `tensorrt` and `triton`. This makes the API
container buildable on arm64 without implying that the GPU inference services are supported there.

## Web API Hardening

### Source control and upload staging

The API now stores operator-managed source configuration in Postgres instead of relying on camera
lists embedded directly in `config.yaml`.

Control-plane tables:

- `control.input_source_template`
- `control.uploaded_media`
- `control.resource_snapshot`
- `control.resource_event`

Supported source kinds:

- `camera_url`
- `video_upload`
- `webcam`

Video uploads are staged under `SOURCE_UPLOAD_DIR` and only metadata is persisted in Postgres.
The upload route enforces:

- supported video extensions only
- bounded upload size via `SOURCE_UPLOAD_MAX_BYTES`
- SHA-256 checksum capture for staged files
- cleanup of partial files on failed upload

Uploaded media now moves through a simple lifecycle:

- `staged`: uploaded but not currently referenced by a source row
- `attached`: referenced by a saved source row but not in an active run
- `active`: referenced by an enabled source in a started run
- `deleted`: explicitly removed

If a saved video-upload source references missing metadata or a missing staged file, the source
now surfaces as `failed` in `/sources` and `/status` instead of only crashing later at `/start`.

### Optional API key protection

The FastAPI app now supports an optional shared API key:

```bash
export WEBAPP_API_KEY="your-secret"
```

When this variable is set, requests must include:

```text
X-API-Key: your-secret
```

If `WEBAPP_API_KEY` is not set, the API remains open for local development.

CORS preflight `OPTIONS` requests remain allowed when API-key protection is enabled, so browser
clients can still negotiate authenticated cross-origin requests.

`/healthz` and `/readyz` remain unauthenticated by default so container probes do not need the
shared API key.

### Configurable CORS allowlist

Allowed origins can now be overridden with:

```bash
export WEBAPP_ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
```

This is safer than hard-coding a wider set in environments where the dashboard origin is known.

### Basic response hardening headers

The API now adds:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`

### Request size ceiling

The API now rejects requests whose declared `Content-Length` exceeds
`WEBAPP_MAX_REQUEST_BYTES`.

Default:

```bash
export WEBAPP_MAX_REQUEST_BYTES=5242880
```

This is mainly intended to limit oversized POI/image uploads before they reach the expensive
decode and feature-extraction paths.

### Health and readiness probes

The API now exposes:

- `/healthz` for liveness
- `/readyz` for dependency readiness

`/readyz` verifies:

- runtime config availability
- database connectivity
- RabbitMQ env configuration
- `ffmpeg` availability

This makes container orchestration and startup debugging more predictable than relying on the
root endpoint alone.

### Status visibility

The `/status` endpoint now returns per-module state and the active `run_id`, not just the
overall system status. Module-level `ERROR` status is surfaced as overall system `error`, and
the response also includes `error_modules` so operators can see which module failed.

It now also returns:

- `sources`: active source summaries with coarse runtime state
- `resources`: the latest sampled CPU / RAM / disk / GPU snapshot
- `admission`: whether a new run would currently be allowed to start

The compatibility `POST /camera_stream` route still exists, but it now rewrites camera-only
payloads into persisted `InputSource` rows. New clients should use `/sources`.

## Resource Monitoring And Admission Control

The web control plane now samples host resource data and persists periodic snapshots in
`control.resource_snapshot`.

Current sampled areas:

- CPU utilization
- memory utilization
- disk utilization
- GPU utilization and memory when `nvidia-smi` is available
- module status, including `WEBAPP`
- dependency health for `database`, `rabbitmq`, and `ffmpeg`

The module control path now also treats unexpected worker-thread exits as fatal. If a critical
thread inside `INGESTOR`, `REID`, or `ASSOCIATION` dies after startup, the module publishes
`error`, the web control plane surfaces that through `/status`, and admission remains blocked until
the module is restarted or the system is stopped.

Dependency outages are also folded into the same control-plane snapshot. If Postgres, RabbitMQ, or
`ffmpeg` becomes unavailable, `/system/resources`, `/status`, and the Monitoring page surface that
under `dependency_status`, and start admission is blocked with the first unhealthy dependency
message.

The control plane now also includes per-module queue telemetry under `resources.module_metrics`.
`INGESTOR`, `REID`, and `ASSOCIATION` publish queue-depth summaries so operators can see when
downstream stages are backing up even if the modules are still technically running.

The `/start` path now evaluates an admission gate before publishing a system start command.
Current denials include:

- no enabled sources configured
- one or more enabled sources already have a persisted validation error
- one or more modules already in `error`
- CPU / memory / disk threshold breach
- GPU threshold breach
- GPU required but unavailable when `WEBAPP_REQUIRE_GPU=true`

Before a start command is published, enabled sources are also probed directly:

- uploaded videos must still exist on disk and yield at least one frame
- camera URLs must open and yield at least one frame
- webcam device indices must open and yield at least one frame

If source probing fails, the source row keeps the failure message in `last_error`, `/status` and
`/system/resources` surface that through admission, and `/start` returns `409` without publishing
the run.

After start, ingest also guards against silent source starvation. The run metadata is only written
after the first real frame is received, and the module transitions to `error` if no frames arrive
within the configured ingest timeout (`input.no_frame_timeout`, default `15` seconds).

Ingest camera/bootstrap logging is now separated from run logging. Before the first real frame is
seen, ingest logs to `logging.bootstrap_log_dir` (default `shared/output/bootstrap_logs/`). Once
the run is confirmed with a real frame, ingest switches to the per-run `logging.log_dir`.

Threshold env vars:

```bash
export RESOURCE_CPU_THRESHOLD_PERCENT=95
export RESOURCE_MEMORY_THRESHOLD_PERCENT=95
export RESOURCE_DISK_THRESHOLD_PERCENT=95
export RESOURCE_GPU_THRESHOLD_PERCENT=95
export RESOURCE_GPU_MEMORY_THRESHOLD_PERCENT=95
```

Targeted module restart requests are also persisted as resource events and can be issued via:

```text
POST /system/modules/{module_name}/restart
```

Manual incident status changes are also pushed back into the association module. Confirmed or
in-progress incidents therefore stay protected from automatic association-side resolution until an
explicit `RESOLVED` update is sent.

## POI Input Safety

The POI registration path now includes additional checks:

- the system must be running before POI registration is accepted
- non-research requests must include images
- image count is capped by `POI_MAX_IMAGES` (default: `10`)
- base64 payloads are validated before decode
- decoded payloads must be valid images
- POI crop directories are derived from sanitized names to avoid path traversal
- generated entity image paths are written under a dedicated base directory
- database writes are rolled back if POI publication fails
- POI result responses expose `seconds_since_update`, so freshness is measured in
  elapsed wall-clock time instead of inferred frame counts

Related environment variables:

```bash
export POI_MAX_IMAGES=10
export POI_CROP_DIR="shared/output/poi_crops"
export ENTITY_IMAGE_DIR="shared/output/entity_images"
```

Backend-generated entity images default to:

```text
shared/output/entity_images/run_<run_id>/camera_<camera_id>/<journey_node_id>.jpg
```

That keeps generated entity crops out of ad hoc cache paths and makes the output directory easy to
bind into a shared volume if downstream systems need the files.

## Runtime Config Loading

`external_routes` now loads the OmegaConf runtime config lazily instead of at import time.

Benefits:

- clearer `503` errors when config is missing
- fewer startup-time crashes during partial environments
- easier local inspection of the web app without a full running backend

The config path can be overridden with:

```bash
export DHS_CONFIG_PATH="src/shared/configs/config.yaml"
```

For local container bootstrapping, the repo ships `shared/configs/example_config.yaml` as the
starting point for the gitignored runtime file.

## RabbitMQ Initialization

RabbitMQ settings are now resolved at use time instead of module import time.

Benefits:

- missing `RABBITMQ_HOST` and `RABBITMQ_EXCHANGE` produce clearer runtime errors
- importing modules no longer fails immediately just because RabbitMQ env vars are absent
- resolution publication failures are logged without corrupting already-committed incident updates
- module command listeners now close publishers/consumers more cleanly during shutdown
- module stop/reset logging now warns when worker threads are still alive during cleanup

## Schema Notes

Path-bearing columns that store generated media locations now use unbounded text fields instead of
fixed-length varchar fields. That avoids truncation of long local or container paths for:

- `dicos.frame.path`
- `dicos.poi_search.crop_dir`

If your local Postgres instance was created before this change and you rely on `reset-db`, rerun
schema recreation so those column definitions match the current models.

## ffmpeg Guardrails

Video and crop extraction routes now:

- verify `ffmpeg` is installed before launching subprocesses
- validate incident clip duration
- verify referenced recording files exist
- close subprocess pipes cleanly
- log ffmpeg failures instead of failing silently
- clip crop bounding boxes to frame boundaries before writing cached crops

## Database Initialization

The SQLAlchemy engine and session factory are now initialized lazily.

Benefits:

- importing DB-dependent modules no longer fails immediately if Postgres env vars are missing
- errors are raised closer to the actual DB usage point
- the DB engine uses `pool_pre_ping=True` to reduce stale-connection failures
- association incident IDs are initialized lazily instead of querying the database at import time

## Incident State Integrity

The incident update API now enforces:

- optimistic stale-status checks when `old_status` is provided
- allowed status transition rules instead of arbitrary state jumps

Examples of allowed transitions:

- `UNCONFIRMED -> CONFIRMED`
- `CONFIRMED -> IN PROGRESS`
- `PENDING RESOLUTION -> RESOLVED`

An invalid or stale transition now returns `409 Conflict`.

## Remaining Gaps

The backend is still primarily a trusted-network service. Areas that may warrant further work:

- stronger authentication than a shared API key
- rate limiting on expensive endpoints
- deeper per-source runtime telemetry from ingestor instead of coarse global frame counters
- stricter validation of remote camera URLs before start
- structured audit logging for control actions
- tighter concurrency control around cross-request in-memory system state
