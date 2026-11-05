from sqlalchemy import String, cast, func, literal, select, union_all
from sqlalchemy.orm import Session

from app.detection.models import AlertRecord
from app.incidents.models import Incident


def distribution(db: Session):
    alerts = select(literal("alerts"), AlertRecord.severity, AlertRecord.status, func.count()).group_by(
        AlertRecord.severity, AlertRecord.status,
    )
    incidents = select(literal("incidents"), Incident.severity, cast(Incident.status, String), func.count()).group_by(
        Incident.severity, Incident.status,
    )
    return db.execute(union_all(alerts, incidents)).all()
