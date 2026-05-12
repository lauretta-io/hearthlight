from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_REPO_URL = "https://github.com/lauretta-io/hearthlight.git"
DEFAULT_REPO_BRANCH = "main"
DEFAULT_WORKSPACE_PATH = Path.home() / "hearthlight"
USER_CONFIG_DIR = Path.home() / ".config" / "hearthlight"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.json"
WORKSPACE_OVERRIDE_ENV = "HEARTHLIGHT_WORKSPACE"
LOCAL_EXECUTION_ENV = "HEARTHLIGHT_CLI_LOCAL"


def is_workspace_root(path: Path) -> bool:
    return (
        (path / "docker-compose.yaml").exists()
        and (path / "hearthlight").is_dir()
        and (path / "shared" / "configs" / "example_config.yaml").exists()
    )


def load_user_config() -> dict[str, str]:
    if not USER_CONFIG_PATH.exists():
        return {}
    try:
        loaded = json.loads(USER_CONFIG_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def save_user_config(data: dict[str, str]) -> None:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def save_default_workspace(path: Path) -> None:
    config = load_user_config()
    config["default_workspace"] = str(path.expanduser().resolve())
    save_user_config(config)


def find_workspace_from_current_path(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if is_workspace_root(candidate):
            return candidate
    return None


def resolve_workspace(explicit: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())

    env_override = os.environ.get(WORKSPACE_OVERRIDE_ENV, "").strip()
    if env_override:
        candidates.append(Path(env_override).expanduser())

    config = load_user_config()
    configured = str(config.get("default_workspace", "")).strip()
    if configured:
        candidates.append(Path(configured).expanduser())

    inferred = find_workspace_from_current_path()
    if inferred is not None:
        candidates.append(inferred)

    for candidate in candidates:
        resolved = candidate.resolve()
        if is_workspace_root(resolved):
            return resolved
    return None


def workspace_python_path(workspace: Path) -> Path:
    if os.name == "nt":
        return workspace / ".venv" / "Scripts" / "python.exe"
    return workspace / ".venv" / "bin" / "python"
