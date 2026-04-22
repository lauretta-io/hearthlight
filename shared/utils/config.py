import logging

from ..constants import Tasks

CAMERA_TASKS = [Tasks.PERSON, Tasks.BAG, Tasks.GUN]


def get_tasks(cfg):
    tasks = set()
    for camera in cfg.input.cameras:
        if "tasks" in cfg.input.cameras[camera]:
            camera_tasks = cfg.input.cameras[camera]["tasks"]
            for task in camera_tasks:
                task = task.upper()
                if task not in CAMERA_TASKS:
                    logging.warning(f"Unknown task {task} for camera {camera}")
                tasks.add(task)
    if Tasks.PERSON in tasks:
        tasks.add(Tasks.POI)
    return tasks
