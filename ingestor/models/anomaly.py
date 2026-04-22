import asyncio
import json
import logging
from collections import defaultdict, deque
import numpy as np

from ...shared.model_zoo.anomaly_detectors import AnomalyDetector, VLLMAgent
from ...shared.constants import (
    ANOMALY_ADDITIONAL_CONFIG
)

logger = logging.getLogger(__name__)

class AnomalyDescriber:
    def __init__(self, cfg):
        self.anomaly_detector = AnomalyDetector(cfg.anomaly)
        self.vllm_agent = VLLMAgent(cfg.vllm)
        self.vllm_extra_body = ANOMALY_ADDITIONAL_CONFIG.get("extra_body", {})
        self.vllm_extra_messages = ANOMALY_ADDITIONAL_CONFIG.get("extra_messages", [])

    def __call__(self, frames):
        scene_summary = None
        anomaly_detected = False
        anomaly_category = ""
        score, anomaly = self.anomaly_detector(frames)
        print(f"Anomaly score: {score}, detected: {anomaly}")
        if anomaly:
            result = asyncio.run(self.vllm_agent(frames,
                                                extra_messages=self.vllm_extra_messages,
                                                extra_body=self.vllm_extra_body))
            result = json.loads(result)
            scene_summary = result.get("scene_summary", None)
            score = result.get("confidence", None)
            anomaly_detected = (score is not None and score > 0.5)
            print(result)
            if anomaly_detected:
               anomaly_category = result.get("anomaly_category", "")
        return anomaly_detected, score, scene_summary, anomaly_category
