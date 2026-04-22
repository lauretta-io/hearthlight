from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from hearthlight.cli import main as hearthlight_main


def main(argv: list[str] | None = None) -> int:
    os.environ["HEARTHLIGHT_LEGACY_WRAPPER"] = "1"
    return hearthlight_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
