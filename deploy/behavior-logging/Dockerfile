# Reuse the installed CUDA/PyTorch runtime without changing the existing DHS services.
FROM dhs-passenger-detection-ingestor
USER root
RUN python -m pip install --no-cache-dir num2words==0.5.14 yacs==0.1.8 \
    && python -m pip install --no-cache-dir --no-deps \
        --index-url https://download.pytorch.org/whl/cu126 torchvision==0.22.0+cu126
# Match the dependency versions used for the evaluated Qwen3-VL checkpoint.
RUN python -m pip install --no-cache-dir transformers==5.7.0 accelerate==1.15.0 \
    huggingface-hub==1.33.0 tokenizers==0.22.2
RUN git init /opt/transreid \
    && git -C /opt/transreid fetch --depth=1 https://github.com/damo-cv/TransReID.git dec55046fcdfadee14e2c28e2df89305d8f7557a \
    && git -C /opt/transreid checkout --detach FETCH_HEAD \
    && sed -i "s/from torch._six import container_abcs/import collections.abc as container_abcs/" /opt/transreid/model/backbones/vit_pytorch.py \
    && rm -rf /opt/transreid/.git
ENV PYTHONPATH=/opt/model-zoo/src \
    HF_HOME=/models/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_XET=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    TOKENIZERS_PARALLELISM=false \
    PYTHONUNBUFFERED=1
COPY shared/model_zoo/src/hearthlight_model_zoo /opt/model-zoo/src/hearthlight_model_zoo
COPY deploy/behavior-logging/tracking.py deploy/behavior-logging/person_reid.py deploy/behavior-logging/rerank.py deploy/behavior-logging/activity.py deploy/behavior-logging/scene.py deploy/behavior-logging/history.py /opt/behavior/
COPY deploy/behavior-logging/runner.py deploy/behavior-logging/exit_tracker.py deploy/behavior-logging/compact_context.py /opt/behavior/
COPY deploy/behavior-logging/moments.py /opt/behavior/moments.py
COPY deploy/behavior-logging/zone_crossings.py /opt/behavior/zone_crossings.py
COPY deploy/behavior-logging/zone_explanations.py /opt/behavior/zone_explanations.py
COPY deploy/behavior-logging/interaction_format.py /opt/behavior/interaction_format.py
COPY deploy/behavior-logging/change_reports.py /opt/behavior/change_reports.py
COPY deploy/behavior-logging/interaction_areas.py /opt/behavior/interaction_areas.py
COPY deploy/behavior-logging/object_focus.py deploy/behavior-logging/review_objects.py deploy/behavior-logging/object_semantics.py /opt/behavior/
COPY deploy/behavior-logging/interactions.py /opt/behavior/interactions.py
COPY deploy/behavior-logging/snapshots.py /opt/behavior/snapshots.py
COPY deploy/behavior-logging/clips.py /opt/behavior/clips.py
COPY deploy/behavior-logging/exit_observations.py /opt/behavior/exit_observations.py
COPY deploy/behavior-logging/reid_validation.py /opt/behavior/reid_validation.py
COPY deploy/behavior-logging/feature_bank.py /opt/behavior/feature_bank.py
COPY deploy/behavior-logging/runtime_configuration.py /opt/behavior/runtime_configuration.py
USER 1000:1000
ENTRYPOINT ["python", "/opt/behavior/runner.py"]
CMD ["--config", "/config/cameras.json"]
