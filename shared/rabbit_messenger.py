import os
import queue
from collections import defaultdict
import time
from threading import RLock, Thread
import logging
from functools import partial
from typing import TypeVar, Generic, Type, TypedDict, Iterable

import pika
from pika.exceptions import AMQPConnectionError, AMQPError

from .models.DataModels import (
    SystemMessage,
    StatusMessage,
    POISearch,
    Frames,
    Detections,
    TrackInstances,
    IdentifiedTrackInstances,
    ResolutionMessage,
    TrackInstance,
    Detection,
    AnomalyEvents,
)
from .utils.backoff import with_exponential_backoff
from .utils.config import get_tasks
from .constants import (
    Tasks,
    TaskTypeStr,
    ModuleNames,
    SHORT_SLEEP,
    QUEUE_TIMEOUT,
    PIKA_LOG_LEVEL,
    REID_CLASSES,
)

RABBIT_MAX_TRIES = 3
RABBIT_HEARTBEAT = 30
RABBIT_TIMEOUT = 180


def get_rabbit_settings():
    host = os.environ.get("RABBITMQ_HOST")
    port = os.environ.get("RABBITMQ_PORT", "5672").strip() or "5672"
    exchange = os.environ.get("RABBITMQ_EXCHANGE")
    if not host or not exchange:
        raise RuntimeError(
            "RABBITMQ_HOST and RABBITMQ_EXCHANGE must be set before using RabbitMQ"
        )
    return host, int(port), exchange


class RoutingKey:
    BAG = "REID_BAG"
    PERSON = "REID_PERSON"
    GUN = "INGESTOR_GUN"
    POI_SEARCH = "WEBAPP_POI_SEARCH"
    GROUP_REQUEST = "WEBAPP_GROUP_REQUEST"
    FRAME_INFO = "INGESTOR_FRAME_INFO"
    TRACK = "INGESTOR_TRACK"
    RESOLUTION_MESSAGE = "WEBAPP_RESOLUTION_MESSAGE"
    SYSTEM_MESSAGE = "WEBAPP_SYSTEM_MESSAGE"
    STATUS_MESSAGE = "STATUS_MESSAGE"
    ANOMALY = "ANOMALY_EVENTS"


Message = (
    SystemMessage
    | StatusMessage
    | POISearch
    | Frames
    | Detections
    | TrackInstances
    | IdentifiedTrackInstances
    | ResolutionMessage
    | AnomalyEvents
)

M = TypeVar("M", bound=Message)


logging.getLogger("pika").setLevel(PIKA_LOG_LEVEL)
logger = logging.getLogger(__name__)


@with_exponential_backoff(max_tries=RABBIT_MAX_TRIES)
def get_connection(queue_name: str, routing_key: str, create_queue: bool):
    host, port, exchange = get_rabbit_settings()
    connection_params = pika.ConnectionParameters(
        host=host,
        port=port,
        heartbeat=RABBIT_HEARTBEAT,
        blocked_connection_timeout=RABBIT_TIMEOUT,
    )
    connection = pika.BlockingConnection(connection_params)
    channel = connection.channel()
    channel.exchange_declare(exchange=exchange, durable=True, exchange_type="direct")
    if create_queue:
        channel.queue_declare(queue=queue_name, durable=True)
        channel.queue_bind(exchange=exchange, queue=queue_name, routing_key=routing_key)
    return channel, connection


