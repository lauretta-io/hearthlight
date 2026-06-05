# Testing Guide

## What can be tested locally without the full stack

The repository currently has a small dependency-light Python test suite for shared utility code:

```bash
python3 -m unittest discover -s tests -v
```

These tests cover:

- retry behavior in `shared/utils/backoff.py`
- timing/reporting behavior in `shared/utils/timer.py`
- task extraction logic in `shared/utils/config.py`
- mixed-source utility helpers in `shared/utils/input_sources.py`
- resource snapshot and admission logic in `shared/utils/resource_monitor.py`
- status derivation and compatibility helpers in `shared/utils/system_state.py`

The API model tests also cover the new `InputSource` contract when `pydantic` is installed in the
local Python environment. In the current lean local environment those tests are skipped.

## What still requires Docker Compose

The following parts of the system are not practical to validate with plain local unit tests:

- model inference in `ingestor`
- GPU-backed ReID flows in `reid`
- RabbitMQ message choreography between modules
- database-backed API flows in `webapp`
- full incident generation in `association`

For those paths, use Docker-based validation after creating `.env` and
`shared/configs/config.yaml`.

Recommended validation flow:

```bash
python3 scripts/container_preflight.py
docker compose up -d db rabbitmq
hearthlight reset-db
docker compose up webapp
docker compose up ingestor reid anomaly association
```

For repeatable image-build validation, use the build test script:

```bash
python3 scripts/docker_build_test.py
```

It chooses a sensible default for the current host:

- Apple Silicon / Darwin: builds the API-only path (`rabbitmq`, `webapp`)
- Linux x86_64: builds the full pipeline stack (`rabbitmq`, `webapp`, `ingestor`, `reid`, `association`, `anomaly`)

You can override that explicitly:

```bash
python3 scripts/docker_build_test.py
python3 scripts/docker_build_test.py
```

Or target a custom subset:

```bash
python3 scripts/docker_build_test.py --service webapp --service rabbitmq
```

If you only want to validate the API-side containers without attempting GPU/video ingestion, this
is a useful narrower smoke test:

```bash
docker compose up -d db rabbitmq
hearthlight reset-db
docker compose up webapp
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

For the new mixed-source control plane specifically, there is also a repeatable smoke test:

```bash
python3 scripts/control_plane_smoke_test.py
```

Or let the script manage the minimal compose stack itself:

```bash
python3 scripts/control_plane_smoke_test.py --manage-compose
```

It exercises:

- `/sources/uploads`
- `/sources`
- `/models`
- `/model-bindings`
- `/system/model-health`
- `/system/resources`
- `/status`
- `/camera_streams`
- `/start` and `/stop`

The script cleans up its temporary source rows and uploaded media when it finishes. With
`--manage-compose`, it also starts and stops `db`, `rabbitmq`, and `webapp`.

On Apple Silicon / Linux arm64, this API-only path is the realistic Docker validation target. The
`webapp` image can now build with CPU `onnxruntime` and without `tensorrt`/`triton`, while
`ingestor` and `reid` still depend on NVIDIA runtime support that Docker Desktop on macOS does not
provide.

Then verify:

- frontend loads on `http://localhost:3000`
- API root responds on `http://localhost:8000/`
- `/sources` loads a persisted mixed-source queue
- `/system/resources` returns resource telemetry
- `/status` changes from `idle` to `running` after `/start`
- `/status` includes `sources`, `resources`, and `admission`
- incidents and entities appear under `/operations/*`

For a fuller startup and troubleshooting checklist, see `docs/containers.md`.

## Frontend Tests

The frontend still uses `react-scripts test` from `frontend/package.json`:

```bash
cd frontend
npm test -- --watchAll=false
```

The secure Stage 2 provider settings workflow now also has browser-driven E2E
coverage through Playwright:

```bash
cd frontend
npm run test:e2e
```

The Playwright suite stubs the backend API so operators can verify:

- masked-secret persistence
- API-key rotation behavior
- endpoint changes
- provider test success/failure handling
- no raw Stage 2 provider secrets retained in browser storage

Use a modern Node/npm toolchain for this. The local machine used for this
update has Node `22.21.0`.
