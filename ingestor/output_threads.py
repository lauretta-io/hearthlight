import queue
import math
import uuid
from threading import Thread
import os
import logging
from collections import deque

import cv2
import numpy as np

from .models import FeatureExtractor, PoseDetector, Tracker, AnomalyDescriber

from ..shared.rabbit_messenger import (
    GunPublisher,
    TrackPublisher,
    FrameInfoPublisher,
    AnomalyPublisher,
    AnnotationMessage,
    get_annotation_message_consumer,
)
from ..shared.utils.bbox import crop_image, draw_bbox
from ..shared.database.database_worker import DatabaseWorker
from ..shared.utils.config import get_tasks
from ..shared.utils.file_retention import prune_directory_files
from ..shared.utils.queueing import DROP_NEWEST, DROP_OLDEST, bounded_put
from ..shared.utils.timer import LoopTimer
from ..shared.models.DataModels import Frames, Frame, AnomalyEvent, AnomalyEvents, AssetReference
from ..shared.constants import (
    QUEUE_TIMEOUT,
    REID_CLASSES,
    FPS_INTERVAL,
    ANOMALY_EVAL_INTERVAL,
    FRAME_UPDATE_INTERVAL,
    Tasks,
    DetectorClasses,
)

logger = logging.getLogger(__name__)
OUTPUT_QUEUE_MAX = int(os.environ.get("HEARTHLIGHT_OUTPUT_QUEUE_MAX", "12"))
WORKER_QUEUE_MAX = int(os.environ.get("HEARTHLIGHT_WORKER_QUEUE_MAX", "12"))
CLIP_WRITER_QUEUE_MAX = int(os.environ.get("HEARTHLIGHT_ANOMALY_CLIP_QUEUE_MAX", "24"))
ANOMALY_CLIP_RETAIN_MAX = int(os.environ.get("HEARTHLIGHT_ANOMALY_CLIP_RETAIN_MAX", "500"))
FRAME_RETAIN_MAX = int(os.environ.get("HEARTHLIGHT_FRAME_RETAIN_MAX", "5000"))
ANNOTATED_SEGMENT_RETAIN_MAX = int(os.environ.get("HEARTHLIGHT_ANNOTATED_SEGMENT_RETAIN_MAX", "200"))


def _write_anomaly_clip(frames, path, fps):
    if not frames:
        return
    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (w, h))
    for frame in frames:
        writer.write(frame)
    writer.release()
    logger.debug(f"Anomaly clip written: {path}")


class AnomalyClipWriter(Thread):
    def __init__(self, path: str, fps: float):
        super().__init__(name="AnomalyClipWriter", daemon=True)
        self.path = path
        self.fps = fps
        self.process = False
        self.queue = queue.Queue(maxsize=max(1, CLIP_WRITER_QUEUE_MAX))
        self.clips_dropped = 0

    def run(self):
        self.process = True
        while self.process:
            try:
                frames, output_path = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            try:
                _write_anomaly_clip(frames, output_path, self.fps)
                prune_directory_files(self.path, max_files=ANOMALY_CLIP_RETAIN_MAX)
            except Exception:
                logger.exception("Failed to write anomaly clip", extra={"task": self.name})

    def enqueue(self, frames, output_path: str):
        inserted, dropped_existing = bounded_put(
            self.queue,
            (frames, output_path),
            overflow_policy=DROP_OLDEST,
        )
        if dropped_existing or not inserted:
            self.clips_dropped += 1

    def stop(self):
        self.process = False