class Consumer(Thread, Generic[M]):
    """
    rabbitmq message consumer
    """

    def __init__(
        self,
        routing_key,
        model: Type[M],
        queue_name=None,
        task_name="",
        logger=logger,
    ):
        super().__init__(name=self.__class__.__name__ + f" for {routing_key}")
        self.task_name = task_name if task_name else self.name
        self.logger = logger
        self.logger.debug(f"Initializing {self.name}", extra={"task": self.task_name})
        self.process = False
        self.routing_key = routing_key
        self.queue_name = queue_name if queue_name else f"{routing_key}_queue"
        self.connection = None
        self.channel = None
        self.queue: queue.Queue[M] = queue.Queue()
        self.MessageModel = model
        self.logger.debug(f"Initialized {self.name}", extra={"task": self.task_name})

    def run(self):
        self.logger.info(f"Starting {self.name}", extra={"task": self.task_name})
        self.process = True
        while self.process:
            if self.channel is None or self.connection is None or self.connection.is_closed:
                self.reconnect()
                continue
            try:
                for message in self.channel.consume(
                    queue=self.queue_name,
                    auto_ack=True,
                    inactivity_timeout=QUEUE_TIMEOUT,
                ):
                    if not all(message):
                        break
                    self.callback(message[2])
            except (AMQPConnectionError, AMQPError, OSError):
                self.logger.exception(
                    f"AMQP connection error, for {self.name}, reconnecting ...",
                    extra={"task": self.task_name},
                )
                self.reconnect()
        self.disconnect()
        self.logger.info(f"Stopped {self.name}", extra={"task": self.task_name})

    def connect(self):
        self.channel, self.connection = get_connection(
            self.queue_name, self.routing_key, True
        )

    def reconnect(self):
        try:
            self.disconnect()
        except Exception:
            self.logger.warning(
                f"Failed to disconnect stale AMQP connection for {self.name}",
                exc_info=True,
                extra={"task": self.task_name},
            )
        while self.process:
            try:
                self.connect()
                return
            except Exception:
                self.logger.warning(
                    f"Failed to connect {self.name}; retrying ...",
                    exc_info=True,
                    extra={"task": self.task_name},
                )
                time.sleep(1.0)

    def callback(self, body):
        try:
            message = self.MessageModel.model_validate_json(body.decode())
            self.queue.put(message)
        except Exception:
            self.logger.exception(
                f"Invalid Message received by {self.name}: {body}",
                extra={"task": self.task_name},
            )

    @with_exponential_backoff(max_tries=RABBIT_MAX_TRIES)
    def disconnect(self):
        try:
            if self.channel and self.channel.is_open:
                self.channel.stop_consuming()
        finally:
            self.channel = None
        try:
            if self.connection and self.connection.is_open:
                self.connection.close()
        finally:
            self.connection = None

    def stop(self):
        self.logger.info(f"Stopping {self.name}", extra={"task": self.task_name})
        self.process = False

    @with_exponential_backoff(max_tries=RABBIT_MAX_TRIES, max_delay=1.0)
    def clear_queue(self):
        channel = None
        connection = None
        try:
            channel, connection = get_connection(
                self.queue_name,
                self.routing_key,
                True,
            )
            message_count = channel.queue_purge(queue=self.queue_name).method.message_count
            self.logger.info(
                f"Queue {self.queue_name} cleared with {message_count} messages",
                extra={"task": self.task_name},
            )
        except AMQPConnectionError:
            raise
        except Exception:
            self.logger.exception(
                f"Failed to clear queue {self.queue_name}",
                extra={"task": self.task_name},
            )
        finally:
            if connection and connection.is_open:
                connection.close()


# fmt: off
SystemMessageConsumer = partial(Consumer[SystemMessage], routing_key=RoutingKey.SYSTEM_MESSAGE, model=SystemMessage)
StatusConsumer = partial(Consumer[StatusMessage], routing_key=RoutingKey.STATUS_MESSAGE, model=StatusMessage)
POISearchConsumer = partial(Consumer[POISearch], routing_key=RoutingKey.POI_SEARCH, model=POISearch)
FrameInfoConsumer = partial(Consumer[Frames], routing_key=RoutingKey.FRAME_INFO, model=Frames)
GunConsumer = partial(Consumer[Detections], routing_key=RoutingKey.GUN, model=Detections)
TrackConsumer = partial(Consumer[TrackInstances], routing_key=RoutingKey.TRACK, model=TrackInstances)
PersonConsumer = partial(Consumer[IdentifiedTrackInstances], routing_key=RoutingKey.PERSON, model=IdentifiedTrackInstances)
BagConsumer = partial(Consumer[IdentifiedTrackInstances], routing_key=RoutingKey.BAG, model=IdentifiedTrackInstances)
ResolutionConsumer = partial(Consumer[ResolutionMessage], routing_key=RoutingKey.RESOLUTION_MESSAGE, model=ResolutionMessage)
AnomalyConsumer = partial(Consumer[AnomalyEvents], routing_key=RoutingKey.ANOMALY, model=AnomalyEvents)
# fmt: on


