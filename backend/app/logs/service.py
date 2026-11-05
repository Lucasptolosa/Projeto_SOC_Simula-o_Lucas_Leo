from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.logs import repository
from app.logs.schemas import ImportSummary, LogInput, LogsQuery, RejectedLog
from app.users import repository as user_repository
from app.users.models import UserRole, UserStatus
from app.detection import service as detection_service


class LogImportError(ValueError):
    pass


class LogQueryError(ValueError):
    pass


def list_logs(db: Session, author_id: UUID, params: LogsQuery) -> dict:
    author = user_repository.current_user(db, author_id)
    if author is None or author.status is not UserStatus.ACTIVE:
        raise LogQueryError("inactive_author")
    if author.role not in {UserRole.ADMIN, UserRole.ANALYST}:
        raise LogQueryError("forbidden_author")
    return repository.list_logs(db, params)


def authorize_import(db: Session, author_id: UUID) -> None:
    author = user_repository.current_user(db, author_id, lock=True)
    if author is None or author.status is not UserStatus.ACTIVE:
        raise LogImportError("inactive_author")
    if author.role is not UserRole.ADMIN:
        raise LogImportError("forbidden_author")


def validation_rejection(position: int, error: ValidationError) -> RejectedLog:
    first = error.errors(include_input=False, include_context=False, include_url=False)[0]
    field = first["loc"][0] if first["loc"] else None
    if field in LogInput.model_fields:
        return RejectedLog(position=position, reason=f"invalid_{field}",
                           detail=f"Campo {field} inválido ou ausente.")
    return RejectedLog(position=position, reason="invalid_record",
                       detail="Formato inválido ou campos desconhecidos.")


def import_logs(db: Session, author_id: UUID, records: list) -> ImportSummary:
    authorize_import(db, author_id)
    if not 1 <= len(records) <= 1000:
        raise LogImportError("invalid_batch_size")
    state = detection_service.lock_state(db)
    accepted = 0
    inserted = []
    rejected = []
    for position, record in enumerate(records, start=1):
        try:
            log = LogInput.model_validate(record)
        except ValidationError as error:
            rejected.append(validation_rejection(position, error))
            continue
        if not repository.asset_exists(db, log.asset_id):
            rejected.append(RejectedLog(position=position, reason="asset_not_found",
                                         detail="Asset não encontrado."))
        elif not repository.insert_log(db, log):
            rejected.append(RejectedLog(position=position, reason="duplicate_event_id",
                                         detail="event_id já persistido."))
        else:
            accepted += 1
            inserted.append((position, log))
    detection = detection_service.evaluate(db, state, inserted)
    return ImportSummary(accepted=accepted, rejected=len(rejected), rejections=rejected,
                         detection=detection)
