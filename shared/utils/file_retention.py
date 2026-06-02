from __future__ import annotations

from pathlib import Path
import logging


logger = logging.getLogger(__name__)


def directory_size_bytes(
    path: str | Path | None,
    *,
    max_files: int | None = 2000,
) -> int | None:
    if not path:
        return None
    target = Path(path)
    if not target.exists():
        return 0
    total = 0
    scanned = 0
    for child in target.rglob("*"):
        if not child.is_file():
            continue
        scanned += 1
        if max_files is not None and scanned > max_files:
            logger.debug(
                "Stopped directory size scan at %s files for %s",
                max_files,
                target,
            )
            break
        try:
            total += child.stat().st_size
        except OSError:
            continue
    return total


def prune_directory_files(
    path: str | Path | None,
    *,
    max_files: int | None = None,
) -> int:
    if not path or max_files is None or max_files <= 0:
        return 0
    target = Path(path)
    if not target.exists():
        return 0
    files = sorted(
        (child for child in target.iterdir() if child.is_file()),
        key=lambda child: child.stat().st_mtime,
    )
    removed = 0
    while len(files) > max_files:
        victim = files.pop(0)
        try:
            victim.unlink()
            removed += 1
        except OSError:
            logger.warning("Failed to prune retained file %s", victim, exc_info=True)
    return removed
