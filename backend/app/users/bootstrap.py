from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.passwords import hash_password
from app.users.models import User, UserRole, UserStatus


class BootstrapError(ValueError):
    pass


def create_initial_admin(session: Session, username: str, password: str) -> User:
    # Serializa a instalação
    session.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
    if session.scalar(select(User.id).limit(1)) is not None:
        raise BootstrapError("Instalação já inicializada; nenhum usuário foi alterado.")

    user = User(
        username=username, role=UserRole.ADMIN, status=UserStatus.ACTIVE,
        password_hash=hash_password(password),
    )
    session.add(user)
    session.flush()
    return user
