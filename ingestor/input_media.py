import os
import queue
import time
import logging
import subprocess
from threading import Event, Lock, Thread

import cv2
import numpy as np

from ..shared.constants import SHORT_SLEEP
from ..shared.models.DataModels import Frame, Frames, CameraType
from ..shared.models.DataModels import Camera as CameraModel
from ..shared.utils.backoff import with_exponential_backoff

logger = logging.getLogger(__name__)
RECONNECT_MAX_TRIES = 5


class ConnectionState:
    DISCONNECTED = 0
    CONNECTED = 1


class FramesThread(Thread):
    def __init__(self, capture, max_queue_length=10, max_fps=None):
        super().__init__(name=self.__class__.__name__)
        self.process = False
        self.queue = queue.Queue()
        self.max_queue_length = max_queue_length

        self.capture = capture
        self.max_fps = max_fps

    def run(self):
        logger.info("Starting", extra={"task": self.name})
        self.process = True
        frame_id = 0
        start = time.time()
        while self.process:
            if self.queue.qsize() >= self.max_queue_length:
                time.sleep(SHORT_SLEEP)
                continue
            status, frame_list = self.capture.get_frames()
            if status:
                frame_id += 1
                frames = Frames(
                    frame_id=frame_id,
                    frames=frame_list,
                )
                self.queue.put(frames)

            if self.max_fps is not None:
                elapsed_time = time.time() - start
                fps = 1 / elapsed_time
                if fps > self.max_fps:
                    time.sleep(1 / self.max_fps - elapsed_time)
                start = time.time()

        logger.info("Stopped", extra={"task": self.name})

    def stop(self):
        logger.info("Stopping", extra={"task": self.name})
        self.process = False


class MultiCapture:
    def __init__(
        self,
        camera_cfg,
        resize: None | tuple[int, int] = None,
        record_dir: str | None = None,
    ):
        self.name = self.__class__.__name__
        try:
            logger.debug("Initializing", extra={"task": self.name})
            self.total_frames = None
            self.cameras = []
            self.threads = []
            self.recorders = []
            failed_ids = []
            self.resize = resize

            for cam_id, cam_cfg in camera_cfg.items():
                camera = CameraModel(cam_id=cam_id, **cam_cfg)
                self.cameras.append(camera)
                if record_dir:
                    camera.recording_path = os.path.join(
                        record_dir, f"{camera.cam_id}.mp4"
                    )
                    capture = RecorderCapture(
                        camera.cam_id,
                        camera.source,
                        camera.recording_path,
                    )
                    assert capture.recorder.start_timestamp is not None
                    camera.set_start_timestamp(capture.recorder.start_timestamp)
                else:
                    capture = Capture(camera.cam_id, camera.source)
                camera.width = capture.width
                camera.height = capture.height
                if camera.camera_type == CameraType.VIDEO_FILE:
                    thread = VideoFile(capture, camera.start_timestamp)
                    camera.total_frames = capture.frame_count
                    if (
                        self.total_frames is None
                        or capture.frame_count > self.total_frames
                    ):
                        self.total_frames = capture.frame_count
                else:
                    thread = Camera(capture)
                self.threads.append(thread)
                thread.start()
                if not capture.is_connected():
                    failed_ids.append(camera.cam_id)

            if failed_ids:
                logger.warning(
                    f"Failed to init these camera_ids: {failed_ids}, will reconnect later...",
                    extra={"task": self.name},
                )
            if not any([thread.capture.is_connected() for thread in self.threads]):
                raise Exception("No cameras are connected")

        except Exception:
            logger.exception("Failed to initialize", extra={"task": self.name})
            raise

        logger.debug("Initialized", extra={"task": self.name})

    def get_frames(self):
        status = False
        frames = []
        for thread in self.threads:
            connected, frame = thread.get_frame()
            if connected:
                status = True
            if self.resize:
                frame.resized_array = cv2.resize(frame.array, self.resize)
            frames.append(frame)
        return status, frames

    def get_num_sources(self):
        return len(self.threads)

    def stop(self):
        logger.info("Stopping", extra={"task": self.name})
        for thread in self.threads:
            thread.stop()

    def join(self):
        for thread in self.threads:
            thread.join()


