# Hearthlight
![Hearthlight logo](docs/assets/hearthlight.png)
Real-time anomaly-detection backend for analyzing CCTV feeds, identifying unusual activity, and
supporting incident workflows.

Current release: `0.8.0`

- release notes: [CHANGELOG.md](/Users/galvinwidjaja/code/cursor/hearthlight/CHANGELOG.md:1)
- API, CLI, frontend package metadata, and macOS bundle metadata are aligned to `0.8.0`

## Repository Overview

Main runtime services:

- `ingestor`: video ingestion, detection, tracking, and message fan-out
- `reid`: persistent ID assignment for people and bags, plus POI support
- `association`: owner inference and incident generation
- `anomaly`: pluggable post-detection anomaly sidecar
- `webapp`: FastAPI backend plus React dashboard
- `rabbitmq`: inter-service messaging
- `db`: PostgreSQL persistence

Shared infrastructure and contracts live under `shared/`.

Persistence now uses a single Postgres server on `db:5432` with two active schemas:

- `runtime`: runtime entities such as runs, incidents, entities, and recordings
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
- Changelog: `CHANGELOG.md`
- Container runbook: `docs/containers.md`
- Security notes: `docs/security.md`
- Testing guide: `docs/testing.md`
- Deployment seeds/init assets: `deploy/README.md`
- Project roadmap: `TODO.md`

## Model Selection and Alerts

Hearthlight now has one consistent model-selection story:

- the launcher CLI is the host-side startup and model-inventory path
- the Settings UI is the control-plane binding path for live runs

The effective runtime model set is resolved per source:

- a source-specific override wins if it is saved on the source row
- otherwise the saved default binding for that stage is used

The current model stages are:

- detector
- tracker
- Heuristic Filter
- anomaly detection

Operator-facing surfaces use readable names such as `YOLOX Small` and `TransReID Person + Hybrid Bag`.
Stable internal keys such as `builtin_yolox_s_cpu` remain unchanged underneath for storage,
automation, and compatibility.

Triggered alerts follow the same control-plane model:

- detector alert targets come from the effective detector model metadata for that source
- anomaly object and anomaly activity targets come only from the saved anomaly prompt settings
- anomaly `1-10` trigger cutoffs now live on the anomaly rule itself, not in the saved prompt config
- the browser does not parse YAML or registry files directly; the backend prepares those option lists

Validated detector class surface for the current default COCO-trained YOLOX detector family:

- raw detector classes exposed by the model metadata: the full COCO 80-class surface
- example classes: `person`, `bicycle`, `car`, `backpack`, `handbag`, `suitcase`, `truck`, `cell phone`
- live Hearthlight detector trigger IDs: `PERSON`, `BAG`
- current runtime mapping:
  - `person` -> `PERSON`
  - `backpack`, `handbag`, `suitcase` -> `BAG`

This means the model library shows the full raw detector class surface, while trigger rules currently
match against the normalized live detector IDs that the pipeline emits.

## Current State of the Docs

Use this README plus `docs/architecture.md`, `docs/repository.md`, and
`docs/initialization.md` as the source of truth for the current repository.

## 0.8.0 Highlights

- source labels now default intelligently to `Camera N`, `Webcam N`, or the uploaded video filename without its extension
- source settings now include `Process every Nth frame` so each camera can lower detector and anomaly load before inference
- source-level AI overrides hide automatically when `Enable Video AI` is turned off
- the Rules page is now split into `Detection Rules` and `Anomaly Detection Rules`, with multi-camera targeting and per-rule anomaly cutoff values
- the model library now shows qualitative processing-rate guidance, and Model Logs surfaces recent measured cadence by model stage
- anomaly detection Stage 2 now supports third-party API-backed model entries for `Chatgpt`, `Claude`, and a generic `Lauretta API` endpoint when their credentials are configured
- theme selection now lives in `Settings > Appearance`, with a workspace-wide backend setting plus browser startup cache
- the frontend now runs on Vite instead of `react-scripts`
- anomaly Stage 1 and anomaly detection defaults now have local CPU/CUDA/MLX-safe registry fallbacks
- connectors are presented as a cleaner single-column list with configured-state badges