def get_task_consumers(
    tasks: Iterable[TaskTypeStr],
    queue_names: dict[TaskTypeStr, str] = {},
    task_name: str = "",
):
    CONSUMERS = {
        Tasks.PERSON: PersonConsumer,
        Tasks.BAG: BagConsumer,
        Tasks.GUN: GunConsumer,
    }
    consumers = {}
    for task in tasks:
        if task not in CONSUMERS:
            logger.warning(f"Unknown task {task}")
        else:
            consumers[task] = CONSUMERS[task](
                queue_name=queue_names.get(task),
                task_name=task_name,
            )
    return consumers


def get_annotation_message_consumer():
    queue_names: dict[TaskTypeStr, str] = {
        task: f"{task}_annotation" for task in REID_CLASSES
    }
    consumers = get_task_consumers(REID_CLASSES, queue_names=queue_names)
    return MessageOrganizer[AnnotationMessage](consumers)


def get_association_message_consumer(cfg):
    tasks = get_tasks(cfg)
    consumers = get_task_consumers(tasks)
    frame_queue = RoutingKey.FRAME_INFO + "_" + ModuleNames.ASSOCIATION
    consumers[RoutingKey.FRAME_INFO] = FrameInfoConsumer(queue_name=frame_queue)
    return MessageOrganizer[AssociationMessage](consumers)


def get_reid_message_consumer():
    frame_queue = RoutingKey.FRAME_INFO + "_" + ModuleNames.REID
    consumers = {
        RoutingKey.TRACK: TrackConsumer(),
        RoutingKey.FRAME_INFO: FrameInfoConsumer(queue_name=frame_queue),
    }
    return MessageOrganizer[ReIDMessage](consumers)


def get_anomaly_message_consumer():
    frame_queue = RoutingKey.FRAME_INFO + "_" + ModuleNames.ANOMALY
    consumers = {
        RoutingKey.PERSON: PersonConsumer(),
        RoutingKey.BAG: BagConsumer(),
        RoutingKey.FRAME_INFO: FrameInfoConsumer(queue_name=frame_queue),
    }
    return MessageOrganizer[AnomalyMessage](consumers)


class AssociationMessage(TypedDict, total=False):
    PERSON: IdentifiedTrackInstances | None
    BAG: IdentifiedTrackInstances | None
    GUN: Detections | None
    FRAME_INFO: Frames | None


class AnnotationMessage(TypedDict, total=False):
    PERSON: IdentifiedTrackInstances | None
    BAG: IdentifiedTrackInstances | None


class ReIDMessage(TypedDict, total=False):
    INGESTOR_TRACK: TrackInstances | None
    INGESTOR_FRAME_INFO: Frames | None


class AnomalyMessage(TypedDict, total=False):
    REID_PERSON: IdentifiedTrackInstances | None
    REID_BAG: IdentifiedTrackInstances | None
    INGESTOR_FRAME_INFO: Frames | None


Batch = TypeVar(
    "Batch",
    AssociationMessage,
    ReIDMessage,
    AnnotationMessage,
    dict[str, Message | None],
)


