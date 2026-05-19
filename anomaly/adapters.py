from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib import error, request

from omegaconf import OmegaConf

try:
    from ..shared.models.DataModels import AnomalyEvent, AssetReference
except ImportError:  # pragma: no cover - standalone module import fallback
    from shared.models.DataModels import AnomalyEvent, AssetReference

logger = logging.getLogger(__name__)


@dataclass
class AdapterState:
    last_activity_at: float | None = None
    last_empty_at: float | None = None
    last_event_at: float | None = None


@dataclass
class StageOneCandidate:
    event_id: str
    run_id: str | None
    source_id: int | None
    camera_id: int
    frame_id: int
    stage_1_model_key: str
    stage_2_model_key: str
    category: str
    score: float
    reasoning: str | None
    visible_items: list[str]
    visible_activities: list[str]
    asset_references: list[AssetReference]


@dataclass
class PromptBundle:
    template: str
    anomaly_object_list: list[str]
    anomaly_activity_list: list[str]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = OmegaConf.load(path)
    if raw is None:
        return {}
    return OmegaConf.to_container(raw, resolve=True)  # type: ignore[return-value]


class PromptCatalog:
    def __init__(self, prompt_yaml_path: str, anomaly_list_yaml_path: str):
        self.prompt_yaml_path = Path(prompt_yaml_path).expanduser().resolve()
        self.anomaly_list_yaml_path = Path(anomaly_list_yaml_path).expanduser().resolve()
        self._cache: PromptBundle | None = None
        self._cache_signature: tuple[float | None, float | None] | None = None

    def load(self) -> PromptBundle:
        prompt_mtime = (
            self.prompt_yaml_path.stat().st_mtime if self.prompt_yaml_path.exists() else None
        )
        anomaly_mtime = (
            self.anomaly_list_yaml_path.stat().st_mtime
            if self.anomaly_list_yaml_path.exists()
            else None
        )
        signature = (prompt_mtime, anomaly_mtime)
        if self._cache is not None and self._cache_signature == signature:
            return self._cache

        prompt_cfg = _load_yaml(self.prompt_yaml_path)
        anomaly_cfg = _load_yaml(self.anomaly_list_yaml_path)
        template = str(prompt_cfg.get("template") or "").strip()
        object_list = [
            str(item).strip()
            for item in list(anomaly_cfg.get("anomaly_object_list") or [])
            if str(item).strip()
        ]
        activity_list = [
            str(item).strip()
            for item in list(anomaly_cfg.get("anomaly_activity_list") or [])
            if str(item).strip()
        ]
        self._cache = PromptBundle(
            template=template,
            anomaly_object_list=object_list,
            anomaly_activity_list=activity_list,
        )
        self._cache_signature = signature
        return self._cache


class HeuristicPresenceStageOneAdapter:
    def __init__(self, registration: dict):
        runtime = registration.get("runtime") or {}
        self.quiet_period_seconds = float(runtime.get("quiet_period_seconds", 30.0))
        self.min_track_count = int(runtime.get("min_track_count", 1))
        self.cooldown_seconds = float(runtime.get("cooldown_seconds", 60.0))
        self.state_by_source: dict[int | None, AdapterState] = defaultdict(AdapterState)

    def evaluate(
        self,
        *,
        stage_1_model_key: str,
        stage_2_model_key: str,
        source_id: int | None,
        camera_id: int,
        frame_id: int,
        timestamp: float,
        person_tracks: list,
        bag_tracks: list,
        frame_save_path: str | None = None,
        run_id: str | None = None,
    ) -> list[StageOneCandidate]:
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
        category = (
            "presence_resume" if resumed_after_quiet or first_activity else "sustained_activity"
        )
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
            StageOneCandidate(
                event_id=f"{stage_1_model_key}:{source_id}:{frame_id}:{category}",
                run_id=run_id,
                source_id=source_id,
                camera_id=camera_id,
                frame_id=frame_id,
                stage_1_model_key=stage_1_model_key,
                stage_2_model_key=stage_2_model_key,
                category=category,
                score=score,
                reasoning=f"Observed {track_count} tracked objects after inactivity window.",
                visible_items=visible_items,
                visible_activities=visible_activities,
                asset_references=asset_references,
            )
        ]


