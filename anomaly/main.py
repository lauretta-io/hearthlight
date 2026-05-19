from __future__ import annotations

from collections import defaultdict
import logging
import queue
from threading import Thread
import time

from omegaconf import DictConfig

from .adapters import PromptCatalog, build_adapter
from .output_threads import OutputThread
from ..shared.constants import (
    ANOMALY_EVAL_INTERVAL,
    FPS_INTERVAL,
    FRAME_UPDATE_INTERVAL,
    ModuleNames,
    QUEUE_TIMEOUT,
)
from ..shared.database.database_worker import DatabaseWorker
from ..shared.models.DataModels import Status, StatusMessage
from ..shared.rabbit_messenger import (
    RoutingKey,
    StatusPublisher,
    get_anomaly_message_consumer,
)
from ..shared.slave import run_command_listener
from ..shared.utils.backpressure import summarize_queue_backpressure
from ..shared.utils.logger import set_run_logging
from ..shared.utils.model_registry import (
    MODEL_STAGE_ANOMALY_STAGE_1,
    MODEL_STAGE_ANOMALY_STAGE_2,
    build_default_bindings,
    get_registration,
    load_registry_bundle,
)
from ..shared.utils.runtime_guard import get_dead_thread_names
from ..shared.utils.timer import LoopTimer

logger = logging.getLogger(__name__)


