from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec

from ..shared.models.DataModels import AnomalyEvent, AssetReference
# from ..shared.model_zoo.anomaly_detectors import AnomalyDetector

@dataclass
class AdapterState:
    last_activity_at: float | None = None
    last_empty_at: float | None = None
    last_event_at: float | None = None

# class FlashbackAdapter:
#     def __init__(self, registration: dict):
#         cfg = registration.get("config")
#         self.model = AnomalyDetector(cfg)

#     def evaluate(self, frames, **kwargs):
#         return self.model(frames)

class HeuristicPresenceAdapter:
    def __init__(self, registration: dict):
        runtime = registration.get("runtime") or {}
        self.quiet_period_seconds = float(runtime.get("quiet_period_seconds", 30.0))
        self.min_track_count = int(runtime.get("min_track_count", 1))
        self.cooldown_seconds = float(runtime.get("cooldown_seconds", 60.0))
        self.state_by_source: dict[int | None, AdapterState] = defaultdict(AdapterState)

    def evaluate(
        self,
        *,
        model_key: str,
        source_id: int | None,
        frame_id: int,
        timestamp: float,
        person_tracks: list,
        bag_tracks: list,
        frame_save_path: str | None = None,
        run_id: str | None = None,
    ) -> list[AnomalyEvent]:
        track_count = len(person_tracks) + len(bag_tracks)
        state = self.state_by_source[source_id]
        if track_count <= 0:
            state.last_empty_at = timestamp
            return []

        resumed_after_quiet = (
            state.last_empty_at is not None
            and timestamp - state.last_empty_at >= self.quiet_period_seconds
        )
        sustained_activity = (
            state.last_event_at is not None
            and timestamp - state.last_event_at >= self.cooldown_seconds
        )
        first_activity = state.last_activity_at is None

        state.last_activity_at = timestamp
        state.last_empty_at = None

        if track_count < self.min_track_count:
            return []
        if not (first_activity or resumed_after_quiet or sustained_activity):
            return []

        state.last_event_at = timestamp
        category = "presence_resume" if resumed_after_quiet or first_activity else "sustained_activity"
        visible_items = []
        if person_tracks:
            visible_items.append("person")
        if bag_tracks:
            visible_items.append("bag")
        visible_activities = [category.replace("_", " ")]
        score = min(1.0, track_count / max(float(self.min_track_count), 1.0))
        asset_references = []
        if frame_save_path:
            asset_references.append(
                AssetReference(
                    uri=frame_save_path,
                    media_type="image/jpeg",
                    producer="ANOMALY",
                )
            )
        return [
            AnomalyEvent(
                event_id=f"{model_key}:{source_id}:{frame_id}:{category}",
                run_id=run_id,
                source_id=source_id,
                frame_id=frame_id,
                model_key=model_key,
                category=category,
                score=score,
                reasoning=f"Observed {track_count} tracked objects after inactivity window.",
                visible_items=visible_items,
                visible_activities=visible_activities,
                asset_references=asset_references,
            )
        ]


class VLMAnomalyDemoAdapter:
    def __init__(self, registration: dict):
        runtime = registration.get("runtime") or {}
        package_name = runtime.get("package", "vlm_anomaly_demo")
        if find_spec(package_name) is None:
            raise RuntimeError(f"anomaly package {package_name} is unavailable")
        self.module = import_module(package_name)

    def evaluate(self, **kwargs) -> list[AnomalyEvent]:
        return []


ADAPTERS = {
    "heuristic_presence": HeuristicPresenceAdapter,
    "vlm_anomaly_demo": VLMAnomalyDemoAdapter,
    # "flashback": FlashbackAdapter,
}


def build_adapter(registration: dict):
    adapter_name = registration.get("adapter", "heuristic_presence")
    adapter_cls = ADAPTERS.get(adapter_name)
    if adapter_cls is None:
        raise ValueError(f"unknown anomaly adapter {adapter_name}")
    return adapter_cls(registration)