class SigLIPStageOneAdapter(HeuristicPresenceStageOneAdapter):
    def evaluate(self, **kwargs) -> list[StageOneCandidate]:
        candidates = super().evaluate(**kwargs)
        for candidate in candidates:
            candidate.reasoning = (
                "SigLIP stage-1 compatibility scorer flagged a candidate based on tracked people or bags."
            )
            if not candidate.category.startswith("siglip_"):
                candidate.category = f"siglip_{candidate.category}"
        return candidates


def _select_best_prompt_match(
    candidates: list[str],
    prompt_terms: list[str],
) -> str | None:
    if not candidates or not prompt_terms:
        return None
    lowered_terms = [term.lower() for term in prompt_terms]
    for candidate in candidates:
        lowered_candidate = candidate.lower()
        if lowered_candidate in lowered_terms:
            return candidate
        for term in prompt_terms:
            lowered_term = term.lower()
            if lowered_term in lowered_candidate or lowered_candidate in lowered_term:
                return term
    return None


class PromptRulesStageTwoAdapter:
    def __init__(self, registration: dict):
        runtime = registration.get("runtime") or {}
        self.default_category = str(runtime.get("default_category", "suspicious_activity"))

    def build_event(
        self,
        *,
        candidate: StageOneCandidate,
        prompts: PromptBundle,
    ) -> AnomalyEvent:
        matched_activity = _select_best_prompt_match(
            candidate.visible_activities,
            prompts.anomaly_activity_list,
        )
        matched_item = _select_best_prompt_match(
            candidate.visible_items,
            prompts.anomaly_object_list,
        )
        category = matched_activity or matched_item or candidate.category or self.default_category
        title_parts = [item for item in [matched_item, matched_activity] if item]
        title = f"Anomaly found: {'; '.join(title_parts)}" if title_parts else category
        prompt_hint = prompts.template.splitlines()[0].strip() if prompts.template else None
        reasoning_parts = [candidate.reasoning or "Potential anomaly candidate detected."]
        if prompt_hint:
            reasoning_parts.append(f"Prompt focus: {prompt_hint}")
        return AnomalyEvent(
            event_id=candidate.event_id,
            run_id=candidate.run_id,
            source_id=candidate.source_id,
            camera_id=candidate.camera_id,
            frame_id=candidate.frame_id,
            stage_1_model_key=candidate.stage_1_model_key,
            stage_2_model_key=candidate.stage_2_model_key,
            title=title,
            model_key=candidate.stage_2_model_key,
            category=category,
            score=candidate.score,
            reasoning=" ".join(reasoning_parts),
            visible_items=candidate.visible_items,
            visible_activities=candidate.visible_activities,
            asset_references=candidate.asset_references,
        )


class SmolVLMStageTwoAdapter(PromptRulesStageTwoAdapter):
    def build_event(
        self,
        *,
        candidate: StageOneCandidate,
        prompts: PromptBundle,
    ) -> AnomalyEvent:
        event = super().build_event(candidate=candidate, prompts=prompts)
        prompt_hint = prompts.template.splitlines()[0].strip() if prompts.template else None
        reasoning_parts = [event.reasoning or "SmolVLM stage-2 compatibility adapter evaluated this candidate."]
        if prompt_hint:
            reasoning_parts.append(f"Prompt template: {prompt_hint}")
        event.reasoning = " ".join(reasoning_parts)
        return event


class PassThroughStageTwoAdapter:
    def __init__(self, _registration: dict):
        pass

    def build_event(
        self,
        *,
        candidate: StageOneCandidate,
        prompts: PromptBundle,
    ) -> AnomalyEvent:
        del prompts
        return AnomalyEvent(
            event_id=candidate.event_id,
            run_id=candidate.run_id,
            source_id=candidate.source_id,
            camera_id=candidate.camera_id,
            frame_id=candidate.frame_id,
            stage_1_model_key=candidate.stage_1_model_key,
            stage_2_model_key=candidate.stage_2_model_key,
            title=candidate.category,
            model_key=candidate.stage_2_model_key,
            category=candidate.category,
            score=candidate.score,
            reasoning=candidate.reasoning,
            visible_items=candidate.visible_items,
            visible_activities=candidate.visible_activities,
            asset_references=candidate.asset_references,
        )


class VLMAnomalyDemoStageTwoAdapter(PassThroughStageTwoAdapter):
    def __init__(self, registration: dict):
        runtime = registration.get("runtime") or {}
        package_name = runtime.get("package", "vlm_anomaly_demo")
        if find_spec(package_name) is None:
            raise RuntimeError(f"anomaly package {package_name} is unavailable")
        self.module = import_module(package_name)


