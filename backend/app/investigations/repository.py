from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.detection.models import AlertRecord
from app.incidents.models import Incident
from app.investigations.models import Investigation, Observation


def alert(db: Session, alert_id: UUID, *, lock: bool = False) -> AlertRecord | None:
    query = select(AlertRecord).where(AlertRecord.id == alert_id)
    if lock:
        query = query.with_for_update()
    return db.scalar(query.execution_options(populate_existing=True))


def investigation(db: Session, investigation_id: UUID) -> Investigation | None:
    return db.scalar(select(Investigation).where(
        Investigation.id == investigation_id,
    ).execution_options(populate_existing=True))


def investigation_exists(db: Session, alert_id: UUID) -> bool:
    return db.scalar(select(Investigation.id).where(Investigation.alert_id == alert_id)) is not None


def incident_id(db: Session, alert_id: UUID) -> UUID | None:
    return db.scalar(select(Incident.id).where(Incident.alert_id == alert_id))


def observations(db: Session, investigation_id: UUID, page: int, page_size: int) -> dict:
    condition = Observation.investigation_id == investigation_id
    total = db.scalar(select(func.count()).select_from(Observation).where(condition))
    rows = db.scalars(select(Observation).where(condition).order_by(
        Observation.occurred_at, Observation.id,
    ).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": rows, "total": total, "page": page, "page_size": page_size}
