from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Mapping, Iterator

from sqlalchemy import text
from sqlalchemy.schema import CreateSchema

from .database import get_engine, reset_engine
from ..models.SQLModels import Base
from ..utils.backoff import with_exponential_backoff

RUNTIME_SCHEMA = "runtime"
LEGACY_RUNTIME_SCHEMA = "dicos"


def _migrate_legacy_runtime_schema(connection) -> None:
    schema_rows = connection.execute(
        text(
            """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name IN (:runtime_schema, :legacy_schema)
            """
        ),
        {
            "runtime_schema": RUNTIME_SCHEMA,
            "legacy_schema": LEGACY_RUNTIME_SCHEMA,
        },
    ).fetchall()
    existing_schemas = {str(row[0]) for row in schema_rows}
    if LEGACY_RUNTIME_SCHEMA in existing_schemas and RUNTIME_SCHEMA not in existing_schemas:
        connection.execute(text(f'ALTER SCHEMA "{LEGACY_RUNTIME_SCHEMA}" RENAME TO "{RUNTIME_SCHEMA}"'))


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
            _migrate_legacy_runtime_schema(connection)
            connection.execute(CreateSchema(RUNTIME_SCHEMA, if_not_exists=True))
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