class RemoteAPIMixin(PromptRulesStageTwoAdapter):
    def __init__(self, registration: dict):
        super().__init__(registration)
        self.registration = dict(registration or {})
        self.runtime = dict(self.registration.get("runtime") or {})
        self.timeout_seconds = float(self.runtime.get("timeout_seconds", 30.0))

    def _fallback_event(self, *, candidate: StageOneCandidate, prompts: PromptBundle, detail: str) -> AnomalyEvent:
        event = super().build_event(candidate=candidate, prompts=prompts)
        detail = detail.strip()
        if detail:
            base_reasoning = event.reasoning or "Remote anomaly API call failed."
            event.reasoning = f"{base_reasoning} Remote adapter detail: {detail}"
        return event

    def _build_request_payload(self, *, candidate: StageOneCandidate, prompts: PromptBundle) -> dict[str, Any]:
        return {
            "event_id": candidate.event_id,
            "camera_id": candidate.camera_id,
            "source_id": candidate.source_id,
            "frame_id": candidate.frame_id,
            "stage_1_score": candidate.score,
            "stage_1_category": candidate.category,
            "visible_items": list(candidate.visible_items),
            "visible_activities": list(candidate.visible_activities),
            "prompt_template": prompts.template,
            "anomaly_objects": list(prompts.anomaly_object_list),
            "anomaly_behaviors": list(prompts.anomaly_activity_list),
            "asset_references": [
                {
                    "uri": asset.uri,
                    "media_type": asset.media_type,
                    "producer": asset.producer,
                    "timestamp": asset.timestamp,
                }
                for asset in candidate.asset_references
            ],
        }

    def _normalize_score(self, raw_score: Any, fallback: float) -> float:
        try:
            numeric = float(raw_score)
        except (TypeError, ValueError):
            return fallback
        if numeric > 1.0:
            numeric = numeric / 10.0
        return max(0.0, min(1.0, numeric))

    def _normalize_event(
        self,
        *,
        candidate: StageOneCandidate,
        prompts: PromptBundle,
        payload: dict[str, Any],
    ) -> AnomalyEvent:
        fallback = super().build_event(candidate=candidate, prompts=prompts)
        title = str(payload.get("title") or fallback.title or candidate.category).strip() or candidate.category
        category = str(payload.get("category") or fallback.category or candidate.category).strip() or candidate.category
        reasoning = str(payload.get("reasoning") or fallback.reasoning or candidate.reasoning or "").strip() or None
        visible_items = [
            str(item).strip()
            for item in list(payload.get("visible_items") or fallback.visible_items or candidate.visible_items)
            if str(item).strip()
        ]
        visible_activities = [
            str(item).strip()
            for item in list(payload.get("visible_activities") or fallback.visible_activities or candidate.visible_activities)
            if str(item).strip()
        ]
        return AnomalyEvent(
            event_id=candidate.event_id,
            run_id=candidate.run_id,
            source_id=candidate.source_id,
            camera_id=candidate.camera_id,
            frame_id=candidate.frame_id,
            stage_1_model_key=candidate.stage_1_model_key,
            stage_2_model_key=candidate.stage_2_model_key,
            title=title,
            model_key=candidate.stage_2_model_key,
            category=category,
            score=self._normalize_score(payload.get("score"), candidate.score),
            reasoning=reasoning,
            visible_items=visible_items,
            visible_activities=visible_activities,
            asset_references=candidate.asset_references,
        )


