MODULE_STATUS_IDLE = "idle"
MODULE_STATUS_RUNNING = "running"
MODULE_STATUS_ERROR = "error"
MODULE_STATUS_STOPPED = "stopped"
MODULE_STATUS_INITIALIZED = "initialized"
MODULE_STATUS_INFO = "info"
MODULE_STATUS_EXIT = "exit"


class SystemStatus:
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


def normalize_module_status(raw_status: str | None) -> str:
    if raw_status in {MODULE_STATUS_RUNNING, MODULE_STATUS_ERROR, MODULE_STATUS_IDLE}:
        return raw_status
    if raw_status in {MODULE_STATUS_STOPPED, MODULE_STATUS_INITIALIZED, MODULE_STATUS_INFO, MODULE_STATUS_EXIT}:
        return MODULE_STATUS_IDLE
    return MODULE_STATUS_IDLE


def derive_system_status(current_status: str, module_statuses: list[str]) -> tuple[str, bool]:
    normalized_statuses = [normalize_module_status(status) for status in module_statuses]
    if any(status == MODULE_STATUS_ERROR for status in normalized_statuses):
        return SystemStatus.ERROR, False
    if current_status == SystemStatus.ERROR:
        # Recover from stale error state once all modules are healthy again.
        if all(
            status in {MODULE_STATUS_IDLE, MODULE_STATUS_RUNNING}
            for status in normalized_statuses
        ):
            return SystemStatus.RUNNING, False
    if current_status == SystemStatus.INITIALIZING:
        # Startup can legitimately settle into IDLE for stream-backed workers until
        # first frames arrive; don't keep the whole system stuck in initializing.
        if all(
            status in {MODULE_STATUS_IDLE, MODULE_STATUS_RUNNING}
            for status in normalized_statuses
        ):
            return SystemStatus.RUNNING, False
    elif current_status == SystemStatus.STOPPING:
        if all(status == MODULE_STATUS_IDLE for status in normalized_statuses):
            return SystemStatus.IDLE, True
    elif current_status == SystemStatus.RUNNING:
        if all(status == MODULE_STATUS_IDLE for status in normalized_statuses):
            return SystemStatus.IDLE, True
    if (
        current_status in {SystemStatus.IDLE, SystemStatus.INITIALIZING}
        and any(status == MODULE_STATUS_RUNNING for status in normalized_statuses)
    ):
        return SystemStatus.RUNNING, False
    return current_status, False


def get_error_modules(module_status: dict[str, str]) -> list[str]:
    return sorted(
        module_name
        for module_name, status in module_status.items()
        if status == MODULE_STATUS_ERROR
    )
