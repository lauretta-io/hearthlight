# Changelog

## 0.8.2 - 2026-05-31

- added system-aware Docker image-lane preparation through `hearthlight prepare-images`, with explicit `cpu`, `cuda`, and `mlx` variants
- updated the compose stack and Docker publish flow to use variant-tagged local and published images such as `hearthlight-webapp:mlx` and `<tag>-cuda`
- introduced `hybrid-local-mlx` as the Apple Silicon host-worker runtime and documented MLX as a hybrid control-plane plus host-worker deployment path
- fixed Apple Silicon detection for translated macOS Python environments so MLX-capable hosts no longer fall back incorrectly to the CPU worker lane
- aligned release metadata, plugin manifests, connector-zoo catalog metadata, and frontend package metadata to `0.8.2`
- added secure Stage 2 provider settings for OpenAI, LM Studio, Lauretta, and Claude-compatible adapters, including encrypted credential storage, masked secret persistence, and UI-managed connection testing
- updated the Stage 2 anomaly adapters to resolve provider runtime settings from the control plane before falling back to env/default registry values
- added browser-driven Playwright coverage and backend/unit coverage for Stage 2 provider settings, secret-rotation flows, and provider connectivity failures
- fixed PromptCatalog default path resolution so anomaly behavior lists load correctly in packaged/runtime environments

## 0.8.1 - 2026-05-31

- finalized the operator workflow refresh across Monitoring, Rules, Incidents, and Model Logs, including compact rule editors, read-only saved rules with explicit edit mode, richer trigger detail media, and a more stable always-warm UI refresh model
- expanded connector and trigger delivery behavior so rules can target saved connector endpoints directly, trigger detail pages can show connector delivery outcomes, and the Connector Zoo defaults to the GitHub-backed catalog path
- hardened anomaly and detector alert handling so detector and anomaly incidents produce clearer titles, model logs persist non-alerting model returns, and alert persistence/filtering works correctly across restarts
- improved local-runtime operation with hybrid-local-cpu startup fixes, direct local worker health integration, smoother live preview behavior, and source-processing controls that better separate uploaded video from webcam and CCTV handling
- tightened runtime robustness with bounded queue helpers, file-retention controls, shared frontend polling and SSE coordination, server-side cached operations events, and soak-test harnesses for long-run resource validation
- repaired several container/runtime packaging issues, including RabbitMQ init behavior, Docker dependency conflicts, and the removal of `reid` from the active Docker stack definition

## 0.8.0 - 2026-05-15

- bumped the project version to `0.8.0` across the Python package, frontend package metadata, macOS bundle metadata, and FastAPI OpenAPI metadata
- added published-image support for the compose/CLI stack via `HEARTHLIGHT_*_IMAGE` env vars and a Docker publish helper script
- widened the default YOLOX detector surface to COCO-trained classes and added extra YOLOX size options in the model zoo
- migrated the frontend from `react-scripts` to Vite and rebuilt the frontend package lockfile
- simplified source configuration defaults:
  - blank labels now resolve to `Camera N` for standard camera sources
  - webcam sources default to `Webcam N`
  - uploaded videos default to the uploaded filename without its extension
- hid source-level detector, tracker, and anomaly override selectors whenever `Enable Video AI` is turned off while preserving the saved disabled state
- renamed the source save action to `Update Source Settings` and added a visible loading spinner while source settings save
- expanded local anomaly registry compatibility so `siglip_stage_1_*` and `smolvlm_stage_2_*` defaults resolve even when the external model-zoo catalog is unavailable
- simplified the Connectors page into a single-column connector list with configured-state badges
- added per-camera frame skipping with `Process every Nth frame`
- moved anomaly `1-10` trigger cutoffs out of Stage 2 prompt config and into anomaly detection rules
- split Rules into separate detection and anomaly sections with multi-camera targeting
- added processing-rate guidance in the model library and recent measured cadence in Model Logs
- added third-party Stage 2 anomaly model entries for Chatgpt, Claude, LM Studio, and Lauretta-hosted OpenAI-compatible APIs, with env-based availability checks and provider model-name overrides
- moved theme selection into `Settings > Appearance` and persisted it as a workspace-wide backend setting with cached startup restore
- unified models, triggers, connectors, and rule-set templates under a restart-loaded plugin manifest system backed by persisted plugin bundle/component catalogs
- added `Govee Light Connection` as a non-core connector plugin that can be pulled from the Connector Zoo without becoming part of the default built-in connector set
- added Govee connector setup helpers for API-key validation, light-device discovery, optional state inspection, and trigger-driven light control
- removed stale frontend pages and assets from the retired Control, Entity, and POI flows
- cleaned up duplicate backup files such as `README (1).md` and `.gitignore (1)`
- documented the validated detector class surface and clarified that live detector trigger IDs remain normalized to `PERSON` and `BAG`

## Earlier History

- changes before `0.8.0` were made directly in the repository without a maintained release changelog
