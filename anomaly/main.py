from __future__ import annotations

from collections import defaultdict, deque
import logging
import queue
from threading import Thread
import time

from omegaconf import DictConfig

from .adapters import build_adapter
from .output_threads import OutputThread
from ..shared.database.database_worker import DatabaseWorker
from ..shared.constants import FPS_INTERVAL, FRAME_UPDATE_INTERVAL, ModuleNames, QUEUE_TIMEOUT, ANOMALY_EVAL_INTERVAL
from ..shared.models.DataModels import Status, StatusMessage
from ..shared.rabbit_messenger import RoutingKey, StatusPublisher, get_anomaly_message_consumer
from ..shared.slave import run_command_listener
from ..shared.utils.backpressure import summarize_queue_backpressure
from ..shared.utils.logger import set_run_logging
from ..shared.utils.model_registry import (
    MODEL_STAGE_ANOMALY,
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
            self.default_model_key = defaults.get(MODEL_STAGE_ANOMALY)
            self.camera_source_ids = {}
            self.camera_model_keys = {}
            self.adapters = {}
            self.track_frames = {}
            self.track_time = {}
            self.cam_last_eval = {}
            self.eval_interval = None
            for cam_id, camera_cfg in cfg.input.cameras.items():
                camera_dict = dict(camera_cfg)
                source_id = camera_dict.get("source_template_id")
                model_key = camera_dict.get("anomaly_model_key") or self.default_model_key
                self.camera_source_ids[cam_id] = source_id
                self.camera_model_keys[cam_id] = model_key
                if model_key not in self.adapters:
                    registration = get_registration(
                        self.registry_bundle,
                        MODEL_STAGE_ANOMALY,
                        model_key,
                    )
                    if registration is None:
                        raise ValueError(f"missing anomaly registration {model_key}")
                    self.adapters[model_key] = build_adapter(registration)
                    if self.eval_interval is None:
                        self.eval_interval = registration.get("runtime", {}).get("eval_interval", ANOMALY_EVAL_INTERVAL)
                self.track_frames[cam_id] = deque(maxlen=30) # track 1 frame per second for the last 30 seconds 
                self.track_time[cam_id] = 0
                self.cam_last_eval[cam_id] = None
        except Exception:
            logger.exception("Failed to initialize", extra={"task": self.name})
            raise

    def run(self):
        print("is this even running?")
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
            frames = message.get(RoutingKey.FRAME_INFO)
            if frames is None:
                continue
            for frame_id, frame in frames:
                cam_id = frame.cam_id
                if frame.timestamp - self.track_time[cam_id] >= FRAME_UPDATE_INTERVAL:
                    self.track_time[cam_id] = frame.timestamp
                    self.track_frames[cam_id].append(frame.array)

                    if ((self.cam_last_eval[cam_id] is None and len(self.track_frames[cam_id]) >= self.eval_interval)
                          or (frame.timestamp - self.cam_last_eval[cam_id] >= self.eval_interval)):
                        adapter = self.adapters.get(self.camera_model_keys.get(cam_id, self.default_model_key))
                        adapter.evaluate(self.track_frames[cam_id][-16:])
                        self.cam_last_eval[cam_id] = frame.timestamp
            person_message = message.get(RoutingKey.PERSON)
            bag_message = message.get(RoutingKey.BAG)
            person_tracks_by_cam = defaultdict(list)
            bag_tracks_by_cam = defaultdict(list)
            for track in getattr(person_message, "track_instances", []):
                person_tracks_by_cam[track.cam_id].append(track)
            for track in getattr(bag_message, "track_instances", []):
                bag_tracks_by_cam[track.cam_id].append(track)

            events = []
            for frame in frames.frames:
                model_key = self.camera_model_keys.get(frame.cam_id, self.default_model_key)
                source_id = self.camera_source_ids.get(frame.cam_id)
                adapter = self.adapters[model_key]
                events.extend(
                    adapter.evaluate(
                        model_key=model_key,
                        source_id=source_id,
                        frame_id=frame_id,
                        timestamp=frame.timestamp,
                        person_tracks=person_tracks_by_cam.get(frame.cam_id, []),
                        bag_tracks=bag_tracks_by_cam.get(frame.cam_id, []),
                        frame_save_path=getattr(frame, "save_path", None),
                        run_id=self.run_identifier,
                    )
                )
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

    def stop(self):
        self.process = False


if __name__ == "__main__":
    run_command_listener(ModuleNames.ANOMALY, Anomaly)
