from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.detection.models import AlertLog, AlertRecord, DetectionRuleRecord, DetectionState
from app.detection_engine import Alert


def lock_state(db: Session) -> DetectionState:
    row = db.scalar(select(DetectionState).where(DetectionState.id == 1)
                    .with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise RuntimeError("Estado de detecção não inicializado.")
    return row


def rules(db: Session) -> list[DetectionRuleRecord]:
    return list(db.scalars(select(DetectionRuleRecord).order_by(DetectionRuleRecord.id)
                           .with_for_update().execution_options(populate_existing=True)))


def rule_by_id(db: Session, rule_id: str) -> DetectionRuleRecord | None:
    return db.scalar(select(DetectionRuleRecord).where(DetectionRuleRecord.id == rule_id)
                     .with_for_update().execution_options(populate_existing=True))


def save_alert(db: Session, alert: Alert) -> None:
    row = AlertRecord(rule_id=alert.rule_id, asset_id=UUID(alert.asset_id),
                      username=alert.username, trigger_event_id=alert.related_logs[-1].event_id,
                      severity=alert.severity, created_at=alert.created_at, status=alert.status)
    db.add(row)
    db.flush()
    db.add_all([AlertLog(alert_id=row.id, event_id=log.event_id, position=position)
                for position, log in enumerate(alert.related_logs, start=1)])


def save_state(db: Session, state: DetectionState, payload: dict) -> None:
    state.payload = payload
    db.flush()
