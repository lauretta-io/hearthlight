import queue
from typing import Protocol
import logging

from omegaconf import DictConfig

from .rabbit_messenger import SystemMessageConsumer, StatusPublisher
from .models.DataModels import SystemCommand, Status, StatusMessage
from .utils.logger import get_orchestration_logger
from .utils.threading import collect_live_thread_names
from .constants import QUEUE_TIMEOUT

logger = logging.getLogger(__name__)


class ModuleProtocol(Protocol):
    def __init__(self, cfg: DictConfig, status_publisher: StatusPublisher) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def join(self) -> None: ...


def run_command_listener(module_name: str, Module: type[ModuleProtocol]):
    orchestration_logger = get_orchestration_logger(module_name)
    orchestration_logger.debug("Initializing system message consumer")
    system_message_consumer = SystemMessageConsumer(
        logger=orchestration_logger, queue_name=module_name
    )
    system_message_consumer.start()
    status_publisher = StatusPublisher()

    def publish_status(status: str):
        status_publisher.publish(StatusMessage(status=status, module=module_name))

    status = Status.IDLE

    orchestration_logger.debug("Initialized system message consumer")
    module = None
    try:
        while True:
            try:
                publish_status(status)
            except Exception:
                orchestration_logger.warning("Failed to publish status, will retry next cycle")
            try:
                message = system_message_consumer.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                if module is not None and not module.is_alive():
                    completed_normally = getattr(module, "completed_normally", False)
                    try:
                        module.join(timeout=2)
                    except Exception:
                        orchestration_logger.exception(
                            "Failed to join exited module %s",
                            module_name,
                        )
                    module = None
                    if completed_normally:
                        orchestration_logger.info(
                            "Module %s finished normally",
                            module_name,
                        )
                        status = Status.STOPPED
                    else:
                        orchestration_logger.error(
                            "Module %s exited unexpectedly",
                            module_name,
                        )
                        status = Status.ERROR
                    publish_status(status)
                continue
            orchestration_logger.info(f"Received command: {message.command}")
            if message.target_modules and module_name not in message.target_modules:
                orchestration_logger.debug(
                    "Ignoring command %s because %s is not targeted",
                    message.command,
                    module_name,
                )
                continue
            if message.command == SystemCommand.START:
                if module is None:
                    orchestration_logger.info("Starting %s", module_name)
                    try:
                        module = Module(message.config, status_publisher)
                        status = Status.INITIALIZED
                        publish_status(status)
                    except Exception:
                        orchestration_logger.exception("Failed to start %s", module_name)
                        module = None
                        status = Status.ERROR
                        publish_status(status)
                        continue
                    module.start()
                    status = Status.RUNNING
                    publish_status(status)
                    orchestration_logger.info("Started %s", module_name)
                else:
                    orchestration_logger.warning("Module %s is already running", module_name)
                    continue
            elif message.command in [SystemCommand.STOP, SystemCommand.EXIT]:
                if module is not None:
                    orchestration_logger.info("Stopping %s", module_name)
                    module.stop()
                    live_threads = collect_live_thread_names(module)
                    if live_threads:
                        orchestration_logger.warning(
                            "Waiting for module threads to stop: %s",
                            ", ".join(live_threads),
                        )
                    module.join()
                    lingering_threads = collect_live_thread_names(module)
                    if lingering_threads:
                        orchestration_logger.warning(
                            "Module threads still alive after join: %s",
                            ", ".join(lingering_threads),
                        )
                    module = None
                    orchestration_logger.info("Stopped %s", module_name)
                    status = Status.STOPPED
                    publish_status(status)
                else:
                    orchestration_logger.info("Module %s was not running", module_name)
                status = Status.IDLE
                publish_status(status)
            if message.command == SystemCommand.EXIT:
                orchestration_logger.info("Exiting")
                break
    finally:
        if module is not None:
            try:
                module.stop()
                live_threads = collect_live_thread_names(module)
                if live_threads:
                    orchestration_logger.warning(
                        "Cleaning up module threads during shutdown: %s",
                        ", ".join(live_threads),
                    )
                module.join()
            except Exception:
                orchestration_logger.exception("Failed to stop module cleanly during shutdown")
        try:
            publish_status(Status.EXIT)
        except Exception:
            orchestration_logger.exception("Failed to publish exit status")
        try:
            system_message_consumer.stop()
            system_message_consumer.join(timeout=2)
        except Exception:
            orchestration_logger.exception("Failed to stop system message consumer")
        try:
            status_publisher.close()
        except Exception:
            orchestration_logger.exception("Failed to close status publisher")
