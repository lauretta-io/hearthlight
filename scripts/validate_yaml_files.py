from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml
from omegaconf import OmegaConf

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class YamlValidationFailure:
    path: Path
    parser: str
    error: str


def iter_yaml_files(root: Path = REPO_ROOT) -> Iterable[Path]:
    for path in sorted(root.rglob("*.yaml")):
        if _should_skip(path, root):
            continue
        yield path
    for path in sorted(root.rglob("*.yml")):
        if _should_skip(path, root):
            continue
        yield path


def _should_skip(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return relative.parts[:2] == ("frontend", "node_modules")


def classify_yaml_parser(path: Path, root: Path = REPO_ROOT) -> str:
    relative = path.relative_to(root)
    if relative.parts[:2] == (".github", "workflows"):
        return "pyyaml"
    return "omegaconf"


def validate_yaml_file(path: Path, root: Path = REPO_ROOT) -> None:
    parser_name = classify_yaml_parser(path, root)
    with path.open("r", encoding="utf-8") as handle:
        if parser_name == "pyyaml":
            yaml.safe_load(handle)
        else:
            OmegaConf.load(path)


def validate_repo_yaml(root: Path = REPO_ROOT) -> list[YamlValidationFailure]:
    failures: list[YamlValidationFailure] = []
    for path in iter_yaml_files(root):
        parser_name = classify_yaml_parser(path, root)
        try:
            validate_yaml_file(path, root)
        except Exception as exc:  # pragma: no cover - exercised through caller assertions
            failures.append(
                YamlValidationFailure(
                    path=path,
                    parser=parser_name,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return failures


def main() -> int:
    failures = validate_repo_yaml()
    if failures:
        for failure in failures:
            print(f"{failure.path} [{failure.parser}]")
            print(f"  {failure.error}")
        return 1
    print("YAML validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
