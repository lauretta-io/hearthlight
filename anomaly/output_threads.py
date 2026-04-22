from __future__ import annotations

from threading import Thread
import logging
import queue

from ..shared.constants import QUEUE_TIMEOUT
from ..shared.database.database_worker import DatabaseWorker
from ..shared.models.DataModels import AnomalyEvent, AnomalyEvents
from ..shared.rabbit_messenger import AnomalyPublisher

logger = logging.getLogger(__name__)


class OutputThread(Thread):
    def __init__(self):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.process = False
        self.queue = queue.Queue[tuple[int, list[AnomalyEvent]]]()
        self.rabbit_thread = RabbitThread()
        self.database_thread = DatabaseThread()

    def run(self):
        self.process = True
        self.rabbit_thread.start()
        self.database_thread.start()
        while self.process:
            try:
                frame_id, events = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            self.rabbit_thread.queue.put((frame_id, events))
            self.database_thread.queue.put(events)

        self.rabbit_thread.stop()
        self.database_thread.stop()
        self.rabbit_thread.join()
        self.database_thread.join()

    def stop(self):
        self.process = False


class RabbitThread(Thread):
    def __init__(self):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.process = False
        self.queue = queue.Queue[tuple[int, list[AnomalyEvent]]]()
        self.publisher = AnomalyPublisher()

    def run(self):
        self.process = True
        while self.process:
            try:
                frame_id, events = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            self.publisher.publish_events(AnomalyEvents(frame_id=frame_id, events=events))
        self.publisher.close(clear_queue=True)

    def stop(self):
        self.process = False


class DatabaseThread(Thread):
    def __init__(self):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.process = False
        self.queue = queue.Queue[list[AnomalyEvent]]()
        self.database_publisher = DatabaseWorker()

    def run(self):
        self.process = True
        while self.process:
            try:
                events = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            self.database_publisher.publish_anomaly_data(events)

    def stop(self):
        self.process = False

