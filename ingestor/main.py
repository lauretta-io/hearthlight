import queue
import time
import os
from threading import Thread
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

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
from ..shared.models.DataModels import Frames, Run, StatusMessage, Status
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
                self.track_frames[cam_id] = deque(maxlen=30)
                self.track_time[cam_id] = 0
                self.cam_last_eval[cam_id] = None

            self.frames_thread = FramesThread(self.capture, max_fps=cfg.input.max_fps)
            self.output_thread = OutputThread(cfg, self.capture.cameras)
            self.process_every_n_frames = {
                cam_id: max(1, int(camera.get("process_every_n_frames", 1) or 1))
                for cam_id, camera in cfg.input.cameras.items()
            }
            self.processed_frame_counts = {cam_id: 0 for cam_id in cfg.input.cameras}
            self.run_info = Run(
                run_identifier=cfg.run_id,
                output_dir=cfg.output.output_dir,
                cameras=self.capture.cameras,
            )
            self.run_info_published = False
            self.run_logging_activated = False
            self.completed_normally = False
            self.no_frame_timeout = float(cfg.input.get("no_frame_timeout", 15.0))
            self.status_publisher = status_publisher
            self.detector_timeout_seconds = float(
                os.environ.get("HEARTHLIGHT_DETECTOR_TIMEOUT_SECONDS", "20")
            )
            self.detector_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="IngestorDetector",
            )
            self.detector_disabled = False
        except Exception:
            logger.exception("Failed to initialize", extra={"task": self.name})
            raise

        logger.debug("Initialized", extra={"task": self.name})

    def _empty_detector_outputs(self, frame_count: int):
        return [None] * frame_count, [[] for _ in range(frame_count)]

    def _publish_frame_status_if_due(self, last_frame_update: float) -> float:
        """Heartbeat-publish the most recent frame_id so the dashboard keeps moving
        even while a single frame is still draining through the detector / output
        pipeline. Returns the updated timestamp of the last status publish.
        """
        if self.last_frame_id is None:
            return last_frame_update
        now = time.time()
        if now - last_frame_update <= FRAME_UPDATE_INTERVAL:
            return last_frame_update
        self.status_publisher.publish(
            StatusMessage(
                status=Status.INFO,
                module=ModuleNames.INGESTOR,
                extra={
                    "frame_id": self.last_frame_id,
                    "total_frames": self.capture.total_frames,
                },
            )
        )
        return now

    def _infer_with_timeout(self, subset_frames: Frames):
        frame_count = len(subset_frames.frames)
        if frame_count == 0:
            return self._empty_detector_outputs(0)
        if self.detector_disabled:
            return self._empty_detector_outputs(frame_count)

        future = self.detector_executor.submit(self.detector, subset_frames)
        try:
            return future.result(timeout=self.detector_timeout_seconds)
        except FuturesTimeout:
            self.detector_disabled = True
            reason = (
                "detector inference timed out; disabling detector to keep stream running"
            )
            logger.error(reason, extra={"task": self.name})
            self.status_publisher.publish(
                StatusMessage(
                    status=Status.INFO,
                    module=ModuleNames.INGESTOR,
                    extra={"reason": reason},
                )
            )
            return self._empty_detector_outputs(frame_count)
        except Exception:
            self.detector_disabled = True
            reason = "detector inference failed; disabling detector to keep stream running"
            logger.exception(reason, extra={"task": self.name})
            self.status_publisher.publish(
                StatusMessage(
                    status=Status.INFO,
                    module=ModuleNames.INGESTOR,
                    extra={"reason": reason},
                )
            )
            return self._empty_detector_outputs(frame_count)

    def run(self):
        logger.info("Starting", extra={"task": self.name})

        self.process = True
        self.output_thread.start()
        self.frames_thread.start()

        last_frame_update = float("-inf")
        last_metrics_update = float("-inf")
        last_frame_received_at = time.time()
        self.last_frame_id = None
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
                if self.capture.all_file_sources_finished():
                    logger.info(
                        "All uploaded/file sources finished; stopping ingestor",
                        extra={"task": self.name},
                    )
                    self.completed_normally = True
                    self.status_publisher.publish(
                        StatusMessage(
                            status=Status.STOPPED,
                            module=ModuleNames.INGESTOR,
                            extra={
                                "reason": "file_sources_completed",
                                "frame_id": self.last_frame_id,
                                "total_frames": self.capture.total_frames,
                            },
                        )
                    )
                    self.process = False
                    continue
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
            self.last_frame_id = frames.frame_id
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

            last_frame_update = self._publish_frame_status_if_due(last_frame_update)
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
            frame_subset = []
            subset_indexes = []
            for index, frame in enumerate(frames.frames):
                skip_value = self.process_every_n_frames.get(frame.cam_id, 1)
                self.processed_frame_counts[frame.cam_id] = self.processed_frame_counts.get(frame.cam_id, 0) + 1
                if ((self.processed_frame_counts[frame.cam_id] - 1) % skip_value) == 0:
                    frame_subset.append(frame)
                    subset_indexes.append(index)
                else:
                    frame.tracker_inputs = None
                    frame.detections = []
            if frame_subset:
                subset_frames = Frames(frame_id=frames.frame_id, frames=frame_subset)
                subset_tracker_inputs, subset_detections = self._infer_with_timeout(
                    subset_frames
                )
            else:
                subset_tracker_inputs, subset_detections = [], []
            timer.time("detect")

            subset_index_lookup = {
                frame_index: subset_index
                for subset_index, frame_index in enumerate(subset_indexes)
            }
            for index, frame in enumerate(frames.frames):
                subset_index = subset_index_lookup.get(index)
                if subset_index is None:
                    continue
                frame.tracker_inputs = subset_tracker_inputs[subset_index]
                frame.detections = subset_detections[subset_index]

            self.output_thread.queue.put(frames)

            timer.mark()
            while self.output_thread.get_limiting_queue_length() > 5 and self.process:
                # Keep the status heartbeat going while we're stalled on downstream
                # backpressure, otherwise the dashboard appears stuck on the previous
                # frame_id for the entire duration of a slow processing cycle.
                last_frame_update = self._publish_frame_status_if_due(
                    last_frame_update
                )
                time.sleep(SHORT_SLEEP)
            timer.time("wait")

            timer.loop()

        self.frames_thread.stop()
        self.capture.stop()
        self.output_thread.stop()
        self.frames_thread.join()
        self.capture.join()
        self.output_thread.join()
        self.detector_executor.shutdown(wait=False, cancel_futures=True)
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