class OutputThread(Thread):
    def __init__(self, cfg, cameras):
        super().__init__(name=self.__class__.__name__)
        logger.debug("Initializing", extra={"task": self.name})

        self.process = False
        self.queue = queue.Queue(maxsize=max(1, OUTPUT_QUEUE_MAX))
        self.frames_dropped = 0

        task_threads = {
            Tasks.PERSON: FeatureExtractorThread,
            Tasks.GUN: GunThread,
            "write_annotated": AnnotationWriter,
            "write_frames": FrameWriter,
        }

        self.threads = {}

        cfg_tasks = get_tasks(cfg)
        self.tasks = {Tasks.PERSON}
        for task in cfg_tasks:
            self.tasks.add(task)
        if cfg.output.video.save_annotated:
            self.tasks.add("write_annotated")
        if cfg.output.visualize.show_vid:
            self.tasks.add("write_annotated")
        if cfg.output.frames.save_frames:
            self.tasks.add("write_frames")

        for task in self.tasks:
            if task in task_threads:
                self.threads[task] = task_threads[task](cfg, cameras)

        if cfg.get("anomaly") is not None:
            self.threads["anomaly"] = AnomalyDetectorThread(cfg, cameras)

        logger.debug("Initialized", extra={"task": self.name})

    def run(self):
        logger.debug("Starting", extra={"task": self.name})

        self.process = True
        for _, thread in self.threads.items():
            thread.start()

        while self.process:
            try:
                frames = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            for _, thread in self.threads.items():
                inserted, dropped_existing = bounded_put(
                    thread.queue,
                    frames,
                    overflow_policy=DROP_OLDEST,
                )
                if dropped_existing or not inserted:
                    self.frames_dropped += 1

        for _, thread in self.threads.items():
            thread.stop()
        for _, thread in self.threads.items():
            thread.join()
        logger.debug("Stopped", extra={"task": self.name})

    def get_limiting_queue_length(self):
        monitored = {*REID_CLASSES, Tasks.GUN, "write_annotated", "anomaly"}
        lens = [
            self.threads[task].queue.qsize()
            for task in self.tasks
            if task in monitored and task in self.threads
        ]
        writer = self.threads.get("write_annotated")
        if writer is not None:
            lens.append(writer.get_max_worker_queue_depth())
        return max(lens) if lens else 0

    def get_queue_metrics(self):
        metrics = {
            "output_thread": self.queue.qsize(),
        }
        for task, thread in self.threads.items():
            metrics[f"{task}_queue"] = thread.queue.qsize()
        writer = self.threads.get("write_annotated")
        if writer is not None:
            metrics["annotated_worker_max_queue"] = writer.get_max_worker_queue_depth()
        return metrics

    def get_drop_metrics(self):
        metrics = {
            "output_thread": int(self.frames_dropped),
        }
        for task, thread in self.threads.items():
            for field_name in ("frames_dropped", "clips_dropped"):
                if hasattr(thread, field_name):
                    metrics[f"{task}_{field_name}"] = int(getattr(thread, field_name))
        writer = self.threads.get("write_annotated")
        if writer is not None:
            metrics["annotated_worker_frames_dropped"] = writer.get_total_dropped_frames()
        return metrics

    def stop(self):
        logger.debug("Stopping", extra={"task": self.name})
        self.process = False


