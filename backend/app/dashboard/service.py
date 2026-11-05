from typing import get_args

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.alerts.schemas import AlertStatus, Severity
from app.dashboard import repository
from app.incidents.transitions import IncidentStatus


class Distribution(BaseModel):
    severity: dict[str, int]
    status: dict[str, int]


class DashboardSummary(BaseModel):
    alerts: Distribution
    incidents: Distribution


def summarize(db: Session) -> DashboardSummary:
    groups = {
        "alerts": Distribution(severity=dict.fromkeys(get_args(Severity), 0), status=dict.fromkeys(get_args(AlertStatus), 0)),
        "incidents": Distribution(severity=dict.fromkeys(get_args(Severity), 0), status=dict.fromkeys(IncidentStatus, 0)),
    }
    for entity, severity, status, count in repository.distribution(db):
        groups[entity].severity[severity] += count
        groups[entity].status[status] += count
    return DashboardSummary(**groups)
