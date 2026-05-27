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
- `shared/plugins`: restart-loaded plugin manifests and bundled plugin component payloads

## Frontend and API

- `frontend/src/components/ControlPage.js`: run control and live resource status
- `frontend/src/components/SettingsPage.js`: source settings, default model bindings, anomaly prompts, alert rules, and launch-plan helper
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
   - chooses CPU vs CUDA, config template, and source preset for one full-system startup path

2. Runtime / run startup
   - handled by the web API and dashboard
   - saves sources, model bindings, anomaly prompts, and alert rules
   - publishes `/start` only after admission checks pass

The browser UI does not directly start Docker. It prepares sources, model defaults, anomaly
prompt settings, alert rules, and an operator launch plan. The actual container launch still
happens from the host shell.

The effective runtime model set is resolved per source:

- source-specific override first
- saved default binding second

## Config sources

The system now uses multiple config sources together:

- `shared/configs/config.yaml`: active runtime config used by the workers
- `shared/configs/saved_configs/*.yaml`: reusable template and camera-preset files
- `shared/plugins/*/plugin.yaml`: plugin bundle manifests loaded on server restart
- plugin-referenced YAML payloads: model registrations, trigger zoo entries, connector zoo entries, and rule-set templates
- optional integration plugins such as `shared/plugins/govee_light_connection/` can contribute zoo entries without becoming part of the core built-in plugin bundle
- `shared/configs/model_bindings.yaml`: default stage bindings for the active plugin-backed model catalog
- Postgres `control` schema: persisted input sources, uploads, alert rules, and control-plane state

## The Three Zoos

At the repository level, Hearthlight organizes operator-selectable capabilities into three plugin-backed
catalogs:

1. Model Zoo
   - source: plugin-provided model registrations plus mounted-model state
   - used by: `GET /model-options`, `GET/PUT /model-bindings`, source settings, model inventory, and model library views

2. Trigger Zoo
   - source: plugin-provided trigger catalog entries
   - used by: rules preparation, trigger-type display, and future trigger-family expansion

3. Connector Zoo
   - source: plugin-provided connector catalog entries
   - used by: connectors setup, connector install/pull flows, and generic connector endpoint persistence

The intended separation is:

- models decide how frames are processed
- triggers decide what kinds of runtime events can become rules
- connectors decide which downstream systems can receive actions

This split is important for plugin design. A plugin can contribute to one zoo without needing to
touch the others. For example, `shared/plugins/govee_light_connection/` contributes only a
Connector Zoo entry, while core detector and anomaly plugins primarily contribute to the Model Zoo.

Alert-rule option catalogs intentionally come from the backend instead of the browser:

- detector choices are derived from the effective detector binding and model metadata
- anomaly object and anomaly activity choices are derived from the saved anomaly prompt payload

## Control-plane endpoints

The main operator-facing API surface for model selection and alert definition is:

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

These endpoints expose readable display names for operators while preserving stable model keys for
storage and automation.

## Compatibility notes

- Old configs may still use `tracking.tracker` or `tracking.track_method`
- The launcher writes both fields for compatibility
- Registry-backed tracker selection is the long-term path, but the runtime still has legacy
  tracker-name fallback handling for built-in trackers such as `bytetrack`