class Camera(Thread):
    def __init__(self, capture):
        super().__init__(name=self.__class__.__name__ + str(capture.cam_id))
        self.capture = capture
        self.cam_id = self.capture.cam_id
        self.empty = np.zeros((640, 480, 3), dtype=np.uint8)
        self.frame_lock = Lock()
        self.process = False
        self.frame = Frame(
            cam_id=self.cam_id,
            timestamp=time.time(),
            time_delta=0,
            array=self.empty,
            status=True,
            empty=True,
        )

    def run(self):
        logger.info("Starting", extra={"task": f"Camera {self.cam_id}"})
        self.process = True
        last_frame_timestamp = None

        while self.process:
            if not self.capture.is_connected():
                self.capture.reconnect()
                continue

            ret, array = self.capture.read()
            if not ret:
                next_frame = Frame(
                    cam_id=self.cam_id,
                    timestamp=time.time(),
                    time_delta=0,
                    array=self.empty,
                    status=False,
                    empty=True,
                )
            else:
                timestamp = time.time()
                next_frame = Frame(
                    cam_id=self.cam_id,
                    timestamp=timestamp,
                    time_delta=(
                        timestamp - last_frame_timestamp
                        if last_frame_timestamp is not None
                        else 0
                    ),
                    array=array,
                    status=True,
                    empty=False,
                )
                last_frame_timestamp = timestamp
            with self.frame_lock:
                self.frame = next_frame

        self.capture.release()
        logger.info("Stopped", extra={"task": f"Camera {self.cam_id}"})

    def stop(self):
        logger.info("Stopping", extra={"task": f"Camera {self.cam_id}"})
        self.process = False

    def get_frame(self):
        status = self.capture.is_connected()
        with self.frame_lock:
            frame = self.frame.model_copy()
        return status, frame


class VideoFile(Thread):
    def __init__(self, capture, start_time=None):
        super().__init__(name=self.__class__.__name__ + str(capture.cam_id))
        self.capture = capture
        self.cam_id = self.capture.cam_id
        self.start_time = start_time if start_time else time.time()
        self.empty = np.zeros((640, 480, 3), dtype=np.uint8)
        self.frame_lock = Lock()
        self.process = False
        self.timestamp = self.start_time
        self.frame = Frame(
            cam_id=self.cam_id,
            timestamp=self.start_time,
            time_delta=0,
            array=self.empty,
            status=True,
            empty=True,
        )

    def run(self):
        logger.info("Starting", extra={"task": f"VideoFile {self.cam_id}"})
        self.process = True
        frame_number = 0
        previous_timestamp = None

        while self.process:
            with self.frame_lock:
                frame_is_pending = not self.frame.empty
            if frame_is_pending:
                time.sleep(SHORT_SLEEP)
                continue
            if not self.capture.is_connected():
                # video over
                logger.info("Video over", extra={"task": f"VideoFile {self.cam_id}"})
                break

            frame_number += 1
            self.timestamp = self.start_time + (1 / self.capture.fps * frame_number)

            ret, array = self.capture.read()
            if not ret:
                next_frame = Frame(
                    cam_id=self.cam_id,
                    timestamp=self.timestamp,
                    time_delta=0,
                    array=self.empty,
                    status=False,
                    empty=True,
                )
            else:
                next_frame = Frame(
                    cam_id=self.cam_id,
                    timestamp=self.timestamp,
                    time_delta=(
                        self.timestamp - previous_timestamp
                        if previous_timestamp is not None
                        else 0
                    ),
                    array=array,
                    status=True,
                    empty=False,
                )
                previous_timestamp = self.timestamp
            with self.frame_lock:
                self.frame = next_frame

        self.capture.release()
        logger.info("Stopped", extra={"task": f"VideoFile {self.cam_id}"})

    def stop(self):
        logger.info("Stopping", extra={"task": f"VideoFile {self.cam_id}"})
        self.process = False

    def get_frame(self):
        # the frame needs to be set to empty so that the file thread will look for
        # the next frame
        with self.frame_lock:
            frame = self.frame.model_copy()
            self.frame = Frame(
                cam_id=self.cam_id,
                timestamp=self.timestamp,
                time_delta=0,
                array=self.empty,
                status=True,
                empty=True,
            )
        return self.capture.is_connected(), frame


