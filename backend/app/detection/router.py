from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.authorization import require_roles
from app.db.session import get_session
from app.detection import service
from app.detection.schemas import PublicRule, UpdateRuleInput
from app.users.models import User, UserRole


router = APIRouter(prefix="/detection-rules", tags=["Administração de Detection Rules"])
RULE_ERRORS = {
    "inactive_author": (401, "Autenticação necessária."),
    "forbidden_author": (403, "Permissão insuficiente."),
    "not_found": (404, "Detection Rule não encontrada."),
}


@router.patch("/{rule_id}", response_model=PublicRule)
def update_rule(
    rule_id: str, payload: UpdateRuleInput,
    author: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_session)],
):
    try:
        result = PublicRule.model_validate(service.update_rule_status(db, author.id, rule_id, payload.status))
        db.commit()
        return result
    except service.DetectionRuleError as error:
        db.rollback()
        status, detail = RULE_ERRORS[str(error)]
        raise HTTPException(status_code=status, detail=detail) from None
    except Exception:
        db.rollback()
        raise
