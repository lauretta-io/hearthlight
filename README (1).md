# DHS Passenger Detection

Real-time security backend for detecting and tracking people, bags, and related incidents from
CCTV feeds in a screening environment.

The original internal write-up for this system is captured in the 2023 "DHS Backend
(Proto-SAIB)" PDF. This repository README updates that material to match the current codebase.

## Repository Overview

Main runtime services:

- `ingestor`: video ingestion, detection, tracking, and message fan-out
- `reid`: persistent ID assignment for people and bags, plus POI support
- `association`: owner inference and incident generation
- `anomaly`: pluggable post-detection anomaly sidecar
- `exporter`: Kafka-compatible micro-batch export worker
- `webapp`: FastAPI backend plus React dashboard
- `rabbitmq`: inter-service messaging
- `db`: PostgreSQL persistence

Shared infrastructure and contracts live under `shared/`.

Persistence now uses a single Postgres server on `db:5432` with two active schemas:

- `dicos`: runtime entities such as runs, incidents, entities, and recordings
- `control`: operator-managed sources, staged uploads, and resource telemetry

Operational telemetry also includes resource-drift summaries so the control plane can surface CPU,
memory, disk, and GPU deltas between snapshots instead of only absolute values.

Operator UI note:

- the React dashboard no longer exposes a standalone POI Search page
- runtime control and monitoring live under `Settings`
- POI data remains available through the backend APIs

More detail:

- Architecture notes: `docs/architecture.md`
- Repository guide: `docs/repository.md`
- Initialization guide: `docs/initialization.md`
- Container runbook: `docs/containers.md`
- Security notes: `docs/security.md`
- Testing guide: `docs/testing.md`
- Deployment seeds/init assets: `deploy/README.md`

## Current State of the Docs

The old README and PDF were partially stale. In particular:

- container and entrypoint names changed
- the frontend is a React app, not just a static dashboard page
- the current association service includes gun-related incident flow
- some historically documented modules are not present in this checkout

Use the PDF for background and intent. Use this README plus `docs/architecture.md`,
`docs/repository.md`, and `docs/initialization.md` for the current repo.

## Prerequisites

- Docker Engine with Docker Compose support
- NVIDIA container runtime for GPU-backed services (`ingestor`, `reid`) if you want full
  inference
- A populated runtime config at `shared/configs/config.yaml`
- `.env` at the repository root
- `foia.env` only if you plan to run the optional FOIA profile

Minimum practical local tooling:

- Python 3.10+ for lightweight unit tests
- Node 18+ if you want to run frontend tests outside Docker

## Environment Files

Create `.env`:

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=root
POSTGRES_DB=delos
POSTGRES_HOST=db
POSTGRES_PORT=5432

RABBITMQ_HOST=rabbitmq
RABBITMQ_EXCHANGE=test
```

Create `foia.env` only if you plan to run the optional FOIA profile:

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=root
POSTGRES_DB=foia
POSTGRES_HOST=foia_db
POSTGRES_PORT=5432
POSTGRES_EXT_HOST=localhost
POSTGRES_EXT_PORT=5424

DHS_USER=postgres
DHS_PASSWORD=root
DHS_DB=delos
DHS_HOST=db
DHS_PORT=5432
```

## Runtime Config

Bootstrap `shared/configs/config.yaml` from the checked-in example:

```bash
cp shared/configs/example_config.yaml shared/configs/config.yaml
```

At minimum, validate:

- model/runtime tuning
- output directories
- ReID thresholds and feature settings
- journey / incident timing parameters

Source definitions are no longer expected to live primarily in `config.yaml`. The web control
plane persists them in Postgres under `control.input_source_template`, and `/start` merges the
enabled source queue into the in-memory runtime config before publishing the system start command.

The runtime config still owns:

- enabled tasks per camera
- model registries, default stage bindings, and exporter sink selection
- thresholds
- output paths

## Startup

Initialize any required submodules first:

```bash
git submodule update --init --recursive
```

Build containers:

```bash
python3 scripts/container_preflight.py
docker compose build
```

