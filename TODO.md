# Hearthlight Roadmap

This file tracks active and upcoming work across backend, pipeline, and frontend.

## Recently Completed

- [x] Added source admission checks before `/start` and surfaced failures in control-plane status.
- [x] Added upload lifecycle handling for staged, attached, active, and deleted media.
- [x] Improved stop/reset reliability with worker-thread and dependency status visibility.
- [x] Added mixed-source settings and monitoring controls in the UI.
- [x] Added model registry and model-binding configuration to the control plane.
- [x] Added editable anomaly prompt settings in the frontend.
- [x] Added uploaded-video support to the Live page preview pipeline.
- [x] Standardized branding asset references to `hearthlight.png` and switched favicon usage.

## High Priority

### Source And Runtime Reliability

- [ ] Add explicit health diagnostics for preview streams (`/sources/{id}/preview.mjpeg`) so UI can show root-cause failures per source.
- [ ] Add smoke tests for camera URL, webcam, and uploaded-video combinations in one run.
- [ ] Add restart/resume behavior for long uploaded videos across module restarts.

### Anomaly Pipeline

- [ ] Add stage-level telemetry for anomaly stage 1 and stage 2 model latency.
- [ ] Add validation to ensure selected stage 1/stage 2 models are compatible with source/task constraints.
- [ ] Add versioned prompt presets so teams can roll back prompt changes safely.

### Testing Framework

- [ ] Define an automated accuracy test set and baseline metrics for detector/tracker/ReID/anomaly outputs.
- [ ] Add crash/fault-injection tests for RabbitMQ and DB interruptions.
- [ ] Add CI coverage for control-plane API contracts and source upload flows.

## Product And UX Backlog

### Frontend

- [ ] Refactor large pages (`Control`, `POI`) into smaller route-scoped components.
- [ ] Improve styling consistency and reduce duplicated UI state logic.
- [ ] Fix incident/entity ID presentation and linking inconsistencies.
- [ ] Add zone creation and editing workflow for camera management.
- [ ] Evolve run startup UX to include source set + threshold presets.

### Incident And Annotation Experience

- [ ] Move annotation review fully into the web UI.
- [ ] Add item highlighting overlays for incident video playback.
- [ ] Add better person-guess/explanation rendering for operator workflows.

### POI Data Model

- [ ] Finalize retention policy for POI search results stored in DB.
- [ ] Define durable linkage between internal POI results and POI search records.

## Documentation Follow-Ups

- [ ] Add a frontend branding section documenting favicon and logo asset locations.
- [ ] Add a short "runbook by failure mode" section for common startup and preview issues.
