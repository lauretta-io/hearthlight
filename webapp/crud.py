from datetime import datetime
from typing import Type, List, Any

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session


async def create(db: Session, model: Type[BaseModel], data: dict) -> Any:
    db_model = model(**data)
    db.add(db_model)
    db.commit()
    db.refresh(db_model)
    return db_model


async def get(db: Session, model: Type[BaseModel], id: int) -> Any:
    db_model = db.get(model, id)
    return db_model


async def update(db: Session, item: Any, data: dict) -> Any:
    for key, value in data.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


async def delete(db: Session, item: Any) -> Any:
    item.is_deleted = True
    item.deleted_at = datetime.now().isoformat()
    db.commit()


async def get_all(db: Session, model: Type[BaseModel]) -> List[Any]:
    return db.query(model).all()


async def delete_id(db: Session, model: Any, id: int):
    item = db.get(model, id)
    if not item:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(item)
    db.commit()
