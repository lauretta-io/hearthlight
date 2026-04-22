from __future__ import annotations

from datetime import datetime, timezone


def seconds_since_datetime(value: datetime | None, *, now: datetime | None = None) -> int | None:
    if value is None:
        return None
    reference = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = reference - value
    return max(0, int(delta.total_seconds()))
