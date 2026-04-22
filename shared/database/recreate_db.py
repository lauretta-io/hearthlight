from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Mapping, Iterator

from sqlalchemy.schema import CreateSchema

from .database import get_engine, reset_engine
from ..models.SQLModels import Base
from ..utils.backoff import with_exponential_backoff


@contextmanager
def _patched_environ(overrides: Mapping[str, str] | None) -> Iterator[None]:
    if not overrides:
        yield
        return

    original: dict[str, str | None] = {key: os.environ.get(key) for key in overrides}
    for key, value in overrides.items():
        os.environ[key] = value
    try:
        yield
    finally:
        for key, prior in original.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior


@with_exponential_backoff(max_tries=10, max_delay=2)
def reset_db(
    env_overrides: Mapping[str, str] | None = None,
    output_dir: str | Path = "output",
) -> None:
    with _patched_environ(env_overrides):
        reset_engine()
        engine = get_engine()
        with engine.connect() as connection:
            connection.execute(CreateSchema("dicos", if_not_exists=True))
            connection.execute(CreateSchema("control", if_not_exists=True))
            connection.commit()

        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        engine.dispose()
        reset_engine()

    output_path = Path(output_dir)
    if output_path.exists():
        shutil.rmtree(output_path)


if __name__ == "__main__":
    reset_db()