For an automated, host-aware build validation instead of a raw compose build, use:
```bash
python3 scripts/docker_build_test.py
```

The recommended startup path is the CLI launcher. It adds startup-time choice over:

- service mode (`api` or `pipeline`)
- config template
- camera/source preset
- detector model
- tracker
- pose enablement and pose model
- feature extractor model
- CPU or CUDA execution
- visible CUDA devices
- dashboard auto-open and DB reset behavior

Interactive launch:

```bash
python3 run/run.py start --interactive
```

Inspect available templates and model names:

```bash
python3 run/run.py list-models
```

Start in CPU mode:

```bash
python3 run/run.py start --template active --profile cpu
```

Start with one template for runtime settings and another template for camera and zone presets:

```bash
python3 run/run.py start --template example --source-preset master_config --profile cpu
```

Start in CUDA mode:

```bash
python3 run/run.py start --mode pipeline --template master_config --profile cuda --cuda-visible-devices 0
```

Preview a launch without changing the active config or starting Docker:

```bash
python3 run/run.py start --interactive --dry-run
```

Stop the stack:

```bash
python3 run/run.py stop
```

Open the dashboard:

```bash
python3 run/run.py dashboard
```

The launcher will:

- detect API-only vs full pipeline startup based on host defaults, with `--mode` or `DELOS_DOCKER_MODE` as overrides
- discover config templates from `shared/configs/`
- discover detector, tracker, pose, and feature-extractor choices from repo configs and `shared/utils/download_weights.py`
- write the generated startup config to `shared/configs/generated/`
- copy the selected launch config to `shared/configs/config.yaml`
- use base `docker-compose.yaml` for CPU runs
- add `run/docker-compose.cuda.yaml` only for CUDA runs

If you still want a local GUI wrapper, it is available here:

```bash
python3 run/run.py gui
```

If you want to launch manually without the CLI, initialize the database schema and start the
default local control stack:

```bash
docker compose up db rabbitmq reset_db webapp
```

Enable the full AI pipeline explicitly:

```bash
docker compose --profile pipeline up ingestor reid anomaly association exporter
```

`docker-compose.yaml` now gates AI worker services behind the optional `pipeline` profile and FOIA
behind the optional `foia` profile, so a plain local startup does not require the worker stack,
the `FOIA/` directory, or `foia.env`. Enable FOIA explicitly:

```bash
docker compose --profile foia up foia_db foia foia_webapp
```

If video display is enabled in config and you are on Linux/X11, you may also need:

```bash
sudo xhost +local:
```

Startup and launcher documentation:

```bash
run/README.md
```

After startup, open the frontend in your browser at `http://localhost:3000`,
configure the camera sources, and use the dashboard start/stop controls to run
the pipeline.

Then open:

- frontend: `http://localhost:3000`
- API: `http://localhost:8000`

You can also use the launcher scripts in `run/` if that matches your environment better.

## Service Responsibilities

### Ingestor

- opens configured video sources
- reads frames continuously
- runs detection/tracking
- forwards frame-level outputs downstream
- publishes run metadata and status updates

Entry point: `ingestor/main.py`

### ReID

- consumes tracked entities from the ingestor path
- assigns persistent or temporary IDs for people and bags
- emits ID updates and POI-related data

Entry point: `reid/main.py`

### Association

- maintains person/bag/gun state
- infers ownership relationships
- creates incidents such as unattended bags and gun events
- processes incident resolutions

Entry point: `association/main.py`

### Anomaly

- consumes normalized frame/tracking context after ReID
- resolves the configured anomaly adapter per source
- persists normalized anomaly events
- republishes anomaly events for downstream consumers

Entry point: `anomaly/main.py`

### Exporter

- reads persisted incidents, entities, anomalies, and asset references from Postgres
- batches records on configurable thresholds
- publishes Kafka-compatible JSON envelopes per topic
- reports exporter health and backlog into the control plane

Entry point: `exporter/main.py`

### Webapp

- exposes control and status endpoints
- serves incident/entity/POI data
- updates incident state
- streams incident video clips

