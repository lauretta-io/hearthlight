import logging

from ..constants import Tasks

CAMERA_TASKS = [Tasks.PERSON, Tasks.BAG]


def normalize_camera_tasks(tasks, *, camera_label: str | None = None):
    normalized = []
    label = camera_label or "camera"
    for raw_task in tasks or []:
        task = str(raw_task).strip().upper()
        if task == Tasks.GUN:
            logging.warning("Ignoring unsupported task %s for %s", task, label)
            continue
        if task not in CAMERA_TASKS:
            logging.warning("Unknown task %s for %s", task, label)
        normalized.append(task)
    return normalized


def get_tasks(cfg):
    tasks = set()
    for camera in cfg.input.cameras:
        if "tasks" in cfg.input.cameras[camera]:
            camera_tasks = normalize_camera_tasks(
                cfg.input.cameras[camera]["tasks"],
                camera_label=f"camera {camera}",
            )
            for task in camera_tasks:
                tasks.add(task)
    if Tasks.PERSON in tasks:
        tasks.add(Tasks.POI)
    return tasks