class Anomaly(Thread):
    def __init__(self, cfg: DictConfig, status_publisher: StatusPublisher):
        super().__init__(name=self.__class__.__name__, daemon=True)
        set_run_logging(cfg, module_name=ModuleNames.ANOMALY)
        try:
            self.process = False
            self.consumer = get_anomaly_message_consumer()
            self.output_thread = OutputThread()
            self.status_publisher = status_publisher
            self.run_identifier = getattr(cfg, "run_id", None)
            if self.run_identifier:
                DatabaseWorker.set_run_id(self.run_identifier)

            self.registry_bundle = load_registry_bundle()
            defaults = build_default_bindings(
                self.registry_bundle,
                runtime_model_bindings=getattr(cfg, "model_bindings", None),
            )
            self.default_stage_1_model_key = defaults.get(MODEL_STAGE_ANOMALY_STAGE_1)
            self.default_stage_2_model_key = defaults.get(MODEL_STAGE_ANOMALY_STAGE_2)

            if not self.default_stage_1_model_key or not self.default_stage_2_model_key:
                raise ValueError("missing anomaly stage model defaults")

            self.camera_source_ids: dict[int, int | None] = {}
            self.camera_stage_one_model_keys: dict[int, str] = {}
            self.camera_stage_two_model_keys: dict[int, str] = {}
            self.camera_eval_interval: dict[int, float] = {}
            self.track_time: dict[int, float] = {}
            self.cam_last_eval: dict[int, float | None] = {}

            self.stage_one_adapters = {}
            self.stage_two_adapters = {}
            self.prompt_catalog_by_stage_two_key: dict[str, PromptCatalog] = {}
            self.frame_update_interval = float(
                getattr(getattr(cfg, "anomaly", {}), "frame_update_interval", FRAME_UPDATE_INTERVAL)
            )

            for cam_id, camera_cfg in cfg.input.cameras.items():
                camera_dict = dict(camera_cfg)
                source_id = camera_dict.get("source_template_id")
                stage_1_model_key = (
                    camera_dict.get("anomaly_stage_1_model_key") or self.default_stage_1_model_key
                )
                stage_2_model_key = (
                    camera_dict.get("anomaly_stage_2_model_key") or self.default_stage_2_model_key
                )
                self.camera_source_ids[cam_id] = source_id
                self.camera_stage_one_model_keys[cam_id] = stage_1_model_key
                self.camera_stage_two_model_keys[cam_id] = stage_2_model_key
                self.track_time[cam_id] = 0.0
                self.cam_last_eval[cam_id] = None

                stage_1_registration = get_registration(
                    self.registry_bundle,
                    MODEL_STAGE_ANOMALY_STAGE_1,
                    stage_1_model_key,
                )
                if stage_1_registration is None:
                    raise ValueError(f"missing anomaly stage_1 registration {stage_1_model_key}")
                if stage_1_model_key not in self.stage_one_adapters:
                    self.stage_one_adapters[stage_1_model_key] = build_adapter(stage_1_registration)
                self.camera_eval_interval[cam_id] = float(
                    (stage_1_registration.get("runtime") or {}).get(
                        "eval_interval",
                        ANOMALY_EVAL_INTERVAL,
                    )
                )

                stage_2_registration = get_registration(
                    self.registry_bundle,
                    MODEL_STAGE_ANOMALY_STAGE_2,
                    stage_2_model_key,
                )
                if stage_2_registration is None:
                    raise ValueError(f"missing anomaly stage_2 registration {stage_2_model_key}")
                if stage_2_model_key not in self.stage_two_adapters:
                    self.stage_two_adapters[stage_2_model_key] = build_adapter(stage_2_registration)
                    runtime = stage_2_registration.get("runtime") or {}
                    self.prompt_catalog_by_stage_two_key[stage_2_model_key] = PromptCatalog(
                        runtime.get("prompt_yaml_path", "shared/prompts/prompt_v2.yaml"),
                        runtime.get("anomaly_list_yaml_path", "shared/prompts/anomaly_list.yaml"),
                    )
        except Exception:
            logger.exception("Failed to initialize", extra={"task": self.name})
            raise

    def run(self):
        logger.info("Starting", extra={"task": self.name})
        self.process = True
        self.consumer.start()
        self.output_thread.start()
        timer = LoopTimer(log_interval=FPS_INTERVAL, task=ModuleNames.ANOMALY, abbrev="anom")
        timer.start()
        last_metrics_update = float("-inf")

        while self.process:
            dead_workers = get_dead_thread_names(
                {
                    "consumer": self.consumer,
                    "output_thread": self.output_thread,
                }
            )
            if dead_workers:
                reason = f"critical worker threads exited unexpectedly: {', '.join(dead_workers)}"
                logger.error(reason, extra={"task": self.name})
                self.status_publisher.publish(
                    StatusMessage(
                        status=Status.ERROR,
                        module=ModuleNames.ANOMALY,
                        extra={"reason": reason},
                    )
                )
                self.process = False
                continue

            try:
                frame_id, message = self.consumer.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            timer.time("fetch")
            frame_message = message.get(RoutingKey.FRAME_INFO)
            if frame_message is None:
                continue
            frames = frame_message.frames

            person_message = message.get(RoutingKey.PERSON)
            bag_message = message.get(RoutingKey.BAG)
            person_tracks_by_cam = defaultdict(list)
            bag_tracks_by_cam = defaultdict(list)
            for track in getattr(person_message, "track_instances", []):
                person_tracks_by_cam[track.cam_id].append(track)
            for track in getattr(bag_message, "track_instances", []):
                bag_tracks_by_cam[track.cam_id].append(track)

            events = []
            for frame in frames:
                cam_id = frame.cam_id
                if cam_id not in self.camera_stage_one_model_keys:
                    continue

                if frame.timestamp - self.track_time[cam_id] < self.frame_update_interval:
                    continue
                self.track_time[cam_id] = frame.timestamp

                eval_interval = self.camera_eval_interval.get(cam_id, ANOMALY_EVAL_INTERVAL)
                last_eval = self.cam_last_eval.get(cam_id)
                if last_eval is not None and frame.timestamp - last_eval < eval_interval:
                    continue
                self.cam_last_eval[cam_id] = frame.timestamp

                stage_1_model_key = self.camera_stage_one_model_keys[cam_id]
                stage_2_model_key = self.camera_stage_two_model_keys[cam_id]
                stage_1_adapter = self.stage_one_adapters[stage_1_model_key]
                stage_2_adapter = self.stage_two_adapters[stage_2_model_key]
                prompt_catalog = self.prompt_catalog_by_stage_two_key[stage_2_model_key]
                prompts = prompt_catalog.load()

                stage_1_candidates = stage_1_adapter.evaluate(
                    stage_1_model_key=stage_1_model_key,
                    stage_2_model_key=stage_2_model_key,
                    source_id=self.camera_source_ids.get(cam_id),
                    camera_id=cam_id,
                    frame_id=frame_id,
                    timestamp=frame.timestamp,
                    person_tracks=person_tracks_by_cam.get(cam_id, []),
                    bag_tracks=bag_tracks_by_cam.get(cam_id, []),
                    frame_save_path=getattr(frame, "save_path", None),
                    run_id=self.run_identifier,
                )
                for candidate in stage_1_candidates:
                    event = stage_2_adapter.build_event(candidate=candidate, prompts=prompts)
                    if event is not None:
                        events.append(event)

            if events:
                self.output_thread.queue.put((frame_id, events))
            timer.time("detect")

            current_time = time.time()
            if current_time - last_metrics_update > FRAME_UPDATE_INTERVAL:
                queue_depths = {
                    "consumer": self.consumer.queue.qsize(),
                    "output_thread": self.output_thread.queue.qsize(),
                    "rabbit_thread": self.output_thread.rabbit_thread.queue.qsize(),
                    "database_thread": self.output_thread.database_thread.queue.qsize(),
                }
                self.status_publisher.publish(
                    StatusMessage(
                        status=Status.INFO,
                        module=ModuleNames.ANOMALY,
                        extra={
                            "queue_depths": queue_depths,
                            "backpressure": summarize_queue_backpressure(queue_depths),
                            "anomaly_events": len(events),
                        },
                    )
                )
                last_metrics_update = current_time
            timer.loop()

        self.consumer.stop()
        self.output_thread.stop()
        self.consumer.join()
        self.output_thread.join()
        logger.info("Stopped", extra={"task": self.name})

    def stop(self):
        self.process = False


if __name__ == "__main__":
    run_command_listener(ModuleNames.ANOMALY, Anomaly)