READ_FAILURE_THRESHOLD = 30


class Capture:
    def __init__(self, cam_id, source):
        self.name = self.__class__.__name__ + str(cam_id)
        self.cam_id = cam_id
        self.source = source
        self.connect_attempts = 0
        self.connection_status = ConnectionState.DISCONNECTED
        self._consecutive_read_failures = 0

        try:
            self.connect()
        except Exception:
            logger.exception(
                f"Failed to connect to {self.source}", extra={"task": self.name}
            )

    @with_exponential_backoff(max_tries=RECONNECT_MAX_TRIES)
    def connect(self):
        self.cap = cv2.VideoCapture()
        if isinstance(self.source, str) and self.source.lower().startswith("rtsp://"):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        if self.cap.open(self.source, cv2.CAP_FFMPEG if isinstance(self.source, str) else cv2.CAP_ANY):
            print("running cv2 for source", self.source)
            self.connection_status = ConnectionState.CONNECTED
            self.connect_attempts = 0
        else:
            self.connect_attempts += 1
            self.connection_status = ConnectionState.DISCONNECTED
            raise Exception(f"Failed to connect to {self.source}")

    def read(self):
        if not getattr(self, "cap", None):
            return False, None
        ret, array = self.cap.read()
        while not ret and self._consecutive_read_failures < READ_FAILURE_THRESHOLD:
            print("retrying cap read")
            self._consecutive_read_failures += 1
            ret, array = self.cap.read()
        if not ret:
            self._consecutive_read_failures += 1
            if self._consecutive_read_failures >= READ_FAILURE_THRESHOLD:
                self.connection_status = ConnectionState.DISCONNECTED
        else:
            self._consecutive_read_failures = 0
        return ret, array

    def reconnect(self):
        logger.warning("Not connected", extra={"task": self.name})
        self._consecutive_read_failures = 0
        self.release()
        try:
            self.connect()
            logger.info("Reconnected", extra={"task": self.name})
        except Exception:
            logger.exception("Failed to reconnect", extra={"task": self.name})

    def is_connected(self):
        return self.connection_status == ConnectionState.CONNECTED

    def release(self):
        if getattr(self, "cap", None):
            self.cap.release()

    @property
    def fps(self):
        return self.cap.get(cv2.CAP_PROP_FPS)

    @property
    def width(self):
        return int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))

    @property
    def height(self):
        return int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    @property
    def frame_count(self):
        return int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))


class RecorderCapture:
    def __init__(self, cam_id, source, record_path):
        self.name = self.__class__.__name__ + str(cam_id)
        self.cam_id = cam_id

        self.connect_attempts = 0
        self.connection_status = ConnectionState.CONNECTED

        self.recorder = Recorder(cam_id, source, record_path)
        self.width, self.height, self.fps = self.recorder.get_metadata()
        self.frame_size = self.width * self.height * 3
        self.recorder.start()

    def read(self):
        raw = self.recorder.process.stdout.read(self.frame_size)
        if not raw or len(raw) != self.frame_size:
            self.connection_status = ConnectionState.DISCONNECTED
            return False, None
        frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3))
        return True, frame.copy()

    def reconnect(self):
        return
        logger.warning("Not connected", extra={"task": self.name})
        self.release()
        try:
            self.connect()
            logger.info("Reconnected", extra={"task": self.name})
        except Exception:
            logger.exception("Failed to reconnect", extra={"task": self.name})

    def is_connected(self):
        return self.connection_status == ConnectionState.CONNECTED

    def release(self):
        self.recorder.stop()

    @property
    def frame_count(self):
        return -1


