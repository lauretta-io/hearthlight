from hearthlight_model_zoo.anomaly_detectors import (
    AnomalyDescriber as _BaseAnomalyDescriber,
    AnomalyDetector,
    VLLMAgent,
)

from ...shared.constants import ANOMALY_ADDITIONAL_CONFIG


class AnomalyDescriber(_BaseAnomalyDescriber):
    def __init__(self, cfg):
        super().__init__(
            cfg,
            extra_messages=ANOMALY_ADDITIONAL_CONFIG.get("extra_messages", []),
            extra_body=ANOMALY_ADDITIONAL_CONFIG.get("extra_body", {}),
        )
