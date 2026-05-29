# Changelog

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
