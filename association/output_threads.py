import threading
import queue
import logging

from .incident_classes import Incident
from shared.database.database_worker import DatabaseWorker
from shared.constants import QUEUE_TIMEOUT

logger = logging.getLogger(__name__)


class OutputThread(threading.Thread):
    def __init__(self, cfg):
        super().__init__(name=self.__class__.__name__)
        logger.debug("Initializing", extra={"task": self.name})
        self.process = False
        self.queue = queue.Queue[
            tuple[
                list[tuple[int, int]],
                list[Incident],
                list[Incident],
            ]
        ]()
        DatabaseWorker.set_run_id(cfg.run_id)
        self.db_client = DatabaseWorker()
        logger.debug("Initialized", extra={"task": self.name})

    def run(self):
        logger.debug("Starting", extra={"task": self.name})
        self.process = True
        while self.process:
            try:
                (bag_owner_pairs, new_incidents, system_resolutions) = (
                    self.queue.get(timeout=QUEUE_TIMEOUT)
                )
            except queue.Empty:
                continue

            self.db_client.publish_bag_owner_pairs(bag_owner_pairs)
            self.db_client.publish_incidents(new_incidents, system_resolutions)

        logger.debug("Stopped", extra={"task": self.name})

    def stop(self):
        logger.debug("Stopping", extra={"task": self.name})
        self.process = False
