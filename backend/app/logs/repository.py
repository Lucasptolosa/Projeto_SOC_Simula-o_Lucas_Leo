from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.assets.models import Asset
from app.logs.models import LogRecord
from app.logs.schemas import LogInput, LogsQuery


def asset_exists(db: Session, asset_id: UUID) -> bool:
    query = select(Asset.id).where(Asset.id == asset_id)
    return db.scalar(query.with_for_update(read=True, key_share=True)) is not None


def insert_log(db: Session, log: LogInput) -> bool:
    statement = insert(LogRecord).values(**log.model_dump())
    statement = statement.on_conflict_do_nothing(index_elements=[LogRecord.event_id])
    return db.scalar(statement.returning(LogRecord.event_id)) is not None


def list_logs(db: Session, params: LogsQuery) -> dict:
    conditions = []
    for field in ("asset_id", "event_type", "username"):
        value = getattr(params, field)
        if value is not None:
            conditions.append(getattr(LogRecord, field) == value)
    if params.occurred_from is not None:
        conditions.append(LogRecord.occurred_at >= params.occurred_from)
    if params.occurred_to is not None:
        conditions.append(LogRecord.occurred_at <= params.occurred_to)
    total = db.scalar(select(func.count()).select_from(LogRecord).where(*conditions))
    fields = (LogRecord.event_id, LogRecord.asset_id, LogRecord.occurred_at,
              LogRecord.event_type, LogRecord.username)
    items = db.execute(select(*fields).where(*conditions).order_by(
        LogRecord.occurred_at.desc(), LogRecord.event_id.asc(),
    ).offset((params.page - 1) * params.page_size).limit(params.page_size)).mappings().all()
    return dict(items=items, total=total, page=params.page, page_size=params.page_size)
