# Container Runbook

This runbook covers the Docker-based deployment path for the current repository.

## Preflight

Run the repository preflight checker:

```bash
python3 scripts/container_preflight.py
```

It checks:

- whether `docker` and `docker compose` are available
- whether the Docker Desktop CLI can be discovered even if it is not on `PATH`
- whether the core Dockerfiles exist
- whether required runtime files exist
- whether the compose file publishes the model-control API/UI ports
- whether the compose file enables NVIDIA access for GPU-backed services

Core files required before startup:

- `.env`
- `shared/configs/config.yaml`

Main database expectation:

- one Postgres container exposed on the internal service name `db`
- service port `5432`
- runtime schema `dicos`
- control-plane schema `control`

Bootstrap the runtime config from the checked-in example:

```bash
hearthlight onboard
```
If you are operating manually without onboarding, copy `shared/configs/example_config.yaml` to
`shared/configs/config.yaml` and replace the placeholder camera sources before attempting the
GPU/video services.

## Core Stack

The default local control stack is:

- `db`
- `rabbitmq`
- `webapp`

The optional `pipeline` profile adds:

- `ingestor`
- `reid`
- `anomaly`
- `association`

Recommended startup sequence:

```bash
docker compose build rabbitmq webapp
docker compose up -d db rabbitmq
hearthlight reset-db
docker compose up webapp
```

Enable the full AI pipeline explicitly:

```bash
docker compose --profile pipeline build ingestor reid anomaly association
docker compose --profile pipeline up ingestor reid anomaly association
```

The compose file also now uses health checks for Postgres and RabbitMQ, and core services wait on
those dependencies instead of relying on bare container start order.

The `pipeline` profile is the right path for Linux/NVIDIA hosts. On macOS Docker Desktop, the
default local startup should usually remain `db + rabbitmq + webapp` unless you explicitly want to
attempt the heavier worker image builds.

## Runtime Expectations

After the core stack starts:

- React dashboard should be reachable at `http://localhost:${WEBAPP_UI_HOST_PORT:-3000}`
- FastAPI service should be reachable at `http://localhost:${WEBAPP_API_HOST_PORT:-8000}`
- RabbitMQ management UI should be reachable at `http://localhost:${RABBITMQ_MANAGEMENT_HOST_PORT:-15672}`
- Postgres should be exposed on `localhost:${POSTGRES_HOST_PORT:-5433}`

Model-control endpoints are exposed on the same FastAPI port:

- `GET /models`
- `GET /models/{stage}`
- `GET /model-bindings`
- `PUT /model-bindings`
- `GET /system/model-health`

## Verification Checklist

### 1. Service startup

Check that containers are up:

```bash
docker compose ps
```

Review logs if a service exits:

```bash
docker compose logs --tail=200 webapp
docker compose logs --tail=200 ingestor
docker compose logs --tail=200 reid
docker compose logs --tail=200 association
```

### 2. API health

Verify the API root:

```bash
curl http://localhost:8000/
```

Expected response:

```json
{"message":"Lauretta Real Time Backend"}
```

Verify liveness:

```bash
curl http://localhost:8000/healthz
```

Verify readiness:

```bash
curl http://localhost:8000/readyz
```

`/readyz` checks the runtime config, database connectivity, RabbitMQ env wiring, and `ffmpeg`
availability. It returns `503` until the API’s critical dependencies are available.

Verify system status:

```bash
curl http://localhost:8000/status
```

Expected early-state responses are typically:

- `idle`
- `initializing`
- `running`
- `stopping`

The `/status` payload now also includes:

- `module_status`: per-module states for `INGESTOR`, `REID`, and `ASSOCIATION`
- `error_modules`: the subset of modules currently reporting `error`
- `run_id`: the current active run identifier when a run is active
- `sources`: mixed-source runtime summaries for camera URLs, uploads, and webcams
- `resources`: latest CPU/RAM/disk/GPU snapshot
- `resources.drift`: change-vs-baseline deltas for CPU, memory, disk, and GPU metrics
- `admission`: current start-gating decision and threshold context
- `resources.dependency_status`: live health for `database`, `rabbitmq`, and `ffmpeg`
- `resources.module_metrics`: per-module queue-depth and backpressure summaries

If a critical internal worker thread exits after startup, the owning module now transitions to
`error` instead of silently hanging in place. That state is visible through `module_status`,
`error_modules`, the Monitoring page, and `/system/resources`.

Manual incident status updates also propagate back into association. A confirmed incident is no
longer auto-cleared in the manager layer just because the underlying signal disappears for a later
frame; only an explicit `RESOLVED` update clears it end to end.

On a fresh start, the API resets previous frame counters and module error state before issuing the
new start command.

Verify the mixed-source control endpoints:

```bash
curl http://localhost:8000/sources
curl http://localhost:8000/system/resources
```

Runtime-generated entity images are written under `ENTITY_IMAGE_DIR`, which defaults to
`shared/output/entity_images`. If you need those files outside the container boundary, bind that
path into a persistent or shared volume.

The Operations-style POI read endpoints also expose wall-clock freshness:

- `GET /operations/pois` includes `seconds_since_update` on each card
- `GET /operations/poi` includes `seconds_since_update` for the selected search

That value is derived from the latest POI result timestamp, so UI or external clients do not
need to guess freshness from frame counts or polling cadence.

For a single-command API-side smoke validation, you can also run:

