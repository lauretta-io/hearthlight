import queue
import time
import os
import math
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
from ..shared.utils.queueing import DROP_OLDEST, bounded_put
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


def _resolve_process_every_n_frames(camera: dict, *, input_max_fps: float | int | None) -> int:
    if str(camera.get("source_kind") or "").strip().lower() == "video_upload":
        return max(1, int(camera.get("process_every_n_frames", 1) or 1))
    frame_processing_mode = str(camera.get("frame_processing_mode") or "frame_skip").strip().lower()
    if frame_processing_mode == "target_frame_rate":
        target_frame_rate = float(camera.get("target_frame_rate") or 0)
        effective_input_fps = float(input_max_fps or 0)
        if target_frame_rate > 0 and effective_input_fps > 0:
            return max(1, int(math.ceil(effective_input_fps / target_frame_rate)))
    return max(1, int(camera.get("process_every_n_frames", 1) or 1))


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
                cam_id: _resolve_process_every_n_frames(
                    camera,
                    input_max_fps=cfg.input.max_fps,
                )
                for cam_id, camera in cfg.input.cameras.items()
            }
            self.seen_frame_counts = {cam_id: 0 for cam_id in cfg.input.cameras}
            self.processed_frame_counts = {cam_id: 0 for cam_id in cfg.input.cameras}
            self.skipped_frame_counts = {cam_id: 0 for cam_id in cfg.input.cameras}
            self.source_runtime_stats = {
                cam_id: {
                    "capture_started_at": time.time(),
                    "processed_started_at": time.time(),
                    "last_capture_frame_id": 0,
                    "last_processed_frame_id": 0,
                }
                for cam_id in cfg.input.cameras
            }
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
                os.environ.get("HEARTHLIGHT_DETECTOR_TIMEOUT_SECONDS", "120")
            )
            self.backpressure_max = max(
                1,
                int(os.environ.get("HEARTHLIGHT_INGESTOR_BACKPRESSURE_MAX", "15")),
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

    def _queue_metrics_extra(self) -> dict:
        return {
            "queue_depths": {
                "frames_thread": self.frames_thread.queue.qsize(),
                "downstream_max": self.output_thread.get_limiting_queue_length(),
                **self.output_thread.get_queue_metrics(),
            },
            "backpressure": summarize_queue_backpressure({
                "frames_thread": self.frames_thread.queue.qsize(),
                "downstream_max": self.output_thread.get_limiting_queue_length(),
                **self.output_thread.get_queue_metrics(),
            }),
        }

    def _publish_frame_status_if_due(
        self,
        last_frame_update: float,
        extra: dict | None = None,
    ) -> float:
        """Heartbeat-publish the most recent frame_id so the dashboard keeps moving
        even while a single frame is still draining through the detector / output
        pipeline. Returns the updated timestamp of the last status publish.
        """
        if self.last_frame_id is None:
            return last_frame_update
        now = time.time()
        if now - last_frame_update <= FRAME_UPDATE_INTERVAL:
            return last_frame_update
        payload = {
            "frame_id": self.last_frame_id,
            "total_frames": self.capture.total_frames,
        }
        if extra:
            payload.update(extra)
        self.status_publisher.publish(
            StatusMessage(
                status=Status.INFO,
                module=ModuleNames.INGESTOR,
                extra=payload,
            )
        )
        return now

    def _wait_for_backpressure(self, last_frame_update: float) -> float:
        while (
            self.output_thread.get_limiting_queue_length() > self.backpressure_max
            and self.process
        ):
            last_frame_update = self._publish_frame_status_if_due(
                last_frame_update,
                extra={
                    "processing_phase": "downstream_backpressure",
                    "downstream_backpressure": self.output_thread.get_limiting_queue_length(),
                    **self._queue_metrics_extra(),
                },
            )
            time.sleep(SHORT_SLEEP)
        return last_frame_update

    def _infer_with_timeout(self, subset_frames: Frames, last_frame_update: float) -> tuple:
        frame_count = len(subset_frames.frames)
        if frame_count == 0:
            tracker_inputs, detections = self._empty_detector_outputs(0)
            return tracker_inputs, detections, last_frame_update
        if self.detector_disabled:
            tracker_inputs, detections = self._empty_detector_outputs(frame_count)
            return tracker_inputs, detections, last_frame_update

        future = self.detector_executor.submit(self.detector, subset_frames)
        deadline = time.time() + self.detector_timeout_seconds
        try:
            while not future.done():
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                last_frame_update = self._publish_frame_status_if_due(
                    last_frame_update,
                    extra={
                        "processing_phase": "detecting",
                        "processing_frame_id": subset_frames.frame_id,
                        **self._queue_metrics_extra(),
                    },
                )
                time.sleep(min(0.5, max(0.05, remaining)))
            tracker_inputs, detections = future.result(
                timeout=max(0.05, deadline - time.time())
            )
            return tracker_inputs, detections, last_frame_update
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
            tracker_inputs, detections = self._empty_detector_outputs(frame_count)
            return tracker_inputs, detections, last_frame_update
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
            tracker_inputs, detections = self._empty_detector_outputs(frame_count)
            return tracker_inputs, detections, last_frame_update

    def run(self):
        logger.info("Starting", extra={"task": self.name})

        self.process = True
        self.output_thread.start()
        self.frames_thread.start()

        if self.capture.total_frames:
            self.status_publisher.publish(
                StatusMessage(
                    status=Status.INFO,
                    module=ModuleNames.INGESTOR,
                    extra={
                        "frame_id": 0,
                        "total_frames": self.capture.total_frames,
                    },
                )
            )

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
                source_runtime_details = {}
                for cam_id, stats in self.source_runtime_stats.items():
                    camera_cfg = self.cfg.input.cameras.get(cam_id, {})
                    capture_elapsed = max(
                        current_time - float(stats.get("capture_started_at") or current_time),
                        1e-6,
                    )
                    processed_elapsed = max(
                        current_time - float(stats.get("processed_started_at") or current_time),
                        1e-6,
                    )
                    source_template_id = camera_cfg.get("source_template_id")
                    if source_template_id is None:
                        continue
                    source_runtime_details[str(source_template_id)] = {
                        "camera_id": cam_id,
                        "capture_fps": round(self.seen_frame_counts.get(cam_id, 0) / capture_elapsed, 2),
                        "processed_fps": round(self.processed_frame_counts.get(cam_id, 0) / processed_elapsed, 2),
                        "processed_frames": self.processed_frame_counts.get(cam_id, 0),
                        "skipped_frames": self.skipped_frame_counts.get(cam_id, 0),
                        "process_every_n_frames": self.process_every_n_frames.get(cam_id, 1),
                        "frame_processing_mode": str(camera_cfg.get("frame_processing_mode") or "frame_skip"),
                        "source_kind": camera_cfg.get("source_kind"),
                    }
                self.status_publisher.publish(
                    StatusMessage(
                        status=Status.INFO,
                        module=ModuleNames.INGESTOR,
                        extra={
                            "queue_depths": {
                                "frames_thread": self.frames_thread.queue.qsize(),
                                "downstream_max": self.output_thread.get_limiting_queue_length(),
                                **self.output_thread.get_queue_metrics(),
                            },
                            "backpressure": summarize_queue_backpressure({
                                "frames_thread": self.frames_thread.queue.qsize(),
                                "downstream_max": self.output_thread.get_limiting_queue_length(),
                                **self.output_thread.get_queue_metrics(),
                            }),
                            "drop_counts": {
                                "frames_thread": int(getattr(self.frames_thread, "frames_dropped", 0)),
                                **self.output_thread.get_drop_metrics(),
                            },
                            "sources": source_runtime_details,
                        },
                    )
                )
                last_metrics_update = current_time

            timer.mark()
            frame_subset = []
            subset_indexes = []
            for index, frame in enumerate(frames.frames):
                skip_value = self.process_every_n_frames.get(frame.cam_id, 1)
                self.seen_frame_counts[frame.cam_id] = self.seen_frame_counts.get(frame.cam_id, 0) + 1
                self.source_runtime_stats[frame.cam_id]["last_capture_frame_id"] = frames.frame_id
                if ((self.seen_frame_counts[frame.cam_id] - 1) % skip_value) == 0:
                    self.processed_frame_counts[frame.cam_id] = self.processed_frame_counts.get(frame.cam_id, 0) + 1
                    self.source_runtime_stats[frame.cam_id]["last_processed_frame_id"] = frames.frame_id
                    frame_subset.append(frame)
                    subset_indexes.append(index)
                else:
                    self.skipped_frame_counts[frame.cam_id] = self.skipped_frame_counts.get(frame.cam_id, 0) + 1
                    frame.tracker_inputs = None
                    frame.detections = []
            if frame_subset:
                subset_frames = Frames(frame_id=frames.frame_id, frames=frame_subset)
                subset_tracker_inputs, subset_detections, last_frame_update = self._infer_with_timeout(
                    subset_frames,
                    last_frame_update,
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

            try:
                DatabaseWorker().publish_detector_logs(frame_subset, frames.frame_id)
            except Exception:
                logger.exception("Failed to publish detector model logs", extra={"task": self.name})

            inserted, dropped_existing = bounded_put(
                self.output_thread.queue,
                frames,
                overflow_policy=DROP_OLDEST,
            )
            if dropped_existing or not inserted:
                self.output_thread.frames_dropped += 1

            timer.mark()
            last_frame_update = self._wait_for_backpressure(last_frame_update)
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
