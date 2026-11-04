from sqlalchemy.orm import Session

from app.detection import repository
from app.detection.models import DetectionState
from app.detection.repository import lock_state
from app.detection.state import dump_state, load_state
from app.detection_engine import Log
from app.logs.schemas import DetectionSummary, LogInput, RejectedLog


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
