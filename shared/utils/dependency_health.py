from __future__ import annotations


def normalize_dependency_status(healthchecks: dict[str, tuple[bool, str | None]]) -> dict[str, dict]:
    normalized = {}
    for name, (healthy, detail) in healthchecks.items():
        normalized[name] = {
            "status": "ok" if healthy else "error",
            "detail": detail,
        }
    return normalized


def get_unhealthy_dependencies(dependency_status: dict[str, dict] | None) -> list[str]:
    if not dependency_status:
        return []
    failures = []
    for name, status in dependency_status.items():
        if status.get("status") != "ok":
            detail = status.get("detail")
            failures.append(f"{name}: {detail}" if detail else name)
    return failures
