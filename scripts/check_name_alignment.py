#!/usr/bin/env python3
"""Check project-owned naming alignment after product/domain renames."""

from __future__ import annotations

from pathlib import Path
import os
import re
import sys


ROOT = Path(__file__).resolve().parents[1]

IGNORED_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    ".venv-macos-app",
    "__pycache__",
    "build",
    "dist",
    "frontend/node_modules",
    "node_modules",
}

BANNED_TERMS = (
    "Stage2ProviderSettings",
    "Stage2ProviderSetting",
    "stage2_provider_settings",
    "stage2_provider_setting",
    "stage2-provider-settings",
    "/settings/stage2-provider-settings",
    "Stage 2 Provider Settings",
    "Stage 2 provider settings",
    "Settings > Sources > Anomaly LLM Models",
    "shared/plugins/core/",
)

LEGACY_MIGRATION_ALLOWLIST = {
    "shared/utils/anomaly_llm_model_settings.py": (
        "stage2_provider_setting",
        "Stage 2 provider settings table",
        "uq_stage2_provider_setting_key",
    ),
}


def _is_ignored(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    parts = rel.split("/")
    if any(part in {"node_modules", ".git", ".pytest_cache", ".venv", ".venv-macos-app", "__pycache__", "build", "dist"} for part in parts):
        return True
    for index in range(len(parts)):
        if "/".join(parts[: index + 1]) in IGNORED_DIRS:
            return True
    return False


def _iter_project_files() -> list[Path]:
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(ROOT):
        directory_path = Path(directory)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not _is_ignored(directory_path / dirname)
        ]
        for filename in filenames:
            path = directory_path / filename
            if _is_ignored(path):
                continue
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf"}:
                continue
            files.append(path)
    return files


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _check_banned_terms(files: list[Path]) -> list[str]:
    errors: list[str] = []
    checker_rel = Path(__file__).resolve().relative_to(ROOT).as_posix()
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if rel == checker_rel:
            continue
        text = _read_text(path)
        if text is None:
            continue
        allowed = LEGACY_MIGRATION_ALLOWLIST.get(rel, ())
        for line_number, line in enumerate(text.splitlines(), start=1):
            for term in BANNED_TERMS:
                if term in line and not any(allowed_term in line for allowed_term in allowed):
                    errors.append(f"{rel}:{line_number}: stale renamed term {term!r}")
    return errors


def _check_plugin_directory_keys() -> list[str]:
    errors: list[str] = []
    plugin_root = ROOT / "shared" / "plugins"
    if not plugin_root.exists():
        return errors
    key_pattern = re.compile(r"^key:[ \t]*[\"']?([^\"' \t\r\n#]+)", re.MULTILINE)
    for manifest in sorted(plugin_root.glob("*/plugin.yaml")):
        text = _read_text(manifest) or ""
        match = key_pattern.search(text)
        if not match:
            errors.append(f"{manifest.relative_to(ROOT)}: missing plugin key")
            continue
        key = match.group(1).strip()
        directory_name = manifest.parent.name
        if key != directory_name:
            errors.append(
                f"{manifest.relative_to(ROOT)}: plugin key {key!r} does not match directory {directory_name!r}"
            )
    return errors


def _check_test_file_names() -> list[str]:
    errors: list[str] = []
    required = (
        ROOT / "tests" / "test_anomaly_llm_model_settings.py",
        ROOT / "frontend" / "e2e" / "anomaly-llm-model-settings.spec.js",
    )
    forbidden = (
        ROOT / "tests" / "test_stage2_provider_settings.py",
        ROOT / "frontend" / "e2e" / "stage2-provider-settings.spec.js",
    )
    for path in required:
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)}: expected renamed test file is missing")
    for path in forbidden:
        if path.exists():
            errors.append(f"{path.relative_to(ROOT)}: stale test file remains after rename")
    return errors


def main() -> int:
    files = _iter_project_files()
    errors = []
    errors.extend(_check_banned_terms(files))
    errors.extend(_check_plugin_directory_keys())
    errors.extend(_check_test_file_names())
    if errors:
        print("Name alignment check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Name alignment check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
