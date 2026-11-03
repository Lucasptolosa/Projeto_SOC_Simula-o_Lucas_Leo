from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException

from app.auth.dependencies import get_current_user
from app.users.models import User, UserRole


def require_roles(*roles: UserRole) -> Callable[..., User]:
    # Permissões explícitas obrigatórias
    if not roles or any(not isinstance(role, UserRole) for role in roles):
        raise ValueError("Informe pelo menos um UserRole válido.")
    allowed = frozenset(roles)

    def authorize(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="Permissão insuficiente.")
        return user

    return authorize
