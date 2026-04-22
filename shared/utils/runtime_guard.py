from __future__ import annotations

from threading import Thread


def should_fail_for_missing_frames(
    *,
    last_frame_received_at: float | None,
    now: float,
    timeout_seconds: float,
) -> bool:
    if last_frame_received_at is None:
        return False
    return now - last_frame_received_at >= timeout_seconds


def get_missing_frame_failure_reason(
    *,
    frames_thread_alive: bool,
    timeout_seconds: float,
) -> str:
    if not frames_thread_alive:
        return "frame capture thread stopped unexpectedly"
    return (
        "no frames received within "
        f"{timeout_seconds:.1f} seconds; all sources may be disconnected"
    )


def get_dead_thread_names(threads: dict[str, Thread] | list[tuple[str, Thread]]) -> list[str]:
    items = threads.items() if isinstance(threads, dict) else threads
    return sorted(name for name, thread in items if not thread.is_alive())
