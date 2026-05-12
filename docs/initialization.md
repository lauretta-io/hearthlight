# Initialization Guide

This guide covers the full initialization routine from a fresh checkout to a running UI.

## 1. Prepare local prerequisites

- Docker Engine with Compose support
- `.env` at the repository root
- `shared/configs/config.yaml`
- NVIDIA container support only if you plan to run `--profile cuda`

Optional:

- X11 display access if `show_vid` is enabled and you run on Linux

## 2. Run onboarding

For a clean local checkout:

```bash
pip install hearthlight
hearthlight onboard
```

Shell wrapper:

```bash
bash scripts/onboard.sh
```

That flow checks system packages, copies `shared/configs/example_config.yaml` to
`shared/configs/config.yaml`, installs service requirements, writes notification
defaults for Telegram and Apple Messages into `.env`, seeds those subscriptions
after `reset-db` when values are present, and chooses CPU or CUDA launcher
defaults based on the local machine.

If you need to do the config step manually:

```bash
cp shared/configs/example_config.yaml shared/configs/config.yaml
```

Then review:

- default model bindings for detector, tracker, person ReID, anomaly Stage 1, and anomaly Stage 2
- output paths
- saved templates under `shared/configs/saved_configs/`
- model registry files under `shared/configs/registries/`

## 3. Run preflight

```bash
python3 scripts/container_preflight.py
```

This catches missing Docker, env files, config files, and optional profile gaps before a full
startup attempt.

## 4. Choose startup mode

Use the launcher for host-aware startup:

```bash
hearthlight start --interactive
```

Inspect the current registry-backed model inventory first if you want to confirm available options:

```bash
hearthlight list-models
```

The launcher can choose:

- service mode: `api` or `pipeline`
- execution profile: `cpu` or `cuda`
- config template
- source preset
- detector and tracker inventory for startup-time configuration

Useful non-interactive examples:

```bash
hearthlight start --mode api --template active --profile cpu
hearthlight start --mode pipeline --template master_config --profile cuda --cuda-visible-devices 0
hearthlight start --template example --source-preset master_config --profile cpu
hearthlight start --interactive --dry-run
```

## 5. Configure the runtime in the frontend

Once the API and UI are up:

- open `http://localhost:3000`
- go to `Settings`
- save input sources
- save default model bindings
- save anomaly prompt settings
- define triggered alerts if needed
- review the launch-plan panel for the host-side startup command

Then go to the Run page and start the system after admission is healthy.

Alert-rule options are prepared by the backend:

- detector class choices come from the effective detector model for that source
- anomaly object and anomaly activity choices come only from the saved anomaly prompt settings

## 6. Understand the split between startup and run control

Repository initialization happens on the host:

- Docker stack startup
- CPU vs CUDA selection
- template and source-preset selection
- model inventory inspection through `hearthlight list-models`

Runtime initialization happens through the control plane:

- persisted source queue
- default per-stage model bindings
- saved anomaly prompt settings
- per-source alert rules
- admission checks
- `/start` and `/stop`

The effective runtime model set is always resolved as:

- source override first
- saved default binding second

## 7. Common startup failure classes

- `missing tracker registration builtin_bytetrack`
  - runtime now falls back to the legacy `bytetrack` name if the registration is missing
- `gpu is required but unavailable`
  - use `--profile cpu`, switch to CPU-safe model bindings, or start only in `api` mode
- missing uploads or dead camera URLs
  - fix the source rows in Settings or Run before retrying `/start`
- detector alert options unavailable
  - save a detector model that exposes class metadata for the source first
- anomaly alert options unavailable
  - save valid anomaly prompt settings before defining alert rules
