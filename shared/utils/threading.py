from __future__ import annotations

from threading import Thread


def collect_live_thread_names(root, *, include_root: bool = False) -> list[str]:
    names: set[str] = set()
    seen_objects: set[int] = set()

    def walk(value):
        if value is None:
            return
        object_id = id(value)
        if object_id in seen_objects:
            return
        seen_objects.add(object_id)

        if isinstance(value, Thread):
            if value.is_alive() and (include_root or value is not root):
                names.add(value.name)
            walk(getattr(value, "__dict__", None))
            return

        if isinstance(value, dict):
            try:
                items = list(value.values())
            except Exception:
                return
            for item in items:
                walk(item)
            return

        if isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)
            return

        attributes = getattr(value, "__dict__", None)
        if attributes is not None:
            walk(attributes)

    walk(root)
    return sorted(names)
