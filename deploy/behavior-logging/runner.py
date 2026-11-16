"""Headless inference using the real checkpoints referenced by Hearthlight Model Zoo.

This deliberately does not use the catalog's no-op detector or anomaly fallbacks.
No database, frontend, notification connectors, or external inference API is needed.
"""
from __future__ import annotations
from zone_crossings import attach_crossings,ground_exit_descriptions

import argparse
from datetime import datetime, timezone
import json
import logging
import math
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
from uuid import uuid4
from urllib.parse import urlparse

from runtime_configuration import RuntimeConfiguration,scene_context,configurable_prompt
from activity import ActivityStore
import moments
from object_focus import refine_reports
from snapshots import capture_snapshots, prune_snapshots
from clips import capture_clip, prune_clips
from scene import SCENE_PROMPT, build_request, labeled_frames, parse_scene
from feature_bank import FeatureBank
from reid_validation import capture_reid_encounters
from person_reid import PersonGallery, TransReID
from tracking import PersonDetector, link_detections

STOP = threading.Event()
LABELS = [
    "a person walking through an office",
    "a person sitting and working at a desk",
    "a person carrying or handling a bag",
    "a person picking up or moving an object",
    "a person putting an object into a bag",
    "an empty office with no visible people",
]
PROMPT = (
    "These are consecutive frames from an office camera. Describe the visible people, "
    "objects, and actions briefly in chronological order. Mention visible object or bag "
    "handling when present. Describe only what the frames support; state uncertainty "
    "when the view is unclear. Do not infer identity, ownership, intent, or criminality."
)

PERSON_PROMPT = (
    "These are consecutive crops around a tracked person. Briefly describe visible actions "
    "of the person centered in the crops. If several people are visible or the action is "
    "unclear, say what is uncertain. Do not infer identity, ownership, intent, or criminality."
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def make_log(name, path):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(path, maxBytes=10_000_000, backupCount=4)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def emit(logger, **payload):
    logger.info(json.dumps({"timestamp": utc_now(), **payload}))


def checkpoint_id(artifact_key):
    from hearthlight_model_zoo.artifacts import get_artifact_spec
    spec = get_artifact_spec(artifact_key)
    parsed = urlparse(spec.upstream_url)
    if parsed.hostname != "huggingface.co" or len(parsed.path.strip("/").split("/")) != 2:
        raise ValueError("Catalog artifact is not a Hugging Face model repository")
    return parsed.path.strip("/")


def validate_cameras(config):
    cameras = config.get("cameras")
    if not isinstance(cameras, list) or not cameras:
        raise ValueError("At least one camera must be configured")
    for camera in cameras:
        parsed = urlparse(camera.get("source", ""))
        if parsed.scheme != "rtsp" or not parsed.hostname:
            raise ValueError("Camera sources must be RTSP URLs")
        if not camera.get("id") or not camera.get("name"):
            raise ValueError("Camera id and name are required")
    return cameras


def sampling_settings():
    count = int(os.environ.get("BEHAVIOR_SAMPLE_FRAMES", "16"))
    fps = float(os.environ.get("BEHAVIOR_SAMPLE_FPS", "2"))
    if count < 2 or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Sampling requires at least two frames and a positive finite FPS")
    return count, fps


def sample_frames(source):
    """Sample briefly; never emit FFmpeg stderr, which can contain credentials."""
    from PIL import Image
    count, fps = sampling_settings()
    width = max(640, min(1920, int(os.environ.get("BEHAVIOR_FRAME_WIDTH", "640"))))
    with tempfile.TemporaryDirectory(prefix="hearthlight-frames-") as folder:
        try:
            result = subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                "-rtsp_transport", "tcp", "-timeout", "5000000", "-i", source,
                "-an", "-vf", f"fps={fps},scale={width}:-2", "-frames:v", str(count),
                "-q:v", "3", str(Path(folder) / "frame-%02d.jpg"),
            ], capture_output=True, timeout=max(12, count / fps + 8), check=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError("camera_connection_timeout") from None
        paths = sorted(Path(folder).glob("frame-*.jpg"))
        if result.returncode or not paths:
            raise RuntimeError("camera_stream_unavailable")
        if len(paths) < count:
            raise RuntimeError("camera_sample_incomplete")
        return [Image.open(path).convert("RGB").copy() for path in paths]