## Prerequisites

- Docker Engine with Docker Compose support
- NVIDIA container runtime for GPU-backed services (`ingestor`, `reid`) if you want full
  inference
- A populated runtime config at `shared/configs/config.yaml`
- `.env` at the repository root

Optional remote anomaly-model credentials:

- `OPENAI_API_KEY` and optional `OPENAI_MODEL_NAME` for the `Chatgpt` model option
- `ANTHROPIC_API_KEY` and optional `ANTHROPIC_MODEL_NAME` for the `Claude` model option
- `LAURETTA_API_KEY` and `LAURETTA_API_BASE_URL` for the `Lauretta API` model option

Minimum practical local tooling:

- Python 3.10+ for lightweight unit tests
- Node 18+ if you want to run frontend tests outside Docker

## Environment Files

Create `.env`:

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=root
POSTGRES_DB=hearthlight
POSTGRES_HOST=db
POSTGRES_PORT=5432

RABBITMQ_HOST=rabbitmq
RABBITMQ_EXCHANGE=test
```

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=root
POSTGRES_DB=hearthlight
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_EXT_HOST=localhost
POSTGRES_EXT_PORT=5433
POSTGRES_HOST_PORT=5433
RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_HOST_PORT=5673
RABBITMQ_MANAGEMENT_HOST_PORT=15672
RABBITMQ_EXCHANGE=test
WEBAPP_API_HOST_PORT=8000
WEBAPP_UI_HOST_PORT=3000
```

## Runtime Config

Bootstrap `shared/configs/config.yaml` from the checked-in example:

```bash
pip install hearthlight
hearthlight onboard
```

The onboarding flow can:

- check platform dependencies such as `libpq-dev` and `python3-dev`
- copy `shared/configs/example_config.yaml` to `shared/configs/config.yaml`
- install service `requirements.txt` files
- optionally seed the central mounted model inventory with `--mount-default-models` or repeated `--mount-model` flags
- require API credentials during CLI onboarding when mounting `chatgpt_api_stage_2`, `claude_api_stage_2`, or `lauretta_api_stage_2`, and allow provider-specific model name strings
- detect CUDA and write CPU/GPU launcher defaults
- write `.env` notification defaults for Telegram and Apple Messages
- seed Telegram and Apple Messages trigger subscriptions from `.env` after `reset-db`

Shell wrapper:

```bash
bash scripts/onboard.sh
```

Manual fallback:

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

- thresholds and tuning values
- default stage bindings and compatibility config for plugin-provided models
- output paths
- compatibility config blocks that the launcher still writes for older runtime readers

Plugin discovery now happens at server startup through manifest bundles under `shared/plugins/`.
Models, triggers, connectors, and rule-set templates are all loaded from that plugin catalog on
restart, and missing plugin manifests are soft-disabled in the control-plane database rather than
hard-deleted.

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

The recommended startup path is the Hearthlight CLI launcher. It adds startup-time choice over:

- config template
- camera/source preset
- detector model inventory
- tracker inventory
- CPU or CUDA execution
- visible CUDA devices
- dashboard auto-open and DB reset behavior

Interactive launch:

```bash
hearthlight start --interactive
```

Inspect available templates and model inventory:

```bash
hearthlight list-models
```

Start in CPU mode:

```bash
hearthlight start --template active --profile cpu
```

Start with one template for runtime settings and another template for camera and zone presets:

```bash
hearthlight start --template example --source-preset master_config --profile cpu
```

Start in CUDA mode:

```bash
hearthlight start --template master_config --profile cuda --cuda-visible-devices 0
```

Preview a launch without changing the active config or starting Docker:

```bash
hearthlight start --interactive --dry-run
```

Stop the stack:

```bash
hearthlight stop
```

Open the dashboard:

```bash
hearthlight dashboard
```

Reset database state directly from the CLI:

```bash
hearthlight reset-db
```

Show service health/status from Docker Compose:

```bash
hearthlight status
```

The launcher will:

- detect API-only vs full pipeline startup based on host defaults, with one full-system startup path
- discover config templates from `shared/configs/`
- discover detector, tracker, ReID, and anomaly model inventory from the registry-backed control-plane catalog
- write the generated startup config to `shared/configs/generated/`
- copy the selected launch config to `shared/configs/config.yaml`
- use base `docker-compose.yaml` for CPU runs
- add `run/docker-compose.cuda.yaml` only for CUDA runs

If you still want a local GUI wrapper, it is available here:

```bash
hearthlight gui
```

If you want to launch manually without `hearthlight start`, bring up infrastructure,
run a direct reset, then start webapp:

```bash
docker compose up -d db rabbitmq
hearthlight reset-db
docker compose up webapp
```

Enable the full AI pipeline explicitly:

```bash
docker compose up ingestor reid anomaly association
```

`docker-compose.yaml` gates AI worker services behind the optional `pipeline` profile, so a plain
local startup does not require the heavier worker stack.

If video display is enabled in config and you are on Linux/X11, you may also need:

```bash
sudo xhost +local:
```

Startup and launcher documentation:

```bash
run/README.md
```

macOS packaged app documentation:

```bash
docs/macos_dmg.md
```

**Releases:** align versions in `pyproject.toml` and `frontend/package.json`, then push a **`v*`** tag (details in `docs/macos_dmg.md`).

After startup, open the frontend in your browser at `http://localhost:3000`,
configure sources, save default model bindings, save anomaly prompts, define any triggered alerts,
and then use the dashboard start/stop controls to run the pipeline.

Then open:

- frontend: `http://localhost:3000`
- API through the same origin proxy: `http://localhost:3000/api`
- direct API for scripts and debugging: `http://localhost:8000`

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

- maintains person/bag state
- infers ownership relationships
- creates incidents such as unattended bags
- processes incident resolutions

Entry point: `association/main.py`

### Anomaly

- consumes normalized frame/tracking context after ReID
- resolves the configured anomaly adapter per source
- persists normalized anomaly events
- republishes anomaly events for downstream consumers

Entry point: `anomaly/main.py`

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
- `GET /model-options`
- `GET /model-bindings`
- `PUT /model-bindings`
- `GET /settings/appearance`
- `PUT /settings/appearance`
- `GET /settings/anomaly-prompts`
- `PUT /settings/anomaly-prompts`
- `GET /settings/alert-rules`
- `PUT /settings/alert-rules`
- `GET /settings/alert-rule-options`
- `GET /system/model-health`
- `GET /feeds/algorithm`
- `GET /monitoring/overview`
- `GET /system/resources`
- `POST /system/modules/{module_name}/restart`
- `POST /camera_stream` (deprecated compatibility shim)
- `GET /camera_streams` (compatibility view)
- `GET /sources/{source_id}/preview.mjpeg`
- `POST /register_poi`
- `GET /operations/runs`
- `GET /operations/incidents`
- `GET /operations/incident`
- `GET /operations/entities`
- `GET /operations/entity`
- `GET /operations/events`
- `POST /operations/update_incident`
- `GET /operations/incident_video/`
- `GET /operations/pois`
- `GET /operations/poi`

`GET /operations/events` is a Server-Sent Events stream that the incidents and entities interfaces
can subscribe to for run-list, incident, and entity update notifications, with slower polling
retained as a fallback.

`GET /sources/{source_id}/preview.mjpeg` is a backend MJPEG proxy for the Live page. It allows the
browser UI to preview RTSP-backed or otherwise non-browser-native live sources as long as the
backend container can open the source.

`GET /model-options` and `GET /settings/alert-rule-options` are backend-prepared option catalogs.
They return readable display names while preserving stable model keys and exact saved anomaly prompt
strings for automation and alert creation.

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
- Frontend tests require a consistent modern Node/npm toolchain. On this machine Node is
  `22.21.0`, but the `npm` command currently resolves to an incompatible global install path, so
  frontend test execution is still blocked until the npm installation is fixed.
- Container preflight can be checked without Docker startup by running
  `python3 scripts/container_preflight.py`.
