from __future__ import annotations

import queue
from typing import Any


DROP_OLDEST = "drop_oldest"
DROP_NEWEST = "drop_newest"


def bounded_put(
    target_queue: queue.Queue,
    item: Any,
    *,
    overflow_policy: str = DROP_OLDEST,
) -> tuple[bool, bool]:
    """
    Put an item into a bounded queue without blocking indefinitely.

    Returns:
      inserted: whether the new item was inserted
      dropped_existing: whether an existing queued item was evicted first
    """
    try:
        target_queue.put_nowait(item)
        return True, False
    except queue.Full:
        if overflow_policy == DROP_NEWEST:
            return False, False
        if overflow_policy != DROP_OLDEST:
            raise ValueError(f"unsupported overflow policy: {overflow_policy}")
        try:
            target_queue.get_nowait()
        except queue.Empty:
            return False, False
        try:
            target_queue.put_nowait(item)
            return True, True
        except queue.Full:
            return False, True
