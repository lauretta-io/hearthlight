import queue
import time
from threading import Thread
import logging
from collections import deque

from omegaconf import DictConfig

try:
    import torch
except ModuleNotFoundError:  # pragma: no cover - optional in local CPU runtime
    torch = None

from .models import Detector
from .output_threads import OutputThread
from .input_media import MultiCapture, FramesThread
from ..shared.slave import run_command_listener
from ..shared.utils.logger import set_bootstrap_logging, set_run_logging
from ..shared.utils.backpressure import summarize_queue_backpressure
from ..shared.utils.runtime_guard import (
    get_dead_thread_names,
    get_missing_frame_failure_reason,
    should_fail_for_missing_frames,
)
from ..shared.utils.timer import LoopTimer
from ..shared.models.DataModels import Run, StatusMessage, Status
from ..shared.database.database_worker import DatabaseWorker
from ..shared.rabbit_messenger import StatusPublisher
from ..shared.constants import (
    QUEUE_TIMEOUT,
    SHORT_SLEEP,
    FPS_INTERVAL,
    FRAME_UPDATE_INTERVAL,
    ANOMALY_EVAL_INTERVAL,
    ModuleNames,
)

logger = logging.getLogger(__name__)


class Ingestor(Thread):
    def __init__(self, cfg: DictConfig, status_publisher: StatusPublisher):
        super().__init__(name=self.__class__.__name__, daemon=True)

        set_bootstrap_logging(cfg, module_name=ModuleNames.INGESTOR)
        try:
            logger.debug("Initializing", extra={"task": self.name})
            self.process = False
            self.cfg = cfg
            self.detector = Detector(cfg)
            
            self.capture = MultiCapture(
                cfg.input.cameras,
                resize=cfg.input.get("resize"),
                record_dir=None
                if not cfg.output.video.save_raw
                else cfg.output.video.raw_path,
            )
            
            self.track_frames = {}
            self.track_time = {}
            self.cam_last_eval = {}
            self.eval_interval = cfg.anomaly.get("eval_interval", ANOMALY_EVAL_INTERVAL)
            for cam_id in cfg.input.cameras:
                self.track_frames[cam_id] = deque(maxlen=30) # track 1 frame per second for the last 30 seconds 
                self.track_time[cam_id] = 0
                self.cam_last_eval[cam_id] = None

            self.frames_thread = FramesThread(self.capture, max_fps=cfg.input.max_fps)
            self.output_thread = OutputThread(cfg, self.capture.cameras)
            self.run_info = Run(
                run_identifier=cfg.run_id,
                output_dir=cfg.output.output_dir,
                cameras=self.capture.cameras,
            )
            self.run_info_published = False
            self.run_logging_activated = False
            self.no_frame_timeout = float(cfg.input.get("no_frame_timeout", 15.0))
            self.status_publisher = status_publisher
        except Exception:
            logger.exception("Failed to initialize", extra={"task": self.name})
            raise

        logger.debug("Initialized", extra={"task": self.name})

    def run(self):
        logger.info("Starting", extra={"task": self.name})

        self.process = True
        self.output_thread.start()
        self.frames_thread.start()

        last_frame_update = float("-inf")
        last_metrics_update = float("-inf")
        last_frame_received_at = time.time()
        timer = LoopTimer(
            log_interval=FPS_INTERVAL, task=ModuleNames.INGESTOR, abbrev="ing."
        )
        timer.start()

        while self.process:
            dead_workers = get_dead_thread_names(
                {
                    "frames_thread": self.frames_thread,
                    "output_thread": self.output_thread,
                }
            )
            if dead_workers:
                reason = f"critical worker threads exited unexpectedly: {', '.join(dead_workers)}"
                logger.error(reason, extra={"task": self.name})
                self.status_publisher.publish(
                    StatusMessage(
                        status=Status.ERROR,
                        module=ModuleNames.INGESTOR,
                        extra={"reason": reason},
                    )
                )
                self.process = False
                continue
            try:
                frames = self.frames_thread.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                now = time.time()
                if should_fail_for_missing_frames(
                    last_frame_received_at=last_frame_received_at,
                    now=now,
                    timeout_seconds=self.no_frame_timeout,
                ):
                    reason = get_missing_frame_failure_reason(
                        frames_thread_alive=self.frames_thread.is_alive(),
                        timeout_seconds=self.no_frame_timeout,
                    )
                    logger.error(reason, extra={"task": self.name})
                    self.status_publisher.publish(
                        StatusMessage(
                            status=Status.ERROR,
                            module=ModuleNames.INGESTOR,
                            extra={"reason": reason},
                        )
                    )
                    self.process = False
                continue
            last_frame_received_at = time.time()
            timer.time("fetch")

            if not self.run_info_published:
                try:
                    DatabaseWorker().publish_run_info(self.run_info)
                    self.run_info_published = True
                    DatabaseWorker.set_run_id(self.cfg.run_id)
                except Exception:
                    logger.exception(
                        "Failed to publish run info", extra={"task": self.name}
                    )
                    self.status_publisher.publish(
                        StatusMessage(
                            status=Status.ERROR,
                            module=ModuleNames.INGESTOR,
                            extra={"reason": "failed to persist run metadata"},
                        )
                    )
                    self.process = False
                    continue
                
            if not self.run_logging_activated:
                set_run_logging(self.cfg, module_name=ModuleNames.INGESTOR)
                logger.info("Activated run logging", extra={"task": self.name})
                self.run_logging_activated = True

            if time.time() - last_frame_update > FRAME_UPDATE_INTERVAL:
                self.status_publisher.publish(
                    StatusMessage(
                        status=Status.INFO,
                        module=ModuleNames.INGESTOR,
                        extra={
                            "frame_id": frames.frame_id,
                            "total_frames": self.capture.total_frames,
                        },
                    )
                )
                last_frame_update = time.time()
            current_time = time.time()
            if current_time - last_metrics_update > FRAME_UPDATE_INTERVAL:
                self.status_publisher.publish(
                    StatusMessage(
                        status=Status.INFO,
                        module=ModuleNames.INGESTOR,
                        extra={
                            "queue_depths": {
                                "frames_thread": self.frames_thread.queue.qsize(),
                                "output_thread": self.output_thread.queue.qsize(),
                                "downstream_max": self.output_thread.get_limiting_queue_length(),
                            },
                            "backpressure": summarize_queue_backpressure(
                                {
                                    "frames_thread": self.frames_thread.queue.qsize(),
                                    "output_thread": self.output_thread.queue.qsize(),
                                    "downstream_max": self.output_thread.get_limiting_queue_length(),
                                }
                            ),
                        },
                    )
                )
                last_metrics_update = current_time

            timer.mark()
            tracker_inputs, detections = self.detector(frames)
            timer.time("detect")

            for frame, cam_tracker_inputs, cam_dets in zip(frames.frames, tracker_inputs, detections):
                frame.tracker_inputs = cam_tracker_inputs
                frame.detections = cam_dets

            self.output_thread.queue.put(frames)

            timer.mark()
            while self.output_thread.get_limiting_queue_length() > 5:
                time.sleep(SHORT_SLEEP)
            timer.time("wait")

            timer.loop()

        self.frames_thread.stop()
        self.capture.stop()
        self.output_thread.stop()
        self.frames_thread.join()
        self.capture.join()
        self.output_thread.join()
        if torch is not None:
            try:
                torch.cuda.empty_cache()
            except Exception:
                logger.exception(
                    "Failed to empty torch cuda cache", extra={"task": self.name}
                )
        logger.debug("Stopped", extra={"task": self.name})

    def stop(self):
        logger.debug("Stopping", extra={"task": self.name})
        self.process = False


if __name__ == "__main__":
    run_command_listener(ModuleNames.INGESTOR, Ingestor)
