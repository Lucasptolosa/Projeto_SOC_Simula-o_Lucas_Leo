from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.incidents.models import Incident


def get(db: Session, incident_id: UUID) -> Incident | None:
    return db.scalar(select(Incident).where(Incident.id == incident_id))


def exists_for_alert(db: Session, alert_id: UUID) -> bool:
    return db.scalar(select(Incident.id).where(Incident.alert_id == alert_id)) is not None
