#!/usr/bin/env bash
set -euo pipefail
root=/home/lauretta/hearthlight
exec 9>"$root/var/vlm-comparison/gpu-test.lock"
flock -x 9
running=$(docker inspect --format '{{.State.Running}}' hearthlight-behavior-logger-1)
restore() { if [ "$running" = true ]; then docker start hearthlight-behavior-logger-1 >/dev/null; fi; }
trap restore EXIT
if [ "$running" = true ]; then docker stop -t 60 hearthlight-behavior-logger-1 >/dev/null; fi
# Every result is isolated from the live history and ReID databases.
docker run --rm --gpus '"device=0"' --name hearthlight-qwen4b-8f --entrypoint python --shm-size=1g \
 -e HF_HUB_DISABLE_PROGRESS_BARS=1 -e TOKENIZERS_PARALLELISM=false \
 -v "$root/var/vlm-comparison:/bench:ro" -v "$root/var/behavior-logging/models:/oldmodels:ro" \
 -v "$root/var/qwen4b-8f-10s-20261112:/probe" \
 -v "$root/deploy/vlm-comparison:/code:ro" -v "$root/deploy/behavior-logging:/behavior:ro" \
 hearthlight-behavior:model-zoo /code/qwen4b_8f.py
