# Launcher Guide

The primary install and startup entrypoint is now the CLI launcher:

```bash
pip install hearthlight
hearthlight onboard
hearthlight start --interactive
```

Available commands:

- `hearthlight onboard`
- `hearthlight start`
- `hearthlight stop`
- `hearthlight reset-db`
- `hearthlight status`
- `hearthlight list-models`
- `hearthlight dashboard`
- `hearthlight gui`

## Onboarding

For a clean local checkout, start with the onboarding flow:

```bash
hearthlight onboard
```

The onboarding command walks through:

1. Checking system packages such as `libpq-dev` and `python3-dev` on Linux, or the platform equivalents on macOS.
2. Copying `shared/configs/example_config.yaml` to `shared/configs/config.yaml`.
3. Installing `requirements.txt` files from `webapp`, `ingestor`, `reid`, `anomaly`, and `association`.
4. Writing `.env` defaults, including Telegram and Apple Messages trigger subscription settings.
5. Detecting whether CUDA is usable and writing CPU or GPU launcher defaults into `.env`.
6. Starting Docker `db` and `rabbitmq`, then running `reset-db`.
7. Seeding Telegram and Apple Messages trigger subscriptions from `.env` when values are provided.

Shell wrapper:

```bash
bash scripts/onboard.sh
```

To accept the steps without prompts:

```bash
hearthlight onboard --yes
```

## Startup options

The launcher exposes startup-time optionality without manually editing
`shared/configs/config.yaml` first.

You can choose:

- config template
- camera/source preset
- detector model
- tracker implementation
- detector device
- pose enablement, pose model, and pose device
- feature extractor model and device
- CPU or CUDA execution profile
- API-only or full pipeline service mode
- `CUDA_VISIBLE_DEVICES`
- whether to skip `reset-db`
- whether to open the dashboard automatically
- whether to run with reload mode

## What the launcher does

1. Lists available config templates from `shared/configs/`.
2. Discovers detector, tracker, and feature-extractor choices from registry
   YAML files under `shared/configs/registries/`, and pose choices from config
   templates.
3. Lets you choose API vs pipeline service mode.
4. Lets you choose CPU or CUDA mode.
5. Writes a generated config under `shared/configs/generated/`.
6. Copies the generated config to `shared/configs/config.yaml`.
7. Starts Docker Compose with:
   - base compose for CPU mode
   - base compose plus `run/docker-compose.cuda.yaml` for CUDA mode

## Examples

CPU startup:

```bash
python3 -m hearthlight start \
  --template active \
  --mode api \
  --profile cpu \
  --detector yolox-s \
  --tracker bytetrack \
  --feature-extractor transreid-market1501 \
  --hide-video
```

Use one config template for runtime/model defaults and a different saved config
for camera sources and zone definitions:

```bash
python3 -m hearthlight start \
  --template example \
  --source-preset master_config \
  --profile cpu
```

CUDA startup:

```bash
python3 -m hearthlight start \
  --mode pipeline \
  --template master_config \
  --profile cuda \
  --cuda-visible-devices 0 \
  --detector yolox-s \
  --pose-enabled \
  --pose-model rtmo-s \
  --feature-extractor transreid-market1501 \
  --open-dashboard
```

List discovered templates and model options:

```bash
python3 -m hearthlight list-models
```

Dry-run a launch and only write the generated config:

```bash
python3 -m hearthlight start --interactive --dry-run
```

Reset DB directly via host Python execution (instead of compose `reset_db` service):

```bash
python3 -m hearthlight reset-db
```

Inspect Docker Compose service status:

```bash
python3 -m hearthlight status
```

## Notes

- CPU mode uses the base `docker-compose.yaml`.
- CUDA mode adds `run/docker-compose.cuda.yaml`.
- `--mode api` starts the lighter local control stack; `--mode pipeline` starts
  the AI workers as well.
- CUDA services only get NVIDIA runtime settings when you explicitly choose the
  CUDA profile.
- Generated configs are written to `shared/configs/generated/` and then copied
  to `shared/configs/config.yaml`.
- `--source-preset` replaces the top-level `input`, `passenger_zones`, and
  `tray_zones` blocks from the selected preset template.
- `--dry-run` writes only the generated preview config and does not replace
  `shared/configs/config.yaml`.
- The launcher sets both `tracking.tracker` and `tracking.track_method` for
  compatibility with older and newer config shapes in this repo.
- The launcher does not download weights automatically; it only selects from
  configured model names and registry entries already known to the repo.
- `python3 -m hearthlight gui` is a thin wrapper around the same CLI entrypoint, so
  the CLI and GUI stay aligned.
- Legacy `python3 run/run.py ...` remains available as a temporary compatibility
  wrapper and prints a deprecation notice.
