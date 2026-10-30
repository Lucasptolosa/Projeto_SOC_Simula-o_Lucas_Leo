from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.authorization import require_roles
from app.db.session import get_session
from app.users import service
from app.users.models import User, UserRole
from app.users.schemas import CreateUserInput, PublicUser, UpdateUserInput
from app.users.schemas import UsersQuery
from app.core.pagination import Page


router = APIRouter(prefix="/users", tags=["Administração de Users"])
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
Database = Annotated[Session, Depends(get_session)]
RULE_ERRORS = {
    "inactive_author": (401, "Autenticação necessária."),
    "forbidden_author": (403, "Permissão insuficiente."),
    "not_found": (404, "Usuário não encontrado."),
    "self_edit": (403, "A alteração deve ser de outra conta."),
    "duplicate_username": (409, "Username já cadastrado."),
    "last_admin": (409, "O último ADMIN ativo deve ser preservado."),
    "already_inactive": (409, "Usuário já está inativo."),
}


def run_user_operation(db: Session, operation: Callable[[], User]) -> PublicUser:
    try:
        user = operation()
        result = PublicUser.model_validate(user)
        db.commit()
        return result
    except service.UserRuleError as error:
        db.rollback()
        status, detail = RULE_ERRORS[str(error)]
        raise HTTPException(status_code=status, detail=detail) from None
    except IntegrityError as error:
        db.rollback()
        if getattr(getattr(error.orig, "diag", None), "constraint_name", None) == "uq_users_username":
            raise HTTPException(status_code=409, detail="Username já cadastrado.") from None
        raise
    except Exception:
        db.rollback()
        raise


@router.post("", response_model=PublicUser, status_code=201)
def create_user(payload: CreateUserInput, author: Admin, db: Database):
    return run_user_operation(db, lambda: service.create_user(
        db, author.id, payload.username, payload.role, payload.password.get_secret_value(),
    ))


@router.get("", response_model=Page[PublicUser])
def list_users(params: Annotated[UsersQuery, Query()], author: Admin, db: Database):
    return service.list_users(db, params.page, params.page_size, params.role, params.status)


@router.patch("/{user_id}", response_model=PublicUser)
def update_user(user_id: UUID, payload: UpdateUserInput, author: Admin, db: Database):
    return run_user_operation(db, lambda: service.update_user(
        db, author.id, user_id, payload.model_dump(exclude_unset=True),
    ))


@router.post("/{user_id}/deactivate", response_model=PublicUser)
def deactivate_user(user_id: UUID, author: Admin, db: Database):
    return run_user_operation(db, lambda: service.deactivate_user(db, author.id, user_id))
