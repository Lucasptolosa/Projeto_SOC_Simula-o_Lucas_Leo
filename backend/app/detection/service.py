from sqlalchemy.orm import Session
from uuid import UUID

from app.detection import repository
from app.detection.models import DetectionRuleRecord, DetectionState
from app.detection.repository import lock_state
from app.detection.schemas import UpdateRuleInput
from app.detection.state import dump_state, load_state
from app.detection_engine import Log
from app.logs.schemas import DetectionSummary, LogInput, RejectedLog
from app.audit.service import append_audit
from app.users import repository as user_repository
from app.users.models import UserRole, UserStatus


class DetectionRuleError(ValueError):
    pass


def update_rule_status(db: Session, author_id: UUID, rule_id: str, status: str) -> DetectionRuleRecord:
    author = user_repository.current_user(db, author_id, lock=True)
    if author is None or author.status is not UserStatus.ACTIVE:
        raise DetectionRuleError("inactive_author")
    if author.role is not UserRole.ADMIN:
        raise DetectionRuleError("forbidden_author")
    status = UpdateRuleInput(status=status).status
    if rule_id not in {"DR01", "DR02", "DR03"}:
        raise DetectionRuleError("not_found")
    repository.lock_state(db)
    rule = repository.rule_by_id(db, rule_id)
    if rule is None:
        raise DetectionRuleError("not_found")
    if rule.status == status:
        return rule
    rule.status = status
    append_audit(db, author_id=author_id,
                 action="DETECTION_RULE_ACTIVATED" if status == "ACTIVE" else "DETECTION_RULE_DEACTIVATED",
                 entity_type="DETECTION_RULE", entity_id=rule.id)
    db.flush()
    return rule


def evaluate(db: Session, state: DetectionState, records: list[tuple[int, LogInput]]) -> DetectionSummary:
    engine = load_state(state.payload)
    rules = repository.rules(db)
    if {rule.id for rule in rules} != set(engine.rules):
        raise RuntimeError("Catálogo de detecção incompleto.")
    for rule in rules:
        engine.set_rule_status(rule.id, rule.status)
    logs = [Log(event_id=log.event_id, asset_id=str(log.asset_id),
                occurred_at=log.occurred_at, event_type=log.event_type.value,
                username=log.username) for _, log in records]
    positions = {log.event_id: position for position, log in records}
    result = engine.process_batch(logs)
    for alert in result.alerts:
        repository.save_alert(db, alert)
    repository.save_state(db, state, dump_state(engine))
    rejected = sorted([
        RejectedLog(position=positions[log.event_id], reason="out_of_order",
                    detail="Evento fora de ordem para detecção.")
        for log, _ in result.rejected_logs
    ], key=lambda item: item.position)
    return DetectionSummary(evaluated=len(result.accepted_logs), rejected=len(rejected),
                            rejections=rejected, alerts_created=len(result.alerts))