def scene_token_budget(request):
    # Long track catalogs otherwise truncate valid JSON and discard every report.
    return min(8192, max(2048, 512 + 384*len(request.get('tracks', [])) + 128*len(request.get('zones', []))))


class Models:
    def __init__(self, device):
        import torch
        from huggingface_hub import HfApi
        from transformers import AutoModelForImageTextToText, AutoModelForZeroShotImageClassification, AutoProcessor
        torch.set_num_threads(2)
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable")
        self.device = device
        self.dtype = torch.bfloat16 if device == "cuda" else torch.float32
        self.siglip_id = checkpoint_id("siglip-stage-1-cuda" if device == "cuda" else "siglip-stage-1-cpu")
        self.vlm_id = os.environ.get("BEHAVIOR_VLM_MODEL") or "Qwen/Qwen3-VL-2B-Instruct"
        manifest = Path("/models/checkpoints.json")
        self.revisions = json.loads(manifest.read_text()) if manifest.exists() else {}
        self.revisions = {key: value for key, value in self.revisions.items()
                          if key in (self.siglip_id, self.vlm_id)}
        cached_ids = set(self.revisions)
        for model_id in (self.siglip_id, self.vlm_id):
            if model_id not in self.revisions:
                self.revisions[model_id] = HfApi().model_info(model_id).sha
        self.siglip_processor = AutoProcessor.from_pretrained(self.siglip_id, revision=self.revisions[self.siglip_id], use_fast=False, local_files_only=self.siglip_id in cached_ids)
        self.siglip = AutoModelForZeroShotImageClassification.from_pretrained(
            self.siglip_id, revision=self.revisions[self.siglip_id], dtype=self.dtype, local_files_only=self.siglip_id in cached_ids,
        ).to(device).eval()
        self.vlm_processor = AutoProcessor.from_pretrained(
            self.vlm_id, revision=self.revisions[self.vlm_id], use_fast=False,
            local_files_only=self.vlm_id in cached_ids,
            min_pixels=128 * 32 * 32, max_pixels=256 * 32 * 32,
        )
        self.vlm = AutoModelForImageTextToText.from_pretrained(
            self.vlm_id, revision=self.revisions[self.vlm_id], dtype=self.dtype,
            local_files_only=self.vlm_id in cached_ids, low_cpu_mem_usage=True,
        ).to(device).eval()

        temporary = manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.revisions, indent=2))
        temporary.replace(manifest)

    def visual_matches(self, images):
        import torch
        batch = self.siglip_processor(text=LABELS, images=images[-1], padding="max_length", return_tensors="pt")
        batch = {key: value.to(self.device, dtype=self.dtype) if value.is_floating_point() else value.to(self.device) for key, value in batch.items()}
        with torch.inference_mode():
            scores = self.siglip(**batch).logits_per_image.sigmoid()[0].float().cpu().tolist()
        matches = sorted(zip(LABELS, scores), key=lambda item: item[1], reverse=True)[:3]
        return [{"label": label, "uncalibrated_similarity": score} for label, score in matches]

    def analyze(self, images):
        return {"description": self.describe(images, PROMPT), "visual_matches": self.visual_matches(images),
                "frame_count": len(images), "model_revisions": self.revisions}

    def describe(self, images, prompt, max_new_tokens=160):
        import torch
        content = []
        for index in range(len(images)):
            content.extend([{"type": "text", "text": f"Frame {index}:"}, {"type": "image"}])
        content.append({"type": "text", "text": (
            f"There are exactly {len(images)} frames, numbered 0 through {len(images) - 1}. "
            "All frame indices in your answer must be within that range. " + prompt
        )})
        messages = [{"role": "user", "content": content}]
        text = self.vlm_processor.apply_chat_template(messages, add_generation_prompt=True)
        batch = self.vlm_processor(text=text, images=images, return_tensors="pt")
        batch = {key: value.to(self.device, dtype=self.dtype) if value.is_floating_point() else value.to(self.device) for key, value in batch.items()}
        with torch.inference_mode():
            output = self.vlm.generate(**batch, max_new_tokens=max_new_tokens, do_sample=False)
        description = self.vlm_processor.batch_decode(
            output[:, batch["input_ids"].shape[1]:], skip_special_tokens=True,
        )[0].strip()
        if not description:
            raise RuntimeError("model_returned_empty_description")
        return description

    def describe_text(self, prompt, max_new_tokens=384):
        """Reuse the loaded Qwen model for text-only contextual evaluation."""
        import torch
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        text = self.vlm_processor.apply_chat_template(messages, add_generation_prompt=True)
        batch = self.vlm_processor(text=text, return_tensors="pt")
        batch = {key: value.to(self.device) for key, value in batch.items()}
        with torch.inference_mode():
            output = self.vlm.generate(**batch, max_new_tokens=max_new_tokens, do_sample=False)
        return self.vlm_processor.batch_decode(output[:, batch["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()


def analyze_sample(detector, models, frames, sample, store, operations, reid=None, gallery=None):
    tracks = []
    tracking_status = "unavailable"
    if detector is not None:
        try:
            tracks = link_detections(detector.detect(frames))
            tracking_status = "ready"
        except Exception as error:
            tracking_status = "error"
            emit(operations, state="person_detection_error", error_type=type(error).__name__, **sample)
    person_ids = [None] * len(tracks)
    if reid is not None and gallery is not None:
        try:
            qualities=[sum(min(1,(box[2]-box[0])/64)*min(1,(box[3]-box[1])/128) for _,box in track)/max(1,len(track)) for track in tracks]
            assignments = gallery.assign([
                reid.embed([frames[index].crop(box) for index, box in track]) for track in tracks
            ], observed_at=datetime.fromisoformat(sample.get("sample_started_at", sample["sampled_at"])).timestamp(),
                tracks=tracks,qualities=qualities,track_keys=[f"{sample['sample_id']}:{i}" for i in range(len(tracks))])
            if len(assignments) != len(tracks):
                raise ValueError("person_assignment_count_mismatch")
            person_ids = assignments
            if isinstance(getattr(gallery,"bank",None),FeatureBank):
                with gallery.db:
                    gallery.bank.record_conflicts(tracks,person_ids)
                    merges=gallery.bank.merge_window(time.time(),sample['sample_id'],active_ids={p for p in person_ids if p})
                    person_ids=[gallery.bank.resolve(p) if p else None for p in person_ids]
                if merges:emit(operations,state="reid_identities_merged",merge_count=len(merges),**sample)
                emit(operations,state="identity_merge_check_completed",merge_count=len(merges),**sample)
            gallery.record_tracks(sample, tracks, person_ids)
        except Exception as error:
            emit(operations, state="person_reid_error", error_type=type(error).__name__, **sample)
    request = build_request(sample, frames, tracks, person_ids, tracking_status)
    sample["zone_reports"] = request.get("zone_reports", [])
    try:
        if gallery is not None:
            capture_reid_encounters(gallery, frames, request, store.path)
    except Exception as error:
        emit(operations, state="reid_validation_capture_error", error_type=type(error).__name__, **sample)
    try:
        capture_snapshots(frames, request, store.path)
    except Exception as error:
        emit(operations, state="person_snapshot_error", error_type=type(error).__name__, **sample)
    for track in request["tracks"]:
        if track["person_id"] is not None:
            aliases = gallery.bank.group(track["person_id"]) if gallery is not None and isinstance(getattr(gallery,"bank",None),FeatureBank) else [track["person_id"]]
            track["behavior_context"] = moments.prior_context(store.db, aliases, sample["sampled_at"])
            track["person_description"] = sample.get("person_contexts", {}).get(track["person_id"], "")
            track["prior_state"] = store.prior_state(track["person_id"],gallery.bank.group(track["person_id"])) if gallery is not None and isinstance(getattr(gallery,"bank",None),FeatureBank) else store.prior_state(track["person_id"])
    try:
        capture_clip(frames, request, store.path)
    except Exception as error:
        emit(operations, state="person_clip_error", error_type=type(error).__name__, **sample)
    visual_matches = []
    try:
        visual_matches = models.visual_matches(frames)
    except Exception as error:
        emit(operations, state="visual_matching_error", error_type=type(error).__name__, **sample)
    raw_output = analysis = None
    status, error_code = "inference_failed", None
    try:
        model_request = {**{k:v for k,v in request.items() if k != "recorded_clip"}, "tracks": [{k: v for k, v in track.items() if not k.startswith("snapshot_")}
                                               for track in request["tracks"]]}
        raw_output = models.describe(labeled_frames(frames, request),
                                     SCENE_PROMPT + configurable_prompt(sample.get("capture_settings")) + "\n\nINPUT_JSON:\n" + json.dumps(model_request),
                                     max_new_tokens=scene_token_budget(request))
        status = "invalid_response"
        analysis = parse_scene(raw_output, request, frames)
        status = "analyzed"
    except (ValueError, TypeError) as error:
        error_code = type(error).__name__
        emit(operations, state="scene_response_invalid", error_type=error_code, **sample)
    except Exception as error:
        error_code = type(error).__name__
        emit(operations, state="scene_inference_error", error_type=error_code, **sample)
    analysis = attach_crossings(analysis, request)
    if analysis is not None and (analysis["errors"] or any(
            report["analysis_status"] != "analyzed" for report in analysis["persons"])):
        emit(operations, state="person_analysis_incomplete", issues=analysis["errors"], **sample)
    if analysis is not None:
        refine_reports(models, frames, request, analysis)
        analysis=ground_exit_descriptions(analysis,request)
        moment_sample = {**sample, "activity_model": models.vlm_id,
                         "activity_model_revision": models.revisions[models.vlm_id]}
        aliases_for = gallery.bank.group if gallery is not None and isinstance(getattr(gallery, "bank", None), FeatureBank) else None
        evaluated_moments = moments.prepare_reports(store.db, moment_sample, request, analysis, models.describe_text, aliases_for)
        for moment in evaluated_moments:
            if moment["evaluation_status"] != "evaluated":
                emit(operations, state="moment_evaluation_failed", error_type=moment.get("error_code"), **sample)
    result = store.record_analysis({**sample, "activity_model": models.vlm_id,
                                   "activity_model_revision": models.revisions[models.vlm_id]},
                                  request, analysis, raw_output, status, error_code, visual_matches)
    evaluated = list({behavior["moment"]["log_id"]: behavior["moment"] for behavior in result["behaviors"] if behavior.get("moment")}.values())
    if evaluated:
        emit(operations, state="person_moments_processed", sample_id=sample["sample_id"], camera_id=sample["camera_id"],
             keyframes=sum(moment.get("keyframe", False) for moment in evaluated),
             merged=sum(moment.get("evaluation_status") == "evaluated" and not moment.get("keyframe") for moment in evaluated),
             failed=sum(moment.get("evaluation_status") != "evaluated" for moment in evaluated))
    result["scene_ok"] = result["scene"]["analysis_status"] == "analyzed"
    try:
        prune_snapshots(request, store.path)
    except OSError as error:
        emit(operations, state="person_snapshot_cleanup_error", error_type=type(error).__name__, **sample)
    result["people_ok"] = (tracking_status == "ready" and result["scene_ok"] and analysis is not None
                           and not analysis["errors"] and all(
                               report["analysis_status"] == "analyzed" for report in analysis["persons"]))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/config/cameras.json")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    logs = Path(os.environ.get("BEHAVIOR_LOG_DIR", "/logs"))
    logs.mkdir(parents=True, exist_ok=True)
    operations = make_log("behavior.operations", logs / "operations.jsonl")
    people = make_log("behavior.people", logs / "people.jsonl")
    scenes = make_log("behavior.scenes", logs / "scenes.jsonl")
    behaviors = make_log("behavior.behaviors", logs / "person-behaviors.jsonl")
    activities = make_log("behavior.activities", logs / "activities.jsonl")
    activity_store = ActivityStore(logs / "person-activities.sqlite3")
    observations = make_log("behavior.observations", logs / "observations.jsonl")
    def status(state, **extra):
        payload = {"timestamp": utc_now(), "state": state, **extra}
        temporary = logs / "status.tmp"
        temporary.write_text(json.dumps(payload))
        temporary.replace(logs / "status.json")
        emit(operations, state=state, **extra)
        print(json.dumps(payload), flush=True)
    status("loading_models")
    models = Models(os.environ.get("BEHAVIOR_DEVICE", "cuda"))
    status("models_ready", model_revisions=models.revisions)
    # Exercise text-only Qwen with an explicitly synthetic, in-memory example.
    # No production person, evidence, inventory or alert rows are written.
    import sqlite3
    with sqlite3.connect(":memory:") as probe_db:
        moments.initialize(probe_db)
        probe = moments.prepare(probe_db,
            {"sample_id": "synthetic-model-check", "camera_id": "synthetic-camera", "sampled_at": "2000-01-01T00:00:00Z", "activity_model": models.vlm_id},
            {"person_id": "synthetic-person", "track_id": 1},
            {"description": "A person sits at a desk.", "events": [], "interactions": []},
            "An office with a desk.", models.describe_text)
    moment_model_ready = probe["evaluation_status"] == "evaluated"
    (logs / "moment-model-check.json").write_text(json.dumps({"synthetic_input": True, "model_id": models.vlm_id,
        "ready": moment_model_ready, "error_code": probe.get("error_code")}))
    emit(operations, state="context_model_ready" if moment_model_ready else "context_model_unavailable", model_id=models.vlm_id)

    weights = Path(os.environ.get("BEHAVIOR_PERSON_WEIGHTS", "/models/yolov8n.pt"))
    detector = None
    if weights.is_file():
        try:
            detector = PersonDetector(models.device, weights)
        except Exception as error:
            emit(operations, state="person_detector_unavailable", error_type=type(error).__name__)
    else:
        emit(operations, state="person_detector_unavailable", error_type="weights_missing")
    if args.smoke_test:
        from PIL import Image, ImageDraw
        images = []
        for offset in (0, 20, 40):
            image = Image.new("RGB", (640, 360), "white")
            ImageDraw.Draw(image).rectangle((160 + offset, 100, 440 + offset, 260), fill="blue")
            images.append(image)
        result = models.analyze(images)
        if detector is not None:
            result["person_detections"] = sum(map(len, detector.detect(images)))
            result["person_description"] = models.describe(images[:2], PERSON_PROMPT)
        (logs / "smoke-test.json").write_text(json.dumps({"synthetic_input": True, **result}, indent=2))
        print("Both real models completed inference on synthetic input", flush=True)
        return
    runtime_url=os.environ.get("BEHAVIOR_RUNTIME_URL")
    runtime=RuntimeConfiguration(runtime_url,os.environ.get("BEHAVIOR_RUNTIME_TOKEN_FILE","/logs/behavior-runtime.token"),logs) if runtime_url else None
    cameras=[] if runtime else validate_cameras(json.loads(Path(args.config).read_text()))
    reid = gallery = None
    try:
        candidate = TransReID(models.device, Path("/models/transreid_market1501.pth"))
        gallery = PersonGallery(logs / "person-gallery.sqlite3", candidate.key,
            prototype_limit=int(os.environ.get("BEHAVIOR_REID_PROTOTYPES","8")),
            relaxed_threshold=float(os.environ.get("BEHAVIOR_REID_RELAXED_THRESHOLD","0.76")))
        reid = candidate
    except Exception as error:
        emit(operations, state="person_reid_unavailable", error_type=type(error).__name__)
    interval = max(10, float(os.environ.get("BEHAVIOR_INTERVAL_SECONDS", "30")))
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: STOP.set())
    while not STOP.is_set():
        try:
            prune_clips(activity_store.path)
        except OSError as error:
            emit(operations, state="person_clip_cleanup_error", error_type=type(error).__name__)
        started = time.monotonic()
        successes = 0
        inputs_received = 0
        tracked = 0
        configuration={}
        if runtime:
            try:configuration=runtime.get();cameras=configuration['cameras']
            except Exception as error:
                emit(operations,state="runtime_configuration_unavailable",error_type=type(error).__name__)
                STOP.wait(10);continue
        for camera in cameras:
            if STOP.is_set():
                break
            if runtime:
                try:
                    configuration=runtime.get()
                    camera=next((c for c in configuration['cameras'] if c['id']==camera['id']),None)
                    if camera is None:continue
                except Exception as error:
                    emit(operations,state="runtime_configuration_unavailable",error_type=type(error).__name__);break
            sample_started_at = utc_now()
            try:
                frames = sample_frames(camera["source"])
            except RuntimeError as error:
                if runtime:runtime.status(camera["id"],False)
                emit(operations, state=str(error), camera_id=camera["id"], camera_name=camera["name"])
                continue
            if runtime:runtime.status(camera["id"],True)
            inputs_received += 1
            sample = dict(campus=camera.get("location",{}).get("site","Office"), camera_id=camera["id"], camera_name=camera["name"],
                          sample_id=uuid4().hex, sampled_at=utc_now(), sample_started_at=sample_started_at,
                          sample_frame_count=len(frames), sample_fps=sampling_settings()[1])
            sample["zones"]=camera.get("zones",[])
            sample["scene_context"]=scene_context(camera,sample)
            sample["capture_settings"]=configuration.get("capture",{})
            sample["person_contexts"]=configuration.get("person_contexts",{})
            sample["alert_rules"]=configuration.get("alert_rules",[])
            sample["person_flags"]=configuration.get("person_flags",{})
            if camera.get("building_exit"):
                sample["building_exit"] = camera["building_exit"]
            try:
                result = analyze_sample(detector, models, frames, sample, activity_store, operations, reid, gallery)
            except Exception as error:
                emit(operations, state="scene_storage_error", error_type=type(error).__name__, **sample)
                continue
            successes += int(result["scene_ok"])
            tracked += int(result["people_ok"])
            if result["inserted"]:
                scenes.info(json.dumps(result["scene"]))
                if result["scene_ok"]:
                    emit(observations, **sample, scene_id=sample["sample_id"],
                         description=result["scene"]["description"],
                         visual_matches=result["scene"]["visual_matches"], frame_count=len(frames),
                         model_revisions=models.revisions)
                for behavior in result["behaviors"]:
                    behaviors.info(json.dumps(behavior))
                    emit(people, **sample, scene_id=sample["sample_id"],
                         track_id=behavior["track_id"], person_id=behavior["person_id"],
                         behavior_id=behavior["behavior_id"], description=behavior["description"],
                         activity_status=behavior["analysis_status"], detections=behavior["detections"],
                         activity_model_output=result["scene"]["raw_model_output"],
                         activity_event_ids=[row["event_id"] for row in result["activities"]
                                             if row["track_id"] == behavior["track_id"]])
                for activity in result["activities"]:
                    activities.info(json.dumps(activity))
        state = "idle" if not cameras else "logging" if successes else "inference_failed" if inputs_received else "waiting_for_cameras"
        status(state, cameras=len(cameras), received=inputs_received, analyzed=successes, person_detector_ready=detector is not None,
               person_analysis_completed=tracked, person_reid_ready=reid is not None,
               person_reid_mode="sliding_window_rerank" if reid is not None else None,
               item_activity_logging_ready=True, linked_scene_behavior_logging_ready=True, sample_frames=sampling_settings()[0],
               sample_fps=sampling_settings()[1], activity_model=models.vlm_id)
        STOP.wait(max(1, interval - (time.monotonic() - started)))
    status("stopped")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print exception text or source URLs from configuration.
        print(json.dumps({"state": "startup_failed", "error_type": type(error).__name__}), flush=True)
        raise SystemExit(1)
