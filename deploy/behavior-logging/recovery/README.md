# Recorder recovery

This folder stores static configuration and model references, not weights or videos.
`models.json` records the installed Hugging Face revisions, local checkpoint hashes,
upstream download URLs, Model Zoo commit, and source of the CUDA base image.

On a new computer, clone Hearthlight and the Delos repository next to one another.
Install Docker with the NVIDIA Container Toolkit and an appropriate NVIDIA driver.
Clone the private source dependencies using your authorized GitHub credentials:

```sh
git clone https://github.com/lauretta-io/hearthlight_model_zoo.git shared/model_zoo
git -C shared/model_zoo checkout 4bba4c57be76b18d40a54c8a2a45285d34f6eec2
git clone https://github.com/lauretta-io/dhs-passenger-detection.git ../dhs-base
git -C ../dhs-base checkout 9775a7fc8d29817d91f8546c09fab8e44a6153a5
docker build -t dhs-passenger-detection-ingestor:latest ../dhs-base/ingestor
mkdir -p var/behavior-logging/models var/behavior-logging/logs
cp deploy/behavior-logging/recovery/cameras.example.json var/behavior-logging/cameras.json
cp deploy/behavior-logging/recovery/delos-source.example.json var/behavior-logging/logs/delos-source.json
```

Restore the camera credentials locally, correct host-specific paths, and use the same
camera/tenant/source IDs as Delos. The source database/gallery paths inside Delos
must resolve beneath `/var/lib/delos/person-history`. Keep the local camera file
private (`chmod 600`). Configure camera credentials through Delos Settings when
using the runtime API. The example URLs have credentials and query strings removed.

Create a fresh shared runtime token without committing it:

```sh
umask 077
openssl rand -hex 32 > var/behavior-logging/logs/behavior-runtime.token
docker compose -f deploy/behavior-logging/compose.yaml build logger
docker compose -f deploy/behavior-logging/compose.yaml run --rm --entrypoint python \
  -v "$PWD/deploy/behavior-logging/recovery:/recovery:ro" logger /recovery/pull-models.py
docker compose -f deploy/behavior-logging/compose.yaml run --rm logger --smoke-test
docker compose -f deploy/behavior-logging/compose.yaml up -d
```

Start Delos with its `person-history.yml` overlay pointing at this host's logs
folder. Both the API and recorder must see the same runtime token file. Restore
static Delos configuration using `delos/deploy/recovery/static-config.json` as the
reference; it includes prompts, camera zones and rules. Review logs and health,
then verify a new camera sample and person observation in the UI.

For identity continuity, restore the private SQLite history/gallery backups and
Delos PostgreSQL backup before starting writers. Without these runtime backups,
static recovery starts a fresh history and does not recreate prior identities.
The model cache is reproducible; weights are not trained from this repository.
Remote model availability/access and old dependency packages are external
requirements. A checkpoint hash mismatch must be investigated, never ignored.

## Continuous exit tracker

The Compose deployment has two services: `logger` performs sampled VLM behavior
analysis; `exit-tracker` performs independent continuous exit tracking using the
shared camera configuration, model cache and history directory. Start both with
`docker compose -f deploy/behavior-logging/compose.yaml up -d`. Check them with
`docker compose -f deploy/behavior-logging/compose.yaml ps` and inspect errors with
`docker compose -f deploy/behavior-logging/compose.yaml logs --tail 100 logger exit-tracker`.
The runtime API must be reachable on the configured host/port, and the shared token
and camera credentials must be valid before either service can ingest cameras.