Entry points: `webapp/main.py`, `webapp/run.py`

## API Surface

Important routes exposed by the FastAPI service:

- `POST /start`
- `POST /stop`
- `GET /status`
- `GET /sources`
- `PUT /sources`
- `POST /sources/uploads`
- `DELETE /sources/uploads/{id}`
- `GET /models`
- `GET /models/{stage}`
- `GET /model-bindings`
- `PUT /model-bindings`
- `GET /export-sinks`
- `GET /system/model-health`
- `GET /feeds/algorithm`
- `GET /monitoring/overview`
- `GET /system/resources`
- `POST /system/modules/{module_name}/restart`
- `POST /camera_stream` (deprecated compatibility shim)
- `GET /camera_streams` (compatibility view)
- `GET /sources/{source_id}/preview.mjpeg`
- `POST /register_poi`
- `GET /genetec/runs`
- `GET /genetec/incidents`
- `GET /genetec/incident`
- `GET /genetec/entities`
- `GET /genetec/entity`
- `GET /genetec/events`
- `POST /genetec/update_incident`
- `GET /genetec/incident_video/`
- `GET /genetec/pois`
- `GET /genetec/poi`

`GET /genetec/events` is a Server-Sent Events stream that the incidents and entities interfaces
can subscribe to for run-list, incident, and entity update notifications, with slower polling
retained as a fallback.

`GET /sources/{source_id}/preview.mjpeg` is a backend MJPEG proxy for the Live page. It allows the
browser UI to preview RTSP-backed or otherwise non-browser-native live sources as long as the
backend container can open the source.

## Security Notes

The web layer now supports:

- optional API-key protection via `WEBAPP_API_KEY`
- configurable CORS origins via `WEBAPP_ALLOWED_ORIGINS`
- POI image-count limits via `POI_MAX_IMAGES`
- browser video upload staging under `SOURCE_UPLOAD_DIR`
- generated entity image storage under `ENTITY_IMAGE_DIR`
- resource sampling plus start admission control
- targeted module restart requests through the API
- sanitized POI crop storage paths
- deterministic entity image output paths grouped by run and camera
- unauthenticated `/healthz` and `/readyz` for container probes
- health-gated infra startup in `docker-compose.yaml`

See `docs/security.md` for details.

## Generated Media Paths

The backend stores generated entity images under `ENTITY_IMAGE_DIR`, which defaults to:

```text
shared/output/entity_images
```

Generated files are grouped by run and camera:

```text
shared/output/entity_images/run_<run_id>/camera_<camera_id>/<journey_node_id>.jpg
```

That directory is used for backend-generated entity crops later returned through the entity and
incident APIs.

## Testing

Run the lightweight Python unit tests:

```bash
python3 -m unittest discover -s tests -v
```

These tests currently focus on stable shared utilities and are meant to be fast local coverage,
not end-to-end system verification.

For more detail, see `docs/testing.md` and `docs/containers.md`.

## Known Gaps and Caveats

- Full backend validation still depends on Docker, RabbitMQ, Postgres, and usually GPU access.
- `shared/configs/config.yaml` is gitignored; the repo ships `shared/configs/example_config.yaml`
  as the bootstrap source.
- GPU-backed services still require real camera sources and NVIDIA container support. The checked-
  in example config uses placeholder RTSP URLs and is not sufficient for full pipeline validation.
- On Apple Silicon / Linux arm64 builds, the `webapp` image now falls back to CPU `onnxruntime`
  and skips `tensorrt`, but the GPU inference services still are not expected to run under Docker
  Desktop for macOS.
- The attached historical PDF describes clothing segmentation and tray-specific flows that are
  not directly represented as runnable modules in the current repository.
- Frontend tests require a consistent modern Node/npm toolchain. On this machine Node is
  `22.21.0`, but the `npm` command currently resolves to an incompatible global install path, so
  frontend test execution is still blocked until the npm installation is fixed.
- Container preflight can be checked without Docker startup by running
  `python3 scripts/container_preflight.py`.