class AnomalyDetectorThread(Thread):
    def __init__(self, cfg, cameras):
        super().__init__(name=self.__class__.__name__)
        logger.debug("Initializing", extra={"task": self.name})
        self.process = False
        self.queue = queue.Queue(maxsize=max(1, WORKER_QUEUE_MAX))
        self.frames_dropped = 0
        self.track_frames = {}
        self.track_time = {}
        self.cam_last_eval = {}
        self.camera_runtime = {}
        self.eval_interval = cfg.anomaly.get("eval_interval", ANOMALY_EVAL_INTERVAL)
        self.frame_update_interval = cfg.anomaly.get("frame_update_interval", FRAME_UPDATE_INTERVAL)
        for camera in cameras:
            cam_id = camera.cam_id
            self.track_frames[cam_id] = deque(maxlen=30)
            self.track_time[cam_id] = 0
            self.cam_last_eval[cam_id] = None
            self.camera_runtime[cam_id] = {
                "source_id": getattr(camera, "source_template_id", None),
                "stage_1_model_key": getattr(camera, "anomaly_stage_1_model_key", None),
                "stage_2_model_key": getattr(camera, "anomaly_stage_2_model_key", None),
            }
        self.anomaly_detector = AnomalyDescriber(cfg)
        self.anomaly_publisher = AnomalyPublisher()
        self.database_worker = DatabaseWorker()
        self.anomaly_video_dir = cfg.output.video.get("anomaly_path")
        self.anomaly_video_fps = cfg.output.video.fps
        if self.anomaly_video_dir is not None:
            os.makedirs(self.anomaly_video_dir, exist_ok=True)
            self.clip_writer = AnomalyClipWriter(self.anomaly_video_dir, self.anomaly_video_fps)
        else:
            self.clip_writer = None
        logger.debug("Initialized", extra={"task": self.name})

    def run(self):
        logger.debug("Starting", extra={"task": self.name})
        self.process = True
        if self.clip_writer is not None:
            self.clip_writer.start()

        timer = LoopTimer(log_interval=FPS_INTERVAL, task=self.name, abbrev="anom.")
        timer.start()

        while self.process:
            try:
                frames = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            timer.time("fetch")

            timer.mark()
            for frame in frames.frames:
                cam_id = frame.cam_id
                if frame.timestamp - self.track_time[cam_id] >= self.frame_update_interval:
                    self.track_time[cam_id] = frame.timestamp
                    self.track_frames[cam_id].append(frame.array)
                    if (
                        (self.cam_last_eval[cam_id] is None and len(self.track_frames[cam_id]) >= self.eval_interval)
                        or (self.cam_last_eval[cam_id] is not None and frame.timestamp - self.cam_last_eval[cam_id] >= self.eval_interval)
                    ):
                        self.cam_last_eval[cam_id] = frame.timestamp
                        runtime_details = self.camera_runtime.get(cam_id, {})
                        anomaly_detected, score, scene_summary, anomaly_category = self.anomaly_detector(list(self.track_frames[cam_id])[-self.eval_interval:])
                        if anomaly_detected:
                            anomaly_category = "suspicious activity" if anomaly_category == "" else anomaly_category
                            event = AnomalyEvent(
                                event_id=str(uuid.uuid4()),
                                source_id=runtime_details.get("source_id"),
                                camera_id=cam_id,
                                frame_id=frames.frame_id,
                                model_key=runtime_details.get("stage_2_model_key") or self.anomaly_detector.vllm_agent.__class__.__name__,
                                stage_1_model_key=runtime_details.get("stage_1_model_key"),
                                stage_2_model_key=runtime_details.get("stage_2_model_key"),
                                category=anomaly_category,
                                score=score,
                                title=anomaly_category,
                                reasoning=scene_summary,
                            )
                            self.anomaly_publisher.publish_events(
                                AnomalyEvents(frame_id=frames.frame_id, events=[event])
                            )
                            self.database_worker.publish_anomaly_data([event])
                            if self.clip_writer is not None:
                                clip_frames = list(self.track_frames[cam_id])[-self.eval_interval:]
                                path = os.path.join(self.anomaly_video_dir, f"{event.event_id}.mp4")
                                self.clip_writer.enqueue(clip_frames, path)
                        else:
                            self.database_worker.publish_anomaly_evaluation_log(
                                source_id=runtime_details.get("source_id"),
                                camera_id=cam_id,
                                frame_id=frames.frame_id,
                                stage_1_model_key=runtime_details.get("stage_1_model_key"),
                                stage_2_model_key=runtime_details.get("stage_2_model_key"),
                                score=score,
                                category=anomaly_category,
                                reasoning=scene_summary,
                                promoted=False,
                            )

            timer.time("eval")
            timer.loop()

        if self.clip_writer is not None:
            self.clip_writer.stop()
            self.clip_writer.join(timeout=5)
            self.frames_dropped += self.clip_writer.clips_dropped

    def stop(self):
        logger.debug("Stopping", extra={"task": self.name})
        self.process = False


