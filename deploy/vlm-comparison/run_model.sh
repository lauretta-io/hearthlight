#!/usr/bin/env bash
set -euo pipefail
benchmark_model="$1"
shift
benchmark_root=/home/lauretta/hearthlight
benchmark_work="$benchmark_root/var/vlm-comparison"
exec 9>"$benchmark_work/gpu-test.lock"
flock -x 9
logger_running=$(docker inspect --format '{{.State.Running}}' hearthlight-behavior-logger-1)
restore_logger() {
  if [ "$logger_running" = true ]; then
    docker start hearthlight-behavior-logger-1 >/dev/null
  fi
}
trap restore_logger EXIT
if [ "$logger_running" = true ]; then
  docker stop -t 60 hearthlight-behavior-logger-1 >/dev/null
fi
docker run --rm --gpus '"device=0"' --name hearthlight-vlm-benchmark \
  --entrypoint /bench/env/bin/python --shm-size=1g \
  -e HF_HOME=/bench/models/huggingface -e HF_HUB_DISABLE_TELEMETRY=1 \
  -e TOKENIZERS_PARALLELISM=false \
  -v "$benchmark_work:/bench" \
  -v "$benchmark_root/var/behavior-logging/models:/oldmodels:ro" \
  -v "$benchmark_root/deploy/vlm-comparison:/code:ro" \
  hearthlight-behavior:model-zoo /code/benchmark.py --model "$benchmark_model" "$@"