class Recorder:
    def __init__(self, cam_id, source, record_path):
        self.cam_id = cam_id
        self.source = source
        self.path = record_path

    def _is_rtsp(self):
        return isinstance(self.source, str) and self.source.lower().startswith("rtsp://")

    def get_metadata(self):
        # fmt: off
        cmd = [
            'ffprobe',
            *(['-rtsp_transport', 'tcp'] if self._is_rtsp() else []),
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate',
            '-of', 'csv=p=0',
            self.source
        ]
        # fmt: on

        result = subprocess.run(cmd, capture_output=True, text=True)
        data = result.stdout.strip().split(",")
        width, height = int(data[0]), int(data[1])

        # Parse the frame rate fraction (e.g., "30000/1001")
        fps_frac = data[2]
        if "/" in fps_frac:
            num, den = map(int, fps_frac.split("/"))
            fps = num / den
        else:
            fps = float(fps_frac)

        return width, height, fps

    def start(self):
        logger.info("Starting", extra={"task": f"Recorder {self.cam_id}"})

        output_dir = os.path.dirname(self.path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # fmt: off
        cmd = [
            'ffmpeg',
            *(['-rtsp_transport', 'tcp'] if self._is_rtsp() else []),
            '-i', self.source,                      # Input stream
            
            # Record to file 
            '-map', '0:v:0',                   # Map only the first video stream
            '-c', 'copy',                      # Copy streams without re-encoding
            '-f', 'mp4',                       # MP4 container format
            '-movflags', 'frag_keyframe+empty_moov',  # fragmented MP4, readable while being written
            self.path,                         # write to file
            
            # Raw video frames for OpenCV
            '-map', '0:v:0',                   # Map only the first video stream
            '-c:v', 'rawvideo',                # Output raw video frames
            '-pix_fmt', 'bgr24',               # Use BGR pixel format (for OpenCV)
            '-f', 'rawvideo',                  # Raw video format
            'pipe:1'                           # Output to stdout
        ]
        # fmt: on

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,  # Capture stdout for piping frames
            stderr=subprocess.PIPE,  # Capture stderr for debugging
            bufsize=10**8,  # Large buffer to prevent blocking
        )

        self.start_timestamp = None
        self._first_frame_event = Event()
        self.log_thread = Thread(target=self.log)
        self.log_thread.start()

        self._first_frame_event.wait(timeout=10)

        logger.info("Started", extra={"task": f"Recorder {self.cam_id}"})

    def log(self):
        start_markers = ["Press [q] to stop", "Output #1", "swscaler"]
        start_detected = False
        
        while True:
            line = self.process.stderr.readline()
            if not line:
                logger.warning("Recorder stderr closed", extra={"task": f"Recorder {self.cam_id}"})
                break
            
            line_str = line.decode("utf-8", errors="replace").strip()
            
            if not start_detected and any(marker in line_str for marker in start_markers):
                self.start_timestamp = time.time()
                start_detected = True
                self._first_frame_event.set()
                logger.info(f"Recording start detected: {line_str}", 
                           extra={"task": f"Recorder {self.cam_id}"})
            
            if line_str and "frame=" not in line_str and "swscaler" not in line_str:
                logger.info(line_str, extra={"task": f"Recorder {self.cam_id}"})

    def stop(self):
        if getattr(self, "process", None) is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        if getattr(self, "log_thread", None) is not None:
            self.log_thread.join(timeout=2)