class FeatureExtractorThread(Thread):
    def __init__(self, cfg, cameras):
        super().__init__(name=self.__class__.__name__)
        logger.debug("Initializing", extra={"task": self.name})
        self.process = False
        self.queue = queue.Queue(maxsize=max(1, WORKER_QUEUE_MAX))
        self.frames_dropped = 0
        self.task_cams = [camera.cam_id for camera in cameras if self.check_cam(camera)]

        self.tracker = Tracker(cfg.tracking, self.task_cams)

        self.feature_extractor = FeatureExtractor(cfg.feature_extractor)
        self.track_publisher = TrackPublisher()
        self.frame_info_publisher = FrameInfoPublisher()

        self.pose = PoseDetector(cfg) if cfg.pose.enable else None

        logger.debug("Initialized", extra={"task": self.name})

    def check_cam(self, camera):
        for task in REID_CLASSES:
            if task in camera.tasks:
                return True

    def run(self):
        logger.debug("Starting", extra={"task": self.name})

        self.process = True
        timer = LoopTimer(log_interval=FPS_INTERVAL, task=self.name, abbrev="feat.")
        timer.start()

        while self.process:
            try:
                frames = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            timer.time("fetch")

            frame_id = frames.frame_id
            frame_list = frames.get_frames(self.task_cams)
            if not frame_list:
                continue

            timer.mark()
            dets = []
            crops = []
            for frame in frame_list:
                if frame.tracker_inputs is None:
                    # Detector output can be temporarily unavailable for a frame;
                    # skip it instead of crashing the worker thread.
                    continue
                cam_crops = []
                dets.append(frame.tracker_inputs)
                for det in frame.tracker_inputs:
                    cam_crops.append(crop_image(det[0:4], frame.array))
                crops.append(cam_crops)
            if not dets:
                continue
            timer.time("crop")

            features = self.feature_extractor.extract_frames(crops)
            timer.time("feature")

            tracks = self.tracker.update(dets, features, frame_list, frame_id)
            timer.time("track")

            if self.pose:
                tracks = self.pose(frames, tracks)
                timer.time("pose")

            all_tracks = []
            for frame, cam_tracks in zip(frame_list, tracks):
                frame.tracks = cam_tracks
                all_tracks.extend(cam_tracks)

            self.track_publisher.publish_frame(all_tracks, frame_id)
            self.frame_info_publisher.publish_frame(frames)
            timer.time("publish")

            timer.loop()

        self.track_publisher.close(clear_queue=True)
        self.frame_info_publisher.close(clear_queue=True)
        logger.debug("Stopped", extra={"task": self.name})

    def stop(self):
        logger.debug("Stopping", extra={"task": self.name})
        self.process = False


class GunThread(Thread):
    def __init__(self, cfg, cameras):
        super().__init__(name=self.__class__.__name__)
        logger.debug("Initializing", extra={"task": self.name})
        self.process = False
        self.publisher = GunPublisher()
        self.queue = queue.Queue(maxsize=max(1, WORKER_QUEUE_MAX))
        self.frames_dropped = 0
        self.task_cams = [
            camera.cam_id for camera in cameras if Tasks.GUN in camera.tasks
        ]
        logger.debug("Initialized", extra={"task": self.name})

    def run(self):
        logger.debug("Starting", extra={"task": self.name})

        self.process = True
        timer = LoopTimer(log_interval=FPS_INTERVAL, task=self.name, abbrev="gun")
        timer.start()

        while self.process:
            try:
                frames = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            timer.time("fetch")

            detections = [
                det
                for frame in frames.get_frames(self.task_cams)
                for det in frame.detections
                if det.clss == DetectorClasses.GUN
            ]
            self.publisher.publish_frame(detections, frames.frame_id)
            timer.time("publish")

            timer.loop()

        self.publisher.close(clear_queue=True)
        logger.debug("Stopped", extra={"task": self.name})

    def stop(self):
        logger.debug("Stopping", extra={"task": self.name})
        self.process = False


