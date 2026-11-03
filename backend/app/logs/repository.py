from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.assets.models import Asset
from app.logs.models import LogRecord
from app.logs.schemas import LogInput


def asset_exists(db: Session, asset_id: UUID) -> bool:
    query = select(Asset.id).where(Asset.id == asset_id)
    return db.scalar(query.with_for_update(read=True, key_share=True)) is not None


def insert_log(db: Session, log: LogInput) -> bool:
    statement = insert(LogRecord).values(**log.model_dump())
    statement = statement.on_conflict_do_nothing(index_elements=[LogRecord.event_id])
    return db.scalar(statement.returning(LogRecord.event_id)) is not None
