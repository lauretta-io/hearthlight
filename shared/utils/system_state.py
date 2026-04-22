MODULE_STATUS_IDLE = "idle"
MODULE_STATUS_RUNNING = "running"
MODULE_STATUS_ERROR = "error"


class SystemStatus:
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


def derive_system_status(current_status: str, module_statuses: list[str]) -> tuple[str, bool]:
    if any(status == MODULE_STATUS_ERROR for status in module_statuses):
        return SystemStatus.ERROR, False
    if current_status == SystemStatus.INITIALIZING:
        if all(status == MODULE_STATUS_RUNNING for status in module_statuses):
            return SystemStatus.RUNNING, False
    elif current_status == SystemStatus.STOPPING:
        if all(status == MODULE_STATUS_IDLE for status in module_statuses):
            return SystemStatus.IDLE, True
    return current_status, False


def get_error_modules(module_status: dict[str, str]) -> list[str]:
    return sorted(
        module_name
        for module_name, status in module_status.items()
        if status == MODULE_STATUS_ERROR
    )