class FrameWriter(Thread):
    def __init__(self, cfg, cameras):
        super().__init__(name=self.__class__.__name__)
        logger.debug("Initializing", extra={"task": self.name})
        self.process = False
        self.queue = queue.Queue(maxsize=max(1, WORKER_QUEUE_MAX))
        self.frames_dropped = 0
        self.database_worker = DatabaseWorker()
        self.last_save = {camera.cam_id: float("-inf") for camera in cameras}
        self.save_interval = cfg.output.frames.save_interval
        self.directory = cfg.output.frames.frame_dir
        self.ext = cfg.output.frames.image_ext
        if cfg.output.frames.size is not None:
            self.resize = True
            self.frame_size = (cfg.output.frames.size[0], cfg.output.frames.size[1])
        else:
            self.resize = False
        os.makedirs(self.directory)
        logger.debug("Initialized", extra={"task": self.name})

    def run(self):
        logger.debug("Starting", extra={"task": self.name})
        self.process = True

        while self.process:
            try:
                frames = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue

            saved_frames = []
            for frame in frames.frames:
                cam_id = frame.cam_id
                timestamp = frame.timestamp
                if timestamp - self.last_save[cam_id] > self.save_interval:
                    filename = f"{cam_id}_{timestamp}{self.ext}"
                    path = os.path.join(self.directory, filename)
                    image = frame.array
                    if self.resize:
                        image = cv2.resize(image, self.frame_size)
                    cv2.imwrite(path, image)
                    frame.save_path = path
                    saved_frames.append(frame)

                    if timestamp - self.last_save[cam_id] > self.save_interval:
                        self.last_save[cam_id] = timestamp

            self.database_worker.publish_frames(saved_frames, frames.frame_id)
            if saved_frames:
                prune_directory_files(self.directory, max_files=FRAME_RETAIN_MAX)

        logger.debug("Stopped", extra={"task": self.name})

    def stop(self):
        logger.debug("Stopping", extra={"task": self.name})
        self.process = False


WRITER_WORKER_MAX_QUEUE = 30


class WriterWorker(Thread):
    def __init__(self, cfg, path, id):
        super().__init__(name=self.__class__.__name__ + f" for {id}")
        logger.debug("Initializing", extra={"task": self.name})
        self.process = False
        self.base_path = path
        self.queue = queue.Queue(maxsize=WRITER_WORKER_MAX_QUEUE)
        self.writer = None
        self.fps = cfg.output.video.fps
        self.segment_frames = max(1, int(os.environ.get("HEARTHLIGHT_ANNOTATED_SEGMENT_FRAMES", str(int(self.fps * 300)))))
        self.segment_index = 0
        self.frames_written_in_segment = 0
        self.output_dir = os.path.dirname(path)
        self.output_prefix = os.path.splitext(os.path.basename(path))[0]
        self.frames_dropped = 0
        logger.debug("Initialized", extra={"task": self.name})

    def run(self):
        logger.debug("Starting", extra={"task": self.name})
        self.process = True

        while self.process:
            try:
                frame, num_saves = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            if self.writer is None:
                self.writer = self.get_writer(frame)
            for _ in range(num_saves):
                if self.frames_written_in_segment >= self.segment_frames:
                    self.rotate_writer(frame)
                self.writer.write(frame)
                self.frames_written_in_segment += 1

        if self.writer is not None:
            self.writer.release()
        logger.debug("Stopped", extra={"task": self.name})

    def get_writer(self, frame):
        size = frame.shape[1], frame.shape[0]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        return cv2.VideoWriter(self._current_segment_path(), fourcc, self.fps, size)

    def _current_segment_path(self):
        return os.path.join(
            self.output_dir,
            f"{self.output_prefix}_segment_{self.segment_index:05d}.mp4",
        )

    def rotate_writer(self, frame):
        if self.writer is not None:
            self.writer.release()
        self.segment_index += 1
        self.frames_written_in_segment = 0
        self.writer = self.get_writer(frame)
        prune_directory_files(self.output_dir, max_files=ANNOTATED_SEGMENT_RETAIN_MAX)

    def stop(self):
        logger.debug("Stopping", extra={"task": self.name})
        self.process = False


