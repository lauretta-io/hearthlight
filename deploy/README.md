# Deployment Seeds

This directory contains deployment bootstrap assets for the current control plane.

Contents:

- `seeds/runtime.env.seed`: baseline environment values for Postgres, RabbitMQ, API ports,
  resource thresholds, and resource-drift thresholds.
- `seeds/control_plane/model_bindings.seed.yaml`: default model bindings to copy into
  `shared/configs/model_bindings.yaml` during bootstrap.
- `seeds/control_plane/input_sources.seed.json`: disabled starter source rows for the control
  schema.
- `init/bootstrap_deployment.sh`: copies missing seed files into place and can trigger DB seeding.
- `init/seed_control_plane.py`: writes model bindings and input sources into the local deployment.
  It can seed through direct DB access when SQLAlchemy is installed locally, or through the API
  when `--base-url` is supplied.
- `init/run_deployment.sh`: one-command bootstrap + preflight + stack startup + control-plane seeding.

Typical usage from the repo root:

```bash
deploy/init/run_deployment.sh
```

Force the full worker stack explicitly:

```bash
deploy/init/run_deployment.sh pipeline
```
