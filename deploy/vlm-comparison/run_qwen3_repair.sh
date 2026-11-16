#!/usr/bin/env bash
set -euo pipefail
root=/home/lauretta/hearthlight
exec 9>"$root/var/vlm-comparison/gpu-test.lock"
flock -x 9
running=$(docker inspect --format '{{.State.Running}}' hearthlight-behavior-logger-1)
restore() { if [ "$running" = true ]; then docker start hearthlight-behavior-logger-1 >/dev/null; fi; }
trap restore EXIT
if [ "$running" = true ]; then docker stop -t 60 hearthlight-behavior-logger-1 >/dev/null; fi
for model in qwen3-vl-2b qwen3-vl-4b; do
 docker run --rm --gpus '"device=0"' --name hearthlight-qwen3-repair --entrypoint python --shm-size=1g \
  -e HF_HUB_DISABLE_PROGRESS_BARS=1 -e TOKENIZERS_PARALLELISM=false \
  -v "$root/var/vlm-comparison:/bench:ro" -v "$root/var/behavior-logging/models:/oldmodels:ro" \
  -v "$root/var/qwen3-evaluation-20261112:/evaluation" -v "$root/deploy/vlm-comparison:/code:ro" \
  hearthlight-behavior:model-zoo /code/repair_qwen3_temporal.py --model "$model"
done
