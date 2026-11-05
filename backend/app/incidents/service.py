from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.audit.service import append_audit
from app.incidents import repository
from app.incidents.models import Incident
from app.incidents.schemas import IncidentsQuery, TransitionInput
from app.incidents.transitions import IncidentStatus, validate_transition
from app.investigations import service as investigations
from app.investigations.rules import InvestigationRuleError, validate_escalation_eligibility


def escalate(db: Session, author_id: UUID, investigation_id: UUID) -> Incident:
    author = investigations.authorize(db, author_id, lock=True)
    _, alert = investigations.context(db, investigation_id, lock=True)
    validate_escalation_eligibility(alert.status, actor_role=author.role.value)
    if repository.exists_for_alert(db, alert.id):
        raise InvestigationRuleError("Incident já existente.")
    now = datetime.now(timezone.utc)
    incident = Incident(alert_id=alert.id, analyst_id=author.id, severity=alert.severity,
                        status=IncidentStatus.OPEN, opened_at=now)
    db.add(incident)
    old_status = alert.status
    alert.status = "ESCALATED"
    append_audit(db, author_id=author.id, action="ALERT_ESCALATED", entity_type="ALERT",
                 entity_id=str(alert.id), old_status=old_status, new_status=alert.status,
                 occurred_at=now)
    db.flush()
    return incident


def get(db: Session, author_id: UUID, incident_id: UUID) -> Incident:
    investigations.authorize(db, author_id)
    incident = repository.get(db, incident_id)
    if incident is None:
        raise investigations.InvestigationServiceError("not_found")
    return incident


def list_incidents(db: Session, author_id: UUID, params: IncidentsQuery) -> dict:
    investigations.authorize(db, author_id)
    total, rows = repository.list_incidents(db, **params.model_dump())
    return dict(items=rows, total=total, page=params.page, page_size=params.page_size)


def transition(db: Session, author_id: UUID, incident_id: UUID, payload: TransitionInput) -> Incident:
    author = investigations.authorize(db, author_id, lock=True)
    incident = repository.get(db, incident_id, lock=True)
    if incident is None:
        raise investigations.InvestigationServiceError("not_found")
    target = validate_transition(
        incident.status, payload.target_status,
        containment_description=payload.containment_description,
        resolution_conclusion=payload.resolution_conclusion,
    )
    now = datetime.now(timezone.utc)
    old_status = incident.status
    if target is IncidentStatus.CONTAINED:
        incident.containment_description = payload.containment_description
        incident.contained_by, incident.contained_at = author.id, now
    elif target is IncidentStatus.RESOLVED:
        incident.resolution_conclusion = payload.resolution_conclusion
        incident.resolved_by, incident.resolved_at = author.id, now
    incident.status = target
    append_audit(db, author_id=author.id, action="INCIDENT_STATUS_CHANGED", entity_type="INCIDENT",
                 entity_id=str(incident.id), old_status=old_status.value, new_status=target.value,
                 occurred_at=now)
    db.flush()
    return incident
