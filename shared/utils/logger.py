import json
import logging
import os
from ..constants import ORCHESTRATION_LOG_DIR, ORCHESTRATION_LOG_LEVEL

BOOTSTRAP_LOG_DIR = "shared/output/bootstrap_logs"


class FileFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%d %H:%M:%S.%f"),
            "level": record.levelname,
            "message": record.msg,
            "filename": record.filename,
            "line": record.lineno,
        }
        if record.exc_info:
            # Add line number from traceback
            tb = record.exc_info[2]
            while tb.tb_next:
                tb = tb.tb_next
            log_entry["line"] = tb.tb_lineno

        if hasattr(record, "task"):
            log_entry["task"] = record.task
        if hasattr(record, "status"):
            log_entry["status"] = record.status
        if record.exc_info:
            log_entry["error"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


class ConsoleFormatter(logging.Formatter):
    def format(self, record):
        message = f"{record.levelname} : {record.msg} ({record.filename}:{record.lineno})"
        if record.exc_info:
            message += f"\n{self.formatException(record.exc_info)}"

        return message


def configure_logging(log_level, log_dir, module_name, use_root=True):
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    log_file = f"{module_name}.log"
    path = os.path.join(log_dir, log_file)
    file_handler = logging.FileHandler(path)
    file_handler.setFormatter(FileFormatter())
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ConsoleFormatter())
    if use_root:
        logger = logging.getLogger()
    else:
        logger = logging.getLogger(module_name)
        logger.propagate = False
    while logger.hasHandlers():
        logger.removeHandler(logger.handlers[0])
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    level = log_level.upper() if isinstance(log_level, str) else log_level
    logger.setLevel(level)
    return logger


def get_log_level(cfg, module_name):
    return cfg.logging.get(module_name) or cfg.logging.get("level", "INFO")


def get_run_log_dir(cfg):
    return cfg.logging.get("log_dir", "shared/output/logs")


def get_bootstrap_log_dir(cfg):
    return cfg.logging.get("bootstrap_log_dir", BOOTSTRAP_LOG_DIR)


def set_run_logging(cfg, module_name):
    configure_logging(get_log_level(cfg, module_name), get_run_log_dir(cfg), module_name)


def set_bootstrap_logging(cfg, module_name):
    configure_logging(
        get_log_level(cfg, module_name),
        get_bootstrap_log_dir(cfg),
        module_name,
    )


def get_orchestration_logger(module_name):
    return configure_logging(
        ORCHESTRATION_LOG_LEVEL, ORCHESTRATION_LOG_DIR, module_name, use_root=False
    )