class MessageOrganizer(Thread, Generic[Batch]):
    """
    Synchronizes messages from multiple consumers
    """

    def __init__(self, consumers: dict[str, Consumer], task_name=""):
        keys = list(consumers.keys())
        super().__init__(name=self.__class__.__name__ + f" for {keys}")
        self.task_name = task_name if task_name else self.name
        logger.debug(f"Initializing {self.name}", extra={"task": self.task_name})
        self.process = False
        self.queue: queue.Queue[tuple[int, Batch]] = queue.Queue()
        self.consumers = consumers
        self.clear_consumer_queues_on_stop = False

        self.messages: dict[int, Batch] = defaultdict(
            lambda: {key: None for key in consumers}  # type: ignore
        )
        logger.debug(f"Initialized {self.name}", extra={"task": self.task_name})

    def run(self):
        logger.info(f"Starting {self.name}", extra={"task": self.task_name})
        self.process = True
        for consumer in self.consumers.values():
            consumer.start()

        while self.process:
            hit = False
            for key in self.consumers:
                try:
                    message = self.consumers[key].queue.get_nowait()
                    self.messages[message.frame_id][key] = message
                    hit = True
                except queue.Empty:
                    continue

            if not hit:
                time.sleep(SHORT_SLEEP)

            partial_frames = []
            for frame_id, batch in list(self.messages.items()):
                if None in batch.values():
                    partial_frames.append(frame_id)
                else:
                    self.push_frames(frame_id, batch, partial_frames)
                    partial_frames = []

        for consumer in self.consumers.values():
            consumer.stop()
        for consumer in self.consumers.values():
            consumer.join()
        if self.clear_consumer_queues_on_stop:
            for consumer in self.consumers.values():
                consumer.clear_queue()

        logger.info(f"Stopped {self.name}", extra={"task": self.task_name})

    def push_frames(self, frame_id: int, batch: Batch, partial_frame_ids: list[int]):
        for partial_frame_id in partial_frame_ids:
            missed_keys = []
            partial_message = self.messages[partial_frame_id]
            for key in self.consumers:
                if partial_message[key] is None:
                    missed_keys.append(key)
            logger.warning(
                f"{self.name} missed keys {missed_keys} for frame {partial_frame_id} (current frame: {frame_id})",
                extra={"task": self.task_name},
            )
            self.queue.put((partial_frame_id, partial_message))
            del self.messages[partial_frame_id]
        self.queue.put((frame_id, batch))
        del self.messages[frame_id]

    def stop(self, clear_queues: bool = False):
        logger.info(f"Stopping {self.name}", extra={"task": self.task_name})
        self.clear_consumer_queues_on_stop = clear_queues
        self.process = False


class Publisher:
    """
    Superclass for rabbit publishers
    """

    def __init__(self, routing_key, task_name="", create_queue=True):
        self.name = f"Publisher for {routing_key}"
        self.task_name = task_name if task_name else self.name
        self._io_lock = RLock()
        logger.debug(f"Initializing {self.name}", extra={"task": self.task_name})
        self.routing_key = routing_key
        self.queue_name = f"{routing_key}_queue"
        self.create_queue = create_queue
        self.connection = None
        self.channel = None
        self.connect(create_queue=create_queue)
        logger.debug(f"Initialized {self.name}", extra={"task": self.task_name})

    def connect(self, create_queue=True):
        with self._io_lock:
            self.channel, self.connection = get_connection(
                self.queue_name, self.routing_key, create_queue
            )

    @with_exponential_backoff(max_tries=RABBIT_MAX_TRIES, max_delay=1.0)
    def publish(self, data):
        with self._io_lock:
            try:
                assert self.channel is not None
                _, _, exchange = get_rabbit_settings()
                body = data.model_dump_json()
                self.channel.basic_publish(
                    exchange=exchange, routing_key=self.routing_key, body=body
                )
            except Exception:
                self._close_unlocked()
                self._connect_unlocked(create_queue=self.create_queue)
                raise

    def close(self, clear_queue=False):
        with self._io_lock:
            self._close_unlocked(clear_queue=clear_queue)

    def _connect_unlocked(self, create_queue=True):
        self.channel, self.connection = get_connection(
            self.queue_name, self.routing_key, create_queue
        )

    def _close_unlocked(self, clear_queue=False):
        logger.info(f"Closing {self.name}", extra={"task": self.task_name})
        if self.connection and self.connection.is_open:
            if clear_queue and self.create_queue:
                self._clear_queue_unlocked()
            self.connection.close()
        self.connection = None
        self.channel = None

    @with_exponential_backoff(max_tries=RABBIT_MAX_TRIES, max_delay=1.0)
    def clear_queue(self):
        with self._io_lock:
            self._clear_queue_unlocked()

    def _clear_queue_unlocked(self):
        try:
            if self.channel is not None:
                message_count = self.channel.queue_purge(
                    queue=self.queue_name
                ).method.message_count
                logger.info(
                    f"Queue {self.queue_name} cleared with {message_count} messages",
                    extra={"task": self.task_name},
                )
            else:
                logger.warning(
                    f"Failed to clear queue {self.queue_name} because channel is None",
                    extra={"task": self.task_name},
                )
        except AMQPConnectionError:
            self._connect_unlocked(create_queue=self.create_queue)
            raise
        except Exception:
            logger.exception(
                f"Failed to clear queue {self.queue_name}",
                extra={"task": self.task_name},
            )


