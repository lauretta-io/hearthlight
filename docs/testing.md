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

To verify the already-running local UI proxy without changing source rows or starting a run:

```bash
python3 scripts/control_plane_smoke_test.py --base-url http://127.0.0.1:3000/api --defaults-only
```

Or let the script manage the minimal compose stack itself:

```bash
python3 scripts/control_plane_smoke_test.py --manage-compose
```

It exercises:

- `/sources/uploads`
- `/sources`
- `/models`
- `/model-options`
- `/model-bindings`
- `/system/model-health`
- `/system/resources`
- `/status`
- `/camera_streams`
- `/start` and `/stop`

The script cleans up its temporary source rows and uploaded media when it finishes. With
`--manage-compose`, it also starts and stops `db`, `rabbitmq`, and `webapp`.

## Hosted production verifier

Use the deployment verifier for hosted completion evidence:

Hosted ingress clients should be configured with `HEARTHLIGHT_INGRESS_CLIENT_KEYS` before running
acceptance benchmarks. When configured, invalid keys return `401`, and usage ledger rows are written
per hashed client key and processed bucket.

```bash
python3 scripts/benchmark_queue_ingress.py \
  --base-url https://hearthlight.example.com/api \
  --endpoint /v1/hearthlight/anomaly-submissions \
  --client-key client-a="$HEARTHLIGHT_CLIENT_KEY_A" \
  --client-key client-b="$HEARTHLIGHT_CLIENT_KEY_B" \
  --auth-header Authorization \
  --auth-scheme bearer \
  --repeat 3 \
  --requests-per-repeat 1000 \
  --concurrency 64 \
  --output shared/output/benchmarks/queue_only_run_1.json
```

Generate the settled benchmark JSON before the verifier with the worker service, GPU resize path,
and live provider routing enabled:

```bash
python3 scripts/benchmark_settled_ingress.py \
  --base-url https://hearthlight.example.com/api \
  --endpoint /v1/hearthlight/anomaly-submissions \
  --status-endpoint-template /v1/hearthlight/anomaly-submissions/{submission_id} \
  --client-key client-a="$HEARTHLIGHT_CLIENT_KEY_A" \
  --client-key client-b="$HEARTHLIGHT_CLIENT_KEY_B" \
  --auth-header Authorization \
  --auth-scheme bearer \
  --requests 100 \
  --concurrency 16 \
  --settle-timeout-seconds 180 \
  --output shared/output/benchmarks/settled_run_1.json
```

```bash
python3 scripts/run_deployment_verification.py \
  --base-url https://hearthlight.example.com \
  --api-key "$HEARTHLIGHT_ADMIN_API_KEY" \
  --provider-key openai \
  --ingress-client-key "$HEARTHLIGHT_CLIENT_KEY_A" \
  --invalid-ingress-client-key "$HEARTHLIGHT_INVALID_CLIENT_KEY" \
  --queue-benchmark-json shared/output/benchmarks/queue_only_run_1.json \
  --queue-benchmark-json shared/output/benchmarks/queue_only_run_2.json \
  --settled-benchmark-json shared/output/benchmarks/settled_run_1.json
```

This is the acceptance-facing audit command for the hosted stack. It requires runtime diagnostics,
GPU media smoke, live provider smoke, end-to-end smoke, and queue-only median throughput of at
least 200 submissions/sec across repeated benchmark results with multiple client keys.
Runtime diagnostics are strict by default: they must prove the production profile uses pgbouncer,
S3 object storage, hosted local-stack settings, and the tuned API/worker values from the Compose
reference deployment. `--skip-runtime-profile-check` is available only for non-acceptance local
debugging.
Live provider smoke must prove `request_reached_provider=true`,
`normalized_result_returned=true`, and `provider_response_validated=true`; a successful HTTP
status without a recognized OpenAI-compatible, Claude-compatible, or Lauretta response shape is a
failed hosted proof.
When settled benchmark JSON is supplied, the verifier records ingress and settled throughput as
separate min/median/max summaries and fails if the settled benchmark reports unexpected submission
or settle failures. Settled throughput below 200/sec is still recorded as a secondary optimization
target rather than the primary acceptance gate.
The ingress contract check also submits a small inline asset and reads it back from the hosted
object store through the submission asset endpoint, so object persistence is part of the verifier
rather than a manual inspection step.

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

The secure Anomaly LLM model settings workflow now also has browser-driven E2E
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
- no raw Anomaly LLM model secrets retained in browser storage

Use a modern Node/npm toolchain for this. The local machine used for this
update has Node `22.21.0`.
