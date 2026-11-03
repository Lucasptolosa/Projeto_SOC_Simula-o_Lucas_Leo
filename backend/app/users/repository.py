from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.users.models import User, UserRole, UserStatus


USER_WRITE_LOCK = 0x4D534F4355534552


def serialize_user_writes(db: Session) -> None:
    # Serializa alterações administrativas
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": USER_WRITE_LOCK})


def current_user(db: Session, user_id: UUID, *, lock: bool = False) -> User | None:
    query = select(User).where(User.id == user_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def active_admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(
        User.role == UserRole.ADMIN, User.status == UserStatus.ACTIVE,
    ))


def username_taken(db: Session, username: str, except_id: UUID | None = None) -> bool:
    query = select(User.id).where(User.username == username)
    if except_id is not None:
        query = query.where(User.id != except_id)
    return db.scalar(query) is not None


def list_users(
    db: Session, page: int, page_size: int,
    role: UserRole | None = None, status: UserStatus | None = None,
):
    filters = []
    if role is not None:
        filters.append(User.role == role)
    if status is not None:
        filters.append(User.status == status)
    total = db.scalar(select(func.count()).select_from(User).where(*filters))
    # Projeta campos públicos
    query = select(User.id, User.username, User.role, User.status).where(*filters)
    rows = db.execute(query.order_by(User.username.asc(), User.id.asc()).offset(
        (page - 1) * page_size,
    ).limit(page_size)).mappings().all()
    return total, rows
