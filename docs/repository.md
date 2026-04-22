# Repository Guide

This repository is split into runtime services, shared contracts, operator tooling, and the
frontend/web control plane.

## Runtime services

- `ingestor`: opens video sources, runs detection, builds tracker inputs, and forwards data
- `reid`: assigns persistent IDs to people and bags
- `association`: builds incidents and ownership relationships
- `anomaly`: optional post-detection anomaly worker
- `webapp`: FastAPI backend and React dashboard delivery

## Shared code

- `shared/models`: SQLAlchemy and API data contracts
- `shared/utils`: runtime helpers, security utilities, model registry, launcher support
- `shared/configs`: runtime config, model registry files, binding defaults, saved templates

## Frontend and API

- `frontend/src/components/ControlPage.js`: run control and live resource status
- `frontend/src/components/SettingsPage.js`: source settings, default model bindings, launch-plan helper
- `frontend/src/components/MonitoringPage.js`: monitoring and model health
- `webapp/routes/external_routes.py`: main control-plane API

## Branding assets

- Documentation logo: `docs/assets/hearthlight.png`
- Dashboard favicon/app icon source: `frontend/public/hearthlight.png`
- Product roadmap: `TODO.md`

## Startup layers

There are two different startup layers on purpose:

1. Repository / container startup
   - handled by `python3 -m hearthlight`, `run/launcher.py`, `docker-compose.yaml`, and `run/docker-compose.cuda.yaml`
   - chooses API vs pipeline mode, CPU vs CUDA, config template, and source preset

2. Runtime / run startup
   - handled by the web API and dashboard
   - saves sources and model bindings
   - publishes `/start` only after admission checks pass

The browser UI does not directly start Docker. It prepares sources, model defaults, and an
operator launch plan. The actual container launch still happens from the host shell.

## Config sources

The system now uses multiple config sources together:

- `shared/configs/config.yaml`: active runtime config used by the workers
- `shared/configs/saved_configs/*.yaml`: reusable template and camera-preset files
- `shared/configs/registries/*.yaml`: model registrations
- `shared/configs/model_bindings.yaml`: default registry-backed stage bindings
- Postgres `control` schema: persisted input sources, uploads, and control-plane state

## Compatibility notes

- Old configs may still use `tracking.tracker` or `tracking.track_method`
- The launcher writes both fields for compatibility
- Registry-backed tracker selection is the long-term path, but the runtime still has legacy
  tracker-name fallback handling for built-in trackers such as `cmtrack`
