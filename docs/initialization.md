# Initialization Guide

This guide covers the full initialization routine from a fresh checkout to a running UI.

## 1. Prepare local prerequisites

- Docker Engine with Compose support
- `.env` at the repository root
- `shared/configs/config.yaml`
- NVIDIA container support only if you plan to run `--profile cuda`

Optional:

- `foia.env` if you intend to use the FOIA profile
- X11 display access if `show_vid` is enabled and you run on Linux

## 2. Bootstrap config

If there is no active runtime config yet:

```bash
cp shared/configs/example_config.yaml shared/configs/config.yaml
```

Then review:

- detector and feature-extractor defaults
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
python3 -m hearthlight start --interactive
```

The launcher can choose:

- service mode: `api` or `pipeline`
- execution profile: `cpu` or `cuda`
- config template
- source preset
- detector, tracker, pose, and feature-extractor selections

Useful non-interactive examples:

```bash
python3 -m hearthlight start --mode api --template active --profile cpu
python3 -m hearthlight start --mode pipeline --template master_config --profile cuda --cuda-visible-devices 0
python3 -m hearthlight start --template example --source-preset master_config --profile cpu
python3 -m hearthlight start --interactive --dry-run
```

## 5. Configure the runtime in the frontend

Once the API and UI are up:

- open `http://localhost:3000`
- go to `Settings`
- save input sources
- save default model bindings
- review the launch-plan panel for the host-side startup command

Then go to the Run page and start the system after admission is healthy.

## 6. Understand the split between startup and run control

Repository initialization happens on the host:

- Docker stack startup
- CPU vs CUDA selection
- template and source-preset selection

Runtime initialization happens through the control plane:

- persisted source queue
- default per-stage model bindings
- admission checks
- `/start` and `/stop`

## 7. Common startup failure classes

- `tracker model builtin_cmtrack is incompatible with source kind/tasks`
  - fixed by stage-scoped task validation; unrelated source tasks should no longer block tracker
- `missing tracker registration builtin_cmtrack`
  - runtime now falls back to the legacy `cmtrack` name if the registration is missing
- `gpu is required but unavailable`
  - use `--profile cpu`, switch to CPU-safe model bindings, or start only in `api` mode
- missing uploads or dead camera URLs
  - fix the source rows in Settings or Run before retrying `/start`