```bash
python3 scripts/control_plane_smoke_test.py --manage-compose
```

That brings up `db`, `rabbitmq`, and `webapp`, waits for readiness, exercises the mixed-source
control plane, and tears the stack back down.

To upload a staged video source:

```bash
curl -X POST http://localhost:8000/sources/uploads \
  -F "file=@/absolute/path/to/clip.mp4"
```

The uploaded media lifecycle is visible in API responses:

- `staged` after upload
- `attached` once saved into the source queue
- `active` while included in a started run

If the backing staged file is missing, the source row will surface as `failed` in `/sources` and
`/status`, and `/start` will reject the run with a `409`.

Enabled sources are also probed again during `/start`. Dead camera URLs, unreadable uploads, and
webcam indices that do not yield frames are rejected before the start command is published. The
failure is persisted on the source row so the Run page and `/system/resources` admission state can
show the exact reason.

To restart a specific module without stopping the whole stack:

```bash
curl -X POST http://localhost:8000/system/modules/INGESTOR/restart
```

### 3. Dashboard health

Open:

```text
http://localhost:3000
```

Confirm:

- navigation renders
- status panel loads
- Run page shows the mixed source queue editor
- Run page shows the per-source processing panel and resource panel
- no immediate API or CORS errors in browser devtools

### 4. Start/stop flow

Start the system:

```bash
curl -X POST http://localhost:8000/start
```

If the system refuses to start, inspect the `admission.reason` field from `/status` or
`/system/resources`. Starts are now blocked when:

- no enabled sources are configured
- one or more enabled sources have a persisted validation error
- a module is already in `error`
- configured CPU / RAM / disk thresholds are already exceeded
- `WEBAPP_REQUIRE_GPU=true` and no GPU resources are available

Once a run is accepted, ingest now waits for real frames before persisting the run row. If sources
open but then stall, ingest publishes an error instead of spinning forever on an empty frame queue.
The timeout defaults to `15` seconds and can be overridden with `input.no_frame_timeout` in the
runtime config.

Bootstrap-time ingest logs are now written separately from run logs. Use
`logging.bootstrap_log_dir` if you want failed camera starts and early ingest initialization to
stay out of the eventual per-run log directory.

If you recreated your database from an older checkout, rerun `reset-db` so long generated-media
paths are stored in text columns for `dicos.frame.path` and `dicos.poi_search.crop_dir`.

Poll status:

```bash
curl http://localhost:8000/status
```

Stop the system:

```bash
curl -X POST http://localhost:8000/stop
```

### 5. Operations routes

Once the system has produced run data, verify:

```bash
curl "http://localhost:8000/operations/runs"
curl "http://localhost:8000/operations/incidents?run_identifier=<RUN_ID>"
curl "http://localhost:8000/operations/entities?run_identifier=<RUN_ID>"
```

## GUI Launcher

The repository also includes a local GUI launcher via `python3 -m hearthlight gui` and
`run/run.sh`.

Current behavior:

- launches `python3 -m hearthlight start --open-dashboard`
- waits for `http://localhost:3000`
- opens the dashboard in a browser
- attempts to discover the Docker Desktop CLI automatically if `docker` is not on `PATH`

This launcher is environment-specific and assumes:

- a working Docker installation
- a local X11/display setup if visualization is enabled
- the machine-specific conda path in `run/run.sh`

## GPU Requirements

`docker-compose.yaml` uses explicit NVIDIA access for:

- `ingestor`
- `reid`
- `anomaly`

GPU-backed services now declare both:

- `runtime: nvidia`
- `gpus: all`

and pass through:

- `NVIDIA_VISIBLE_DEVICES`
- `NVIDIA_DRIVER_CAPABILITIES`

If the host does not have NVIDIA container support, those services may fail to start. For a CPU
only API/control-plane environment, run `db`, `rabbitmq`, and `webapp` only, and invoke
`hearthlight reset-db` when you need schema resets.

On macOS Docker Desktop specifically, treat `ingestor` and `reid` as non-runnable unless you move
the stack to a Linux host with NVIDIA container runtime. The `webapp` image has been made more
portable on arm64 by falling back to CPU `onnxruntime`, but that does not make the GPU services
portable.

## Known Compose Risks

These are worth checking before relying on the full stack:

- `shared/configs/config.yaml` must exist before the API container can become ready.
- `frontend` dependencies are installed at container startup, which increases cold-start time for
  `webapp`.
- the checked-in example config uses placeholder RTSP URLs, so `ingestor` will still fail until
  operators replace them with real sources

## Troubleshooting

### API container exits immediately

Check:

- `.env` exists
- `shared/configs/config.yaml` exists
- `shared/configs/config.yaml` was copied from `shared/configs/example_config.yaml`
- database container is reachable
- RabbitMQ is reachable

### Dashboard does not load

Check:

- `webapp` logs for `npm install` or `npm start` failures
- local ports `3000` and `8000` are free
- browser console for failed requests to `127.0.0.1:8000`

### Ingestor or ReID fails on startup

Check:

- NVIDIA runtime availability
- camera sources in `shared/configs/config.yaml`
- model dependencies inside the built images

### Full `docker compose up` fails because of worker services

The core worker stack is behind the `pipeline` profile. Start the minimal API stack first, then
enable pipeline workers explicitly when the host supports them:

```bash
docker compose up -d db rabbitmq webapp
docker compose --profile pipeline up ingestor reid anomaly association
```
