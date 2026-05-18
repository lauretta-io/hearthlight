from __future__ import annotations

import json
from typing import Any

from ..database.database import get_engine
from ..models import SQLModels

SETTING_KEY_APPEARANCE = "appearance"


def ensure_workspace_setting_tables() -> None:
    engine = get_engine()
    SQLModels.Base.metadata.create_all(
        bind=engine,
        tables=[SQLModels.WorkspaceSetting.__table__],
        checkfirst=True,
    )


def get_workspace_setting_row(db, setting_key: str):
    ensure_workspace_setting_tables()
    return (
        db.query(SQLModels.WorkspaceSetting)
        .filter_by(setting_key=setting_key, is_deleted=False)
        .order_by(SQLModels.WorkspaceSetting.id.asc())
        .first()
    )


def parse_workspace_setting_json(raw_value: Any, *, default: Any) -> Any:
    if raw_value in (None, ""):
        return default
    if isinstance(raw_value, (dict, list)):
        return raw_value
    try:
        return json.loads(str(raw_value))
    except Exception:
        return default


def get_workspace_setting_value(db, setting_key: str, *, default: Any) -> Any:
    row = get_workspace_setting_row(db, setting_key)
    if row is None:
        return default
    return parse_workspace_setting_json(getattr(row, "setting_value_json", None), default=default)


def set_workspace_setting_value(db, setting_key: str, value: Any):
    ensure_workspace_setting_tables()
    row = get_workspace_setting_row(db, setting_key)
    if row is None:
        row = SQLModels.WorkspaceSetting(setting_key=setting_key)
        db.add(row)
    row.setting_value_json = json.dumps(value, sort_keys=True)
    row.is_deleted = False
    row.deleted_at = None
    db.flush()
    return row
