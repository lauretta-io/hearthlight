from __future__ import annotations


def summarize_queue_backpressure(
    queue_depths: dict[str, int | None],
    *,
    warn_threshold: int = 10,
    error_threshold: int = 50,
) -> dict:
    normalized_depths = {
        name: int(depth)
        for name, depth in queue_depths.items()
        if depth is not None
    }
    if not normalized_depths:
        return {
            "state": "ok",
            "max_queue_depth": 0,
            "hottest_queue": None,
            "queue_depths": {},
        }

    hottest_queue, max_depth = max(
        normalized_depths.items(),
        key=lambda item: item[1],
    )
    if max_depth >= error_threshold:
        state = "error"
    elif max_depth >= warn_threshold:
        state = "warning"
    else:
        state = "ok"
    return {
        "state": state,
        "max_queue_depth": max_depth,
        "hottest_queue": hottest_queue,
        "queue_depths": normalized_depths,
    }