class OpenAICompatibleStageTwoAdapter(RemoteAPIMixin):
    def __init__(self, registration: dict):
        super().__init__(registration)
        self.model_name = str(self.runtime.get("model_name") or "").strip()
        self.model_name_env = str(self.runtime.get("model_name_env") or "").strip()
        self.api_key_env = str(self.runtime.get("api_key_env") or "").strip()
        self.base_url_env = str(self.runtime.get("base_url_env") or "").strip()
        self.default_base_url = str(self.runtime.get("base_url") or "https://api.openai.com/v1").strip()
        self.system_prompt = str(
            self.runtime.get("system_prompt")
            or "You are an anomaly detection analyst. Return strict JSON with keys title, category, score, reasoning, visible_items, visible_activities."
        ).strip()

    def build_event(
        self,
        *,
        candidate: StageOneCandidate,
        prompts: PromptBundle,
    ) -> AnomalyEvent:
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            return self._fallback_event(
                candidate=candidate,
                prompts=prompts,
                detail=f"missing {self.api_key_env}",
            )
        base_url = os.environ.get(self.base_url_env, "").strip() or self.default_base_url
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        payload = self._build_request_payload(candidate=candidate, prompts=prompts)
        model_name = os.environ.get(self.model_name_env, "").strip() if self.model_name_env else ""
        if not model_name:
            model_name = self.model_name
        request_body = {
            "model": model_name,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": json.dumps(payload)},
            ],
        }
        req = request.Request(
            endpoint,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
            content = (
                raw.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "{}")
            )
            parsed = json.loads(content) if isinstance(content, str) else dict(content or {})
            return self._normalize_event(candidate=candidate, prompts=prompts, payload=parsed)
        except (error.URLError, TimeoutError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
            logger.warning("OpenAI-compatible anomaly adapter failed: %s", exc)
            return self._fallback_event(candidate=candidate, prompts=prompts, detail=str(exc))


class ClaudeStageTwoAdapter(RemoteAPIMixin):
    def __init__(self, registration: dict):
        super().__init__(registration)
        self.model_name = str(self.runtime.get("model_name") or "").strip()
        self.model_name_env = str(self.runtime.get("model_name_env") or "").strip()
        self.api_key_env = str(self.runtime.get("api_key_env") or "ANTHROPIC_API_KEY").strip()
        self.base_url_env = str(self.runtime.get("base_url_env") or "").strip()
        self.default_base_url = str(self.runtime.get("base_url") or "https://api.anthropic.com/v1").strip()
        self.system_prompt = str(
            self.runtime.get("system_prompt")
            or "You are an anomaly detection analyst. Return strict JSON with keys title, category, score, reasoning, visible_items, visible_activities."
        ).strip()
        self.api_version = str(self.runtime.get("api_version") or "2023-06-01").strip()

    def build_event(
        self,
        *,
        candidate: StageOneCandidate,
        prompts: PromptBundle,
    ) -> AnomalyEvent:
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            return self._fallback_event(
                candidate=candidate,
                prompts=prompts,
                detail=f"missing {self.api_key_env}",
            )
        base_url = os.environ.get(self.base_url_env, "").strip() or self.default_base_url
        endpoint = f"{base_url.rstrip('/')}/messages"
        payload = self._build_request_payload(candidate=candidate, prompts=prompts)
        model_name = os.environ.get(self.model_name_env, "").strip() if self.model_name_env else ""
        if not model_name:
            model_name = self.model_name
        request_body = {
            "model": model_name,
            "max_tokens": 700,
            "system": self.system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(payload),
                }
            ],
        }
        req = request.Request(
            endpoint,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": self.api_version,
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
            content_blocks = list(raw.get("content") or [])
            text_block = next(
                (
                    block.get("text")
                    for block in content_blocks
                    if isinstance(block, dict) and str(block.get("type") or "") == "text"
                ),
                "{}",
            )
            parsed = json.loads(text_block) if isinstance(text_block, str) else dict(text_block or {})
            return self._normalize_event(candidate=candidate, prompts=prompts, payload=parsed)
        except (error.URLError, TimeoutError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
            logger.warning("Claude anomaly adapter failed: %s", exc)
            return self._fallback_event(candidate=candidate, prompts=prompts, detail=str(exc))


STAGE_1_ADAPTERS = {
    "siglip_stage_1": SigLIPStageOneAdapter,
    "heuristic_presence_stage_1": HeuristicPresenceStageOneAdapter,
}


STAGE_2_ADAPTERS = {
    "smolvlm_stage_2": SmolVLMStageTwoAdapter,
    "prompt_rules_stage_2": PromptRulesStageTwoAdapter,
    "passthrough_stage_2": PassThroughStageTwoAdapter,
    "vlm_anomaly_demo_stage_2": VLMAnomalyDemoStageTwoAdapter,
    "openai_compatible_stage_2": OpenAICompatibleStageTwoAdapter,
    "claude_stage_2": ClaudeStageTwoAdapter,
}


def build_adapter(registration: dict):
    stage = str(registration.get("stage") or "").strip()
    adapter_name = registration.get("adapter")
    if stage == "anomaly_stage_1":
        adapter_cls = STAGE_1_ADAPTERS.get(adapter_name)
    elif stage == "anomaly_stage_2":
        adapter_cls = STAGE_2_ADAPTERS.get(adapter_name)
    else:
        raise ValueError(f"unknown anomaly stage {stage}")
    if adapter_cls is None:
        raise ValueError(f"unknown anomaly adapter {adapter_name}")
    return adapter_cls(registration)