class AnnotationWriter(Thread):
    def __init__(self, cfg, cameras):
        super().__init__(name=self.__class__.__name__)
        logger.debug("Initializing", extra={"task": self.name})
        self.process = False
        self.queue = queue.Queue(maxsize=max(1, WORKER_QUEUE_MAX))
        self.frames_dropped = 0
        self.cam_ids = [camera.cam_id for camera in cameras]
        self.last_timestamps: dict[int, float | None] = {
            cam_id: None for cam_id in self.cam_ids
        }
        self.num_frames = {cam_id: 1 for cam_id in self.cam_ids}
        self.buffer_length = cfg.input.record_buf_len
        self.label_id = cfg.output.visualize.labels.id
        self.label_clss = cfg.output.visualize.labels.clss

        self.consumer = get_annotation_message_consumer()

        self.write = cfg.output.video.save_annotated
        if self.write:
            self.fps = cfg.output.video.fps
            dir = cfg.output.video.annotated_path
            os.makedirs(dir, exist_ok=True)
            self.workers = {
                cam_id: WriterWorker(
                    cfg,
                    os.path.join(dir, f"cam{cam_id}.mp4"),
                    f"annotated-{cam_id}",
                )
                for cam_id in self.cam_ids
            }
            # self.zone_illustrator = ZoneAssigner(cfg.input, cfg.camera_reid_zones)

        self.show = cfg.output.visualize.show_vid
        if self.show:
            self.mosaic = cfg.output.visualize.mosaic
            self.rows, self.cols, self.size, empty = self.get_grid(cfg)
            self.num_mosaics = math.ceil(
                len(self.cam_ids) / cfg.output.visualize.max_per_window
            )
            self.empty_frames = [empty] * (len(self.cam_ids) % (self.rows * self.cols))

        logger.debug("Initialized", extra={"task": self.name})

    def run(self):
        logger.debug("Starting", extra={"task": self.name})

        self.process = True
        self.consumer.start()
        if self.write:
            for worker in self.workers.values():
                worker.start()

        frames = None

        while self.process:
            while frames is None:
                try:
                    frames = self.queue.get(timeout=QUEUE_TIMEOUT)
                except queue.Empty:
                    continue

            try:
                reid_frame_id, reid_message = self.consumer.queue.get(
                    timeout=QUEUE_TIMEOUT
                )
            except queue.Empty:
                while self.queue.qsize() > self.buffer_length:
                    try:
                        frames = self.queue.get(timeout=QUEUE_TIMEOUT)
                    except queue.Empty:
                        break
                    self.show_and_write(frames, AnnotationMessage())
                continue

            if frames.frame_id > reid_frame_id:
                # Drain stale backed-up reid messages in bulk instead of one per iteration
                while reid_frame_id < frames.frame_id:
                    try:
                        reid_frame_id, reid_message = self.consumer.queue.get_nowait()
                    except queue.Empty:
                        break
                if frames.frame_id > reid_frame_id:
                    logger.warning(
                        f"Frame {frames.frame_id} still ahead of reid {reid_frame_id}, showing without annotations",
                        extra={"task": self.name},
                    )
                    self.show_and_write(frames, AnnotationMessage())
                    continue
            while frames.frame_id < reid_frame_id:
                try:
                    frames = self.queue.get(timeout=QUEUE_TIMEOUT)
                except queue.Empty:
                    continue

            self.show_and_write(frames, reid_message)

        self.consumer.stop(clear_queues=True)
        self.consumer.join()
        if self.show:
            try:
                cv2.destroyAllWindows()
                cv2.waitKey(1)
            except cv2.error:
                logger.warning(
                    "Failed to close preview windows during shutdown",
                    extra={"task": self.name},
                    exc_info=True,
                )
        if self.write:
            for _, worker in self.workers.items():
                worker.stop()
            for _, worker in self.workers.items():
                worker.join()
        logger.debug("Stopped", extra={"task": self.name})

    def show_and_write(self, frames: Frames, reid_message: AnnotationMessage):
        id_map = self.get_id_map(reid_message)
        images = [self.annotate(frame, id_map) for frame in frames.frames]

        if self.write:
            for image, frame in zip(images, frames.frames):
                cam_id = frame.cam_id
                timestamp = frame.timestamp
                last_timestamp = self.last_timestamps[cam_id]
                if last_timestamp is not None:
                    self.num_frames[cam_id] += self.fps * (timestamp - last_timestamp)
                self.last_timestamps[cam_id] = timestamp
                saves = int(self.num_frames[cam_id])
                if saves >= 0:
                    # annotated_frame = self.zone_illustrator.draw(annotated_frame, cam_id)
                    inserted, dropped_existing = bounded_put(
                        self.workers[cam_id].queue,
                        (image, saves),
                        overflow_policy=DROP_OLDEST,
                    )
                    if dropped_existing or not inserted:
                        self.workers[cam_id].frames_dropped += 1
                        logger.warning(
                            f"WriterWorker queue full for cam {cam_id}, dropping frame",
                            extra={"task": self.name},
                        )
                    self.num_frames[cam_id] -= saves

        if self.show:
            try:
                if self.mosaic:
                    images = [cv2.resize(image, self.size) for image in images]
                    images += self.empty_frames
                    skip = 0
                    for i in range(self.num_mosaics):
                        rows = []
                        for j in range(self.rows):
                            row_imgs = images[
                                skip + j * self.cols : skip + (j + 1) * self.cols
                            ]
                            row = cv2.hconcat(row_imgs)
                            rows.append(row)
                        mosaic = cv2.vconcat(rows)
                        mosaic = cv2.putText(
                            mosaic,
                            f"Frame {frames.frame_id}",
                            (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1,
                            (0, 0, 0),
                            2,
                            cv2.LINE_AA,
                        )
                        cv2.imshow(f"Cameras_{i}", mosaic)
                        skip += self.cols * self.rows
                else:
                    for id, cam_id in enumerate(self.cam_ids):
                        cv2.imshow(f"camera {cam_id}", images[id])
                cv2.waitKey(1)
            except cv2.error as exc:
                logger.warning(
                    "Local video display unavailable; disabling preview windows",
                    extra={"task": self.name},
                    exc_info=exc,
                )
                self.show = False

    def get_grid(self, cfg):
        max_height = cfg.output.visualize.max_height
        max_width = cfg.output.visualize.max_width
        num_cams = len(self.cam_ids)
        height = final_height = 720
        width = final_width = 1280
        max_per_window = cfg.output.visualize.max_per_window
        num_rows = num_cols = 1
        min_diff = float("inf")

        if not self.mosaic:
            return 1, 1, (height, width), None

        for rows in range(1, max(num_cams, max_per_window) + 1):
            cols = math.ceil(num_cams / rows)
            total_width = cols * width
            total_height = rows * height
            aspect_ratio = total_width / total_height
            diff = abs(aspect_ratio - max_width / max_height)
            if diff < min_diff:
                min_diff = diff
                num_rows = rows
                num_cols = cols
                final_width = total_width
                final_height = total_height

        scale = min(max_width / final_width, max_height / final_height)
        new_width = int(scale * width)
        new_height = int(scale * height)
        empty_space = np.zeros((new_height, new_width, 3), dtype=np.uint8)
        return num_rows, num_cols, (new_width, new_height), empty_space

    def annotate(self, frame: Frame, id_map: dict[int, int]):
        annotated_frame = frame.array.copy()

        ids = [id_map.get(track.track_id, "") for track in frame.tracks]
        classes = [track.clss for track in frame.tracks]
        bboxes = [track.bbox for track in frame.tracks]

        for detection in frame.detections:
            classes.append(detection.clss)
            bboxes.append(detection.bbox)
            ids.append("")

        draw_bbox(annotated_frame, bboxes, (1, 1), ids=ids, classes=classes)

        return annotated_frame

    def get_id_map(self, message: AnnotationMessage):
        reid_map = {}
        if (persons := message.get(DetectorClasses.PERSON)) is not None:
            for person in persons.track_instances:
                reid_map[person.track_id] = person.real_id
        if (bags := message.get(DetectorClasses.BAG)) is not None:
            for bag in bags.track_instances:
                reid_map[bag.track_id] = bag.real_id

        return reid_map

    def get_max_worker_queue_depth(self):
        if not self.write:
            return 0
        return max((w.queue.qsize() for w in self.workers.values()), default=0)

    def get_total_dropped_frames(self):
        if not self.write:
            return 0
        return sum(getattr(worker, "frames_dropped", 0) for worker in self.workers.values())

    def stop(self):
        logger.debug("Stopping", extra={"task": self.name})
        self.process = False