class FrameInfoPublisher(Publisher):
    """
    Sends Frames[FrameInfo] data to another module
    """

    def __init__(self, routing_key=RoutingKey.FRAME_INFO, task_name=""):
        super().__init__(routing_key, task_name=task_name, create_queue=False)

    def publish_frame(self, frames: Frames):
        self.publish(frames)


class DetectionPublisher(Publisher):
    """
    Sends Detection data to another module
    """

    def __init__(self, routing_key, task_name=""):
        super().__init__(routing_key, task_name=task_name)

    def publish_frame(self, detections: list[Detection], frame_id: int):
        message = Detections(frame_id=frame_id, detections=detections)
        self.publish(message)


GunPublisher = partial(DetectionPublisher, routing_key=RoutingKey.GUN)


class TrackPublisher(Publisher):
    """
    Sends TrackInstance data to another module
    """

    def __init__(self, routing_key=RoutingKey.TRACK, task_name=""):
        super().__init__(routing_key, task_name=task_name)

    def publish_frame(self, tracks: list[TrackInstance], frame_id: int):
        message = TrackInstances(frame_id=frame_id, track_instances=tracks)
        self.publish(message)


class ReIDPublisher(Publisher):
    """
    Sends TrackInstance data with ids along with id map updates to another module
    """

    def __init__(self, routing_key, task_name=""):
        super().__init__(routing_key, task_name=task_name)

    def publish_frame(
        self,
        tracks: list[TrackInstance],
        id_updates: dict[int, int],
        frame_id: int,
        id_guesses: dict[int, int] = {},
    ):
        message = IdentifiedTrackInstances(
            frame_id=frame_id,
            track_instances=tracks,
            id_updates=id_updates,
            id_guesses=id_guesses,
        )
        self.publish(message)


PersonPublisher = partial(ReIDPublisher, routing_key=RoutingKey.PERSON)
BagPublisher = partial(ReIDPublisher, routing_key=RoutingKey.BAG)


class POISearchPublisher(Publisher):
    """
    Sends POISearch data to another module
    """

    def __init__(self, routing_key=RoutingKey.POI_SEARCH, task_name=""):
        super().__init__(routing_key, task_name=task_name)

    def publish_item(self, search: POISearch):
        self.publish(search)


class ResolutionPublisher(Publisher):
    """
    Publishes incident resolutions to association module
    """

    def __init__(self, routing_key=RoutingKey.RESOLUTION_MESSAGE, task_name=""):
        super().__init__(routing_key, task_name=task_name)

    def publish_resolution(self, resolution: ResolutionMessage):
        self.publish(resolution)


class StatusPublisher(Publisher):
    """
    Publishes status messages to another module
    """

    def __init__(self, routing_key=RoutingKey.STATUS_MESSAGE, task_name=""):
        super().__init__(routing_key, task_name=task_name)

    def publish(self, data):
        try:
            super().publish(data)
        except Exception:
            logger.warning(
                f"Failed to publish status message, skipping: {data}",
                extra={"task": self.task_name},
            )

    def publish_status(self, status: StatusMessage):
        logger.info(f"Publishing StatusMessage: {status}")
        self.publish(status)


class AnomalyPublisher(Publisher):
    def __init__(self, routing_key=RoutingKey.ANOMALY, task_name=""):
        super().__init__(routing_key, task_name=task_name)

    def publish_events(self, events: AnomalyEvents):
        self.publish(events)


class SystemMessagePublisher(Publisher):
    """
    Sends SystemMessage data to backend modules
    """

    def __init__(self, routing_key=RoutingKey.SYSTEM_MESSAGE, task_name=""):
        super().__init__(routing_key, task_name=task_name, create_queue=False)

    def publish_message(self, message: SystemMessage):
        logger.info(
            f"Publishing SystemMessage: {message}", extra={"task": self.task_name}
        )
        self.publish(message)
