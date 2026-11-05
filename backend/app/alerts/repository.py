from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.schemas import AlertsQuery
from app.detection.models import AlertLog, AlertRecord
from app.logs.models import LogRecord


FIELDS = (AlertRecord.id, AlertRecord.rule_id, AlertRecord.asset_id, AlertRecord.username,
          AlertRecord.severity, AlertRecord.status, AlertRecord.created_at)


def list_alerts(db: Session, params: AlertsQuery) -> dict:
    conditions = []
    for field in ("severity", "status", "asset_id", "rule_id"):
        value = getattr(params, field)
        if value is not None:
            conditions.append(getattr(AlertRecord, field) == value)
    if params.created_from is not None:
        conditions.append(AlertRecord.created_at >= params.created_from)
    if params.created_to is not None:
        conditions.append(AlertRecord.created_at <= params.created_to)
    total = db.scalar(select(func.count()).select_from(AlertRecord).where(*conditions))
    rows = db.execute(select(*FIELDS).where(*conditions).order_by(
        AlertRecord.created_at.desc(), AlertRecord.id.asc(),
    ).offset((params.page - 1) * params.page_size).limit(params.page_size)).mappings().all()
    return dict(items=rows, total=total, page=params.page, page_size=params.page_size)


def alert(db: Session, alert_id: UUID):
    return db.execute(select(*FIELDS).where(AlertRecord.id == alert_id)).mappings().one_or_none()


def evidence(db: Session, alert_id: UUID):
    return db.execute(select(*LogRecord.__table__.columns).join(
        AlertLog, AlertLog.event_id == LogRecord.event_id,
    ).where(AlertLog.alert_id == alert_id).order_by(AlertLog.position.asc())).mappings().all()
