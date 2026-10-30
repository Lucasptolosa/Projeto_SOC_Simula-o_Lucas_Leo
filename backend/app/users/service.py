from uuid import UUID

from sqlalchemy.orm import Session

from app.audit.service import append_audit
from app.auth.service import revoke_user_sessions, utc_now
from app.core.passwords import hash_password
from app.users import repository
from app.users.models import User, UserRole, UserStatus


class UserRuleError(ValueError):
    pass


def authorize_write(db: Session, author_id: UUID) -> User:
    repository.serialize_user_writes(db)
    author = repository.current_user(db, author_id)
    if author is None or author.status is not UserStatus.ACTIVE:
        raise UserRuleError("inactive_author")
    if author.role is not UserRole.ADMIN:
        raise UserRuleError("forbidden_author")
    return author


def target_user(db: Session, user_id: UUID) -> User:
    user = repository.current_user(db, user_id, lock=True)
    if user is None:
        raise UserRuleError("not_found")
    return user


def protect_last_admin(db: Session, user: User) -> None:
    if user.role is UserRole.ADMIN and user.status is UserStatus.ACTIVE and repository.active_admins(db) <= 1:
        raise UserRuleError("last_admin")


def create_user(db: Session, author_id: UUID, username: str, role: UserRole, password: str) -> User:
    authorize_write(db, author_id)
    if repository.username_taken(db, username):
        raise UserRuleError("duplicate_username")
    user = User(username=username, role=role, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    append_audit(db, author_id=author_id, action="USER_CREATED", entity_type="USER", entity_id=str(user.id))
    db.flush()
    return user


def update_user(db: Session, author_id: UUID, user_id: UUID, changes: dict) -> User:
    authorize_write(db, author_id)
    user = target_user(db, user_id)
    if user_id == author_id:
        raise UserRuleError("self_edit")
    old_role = user.role
    new_role = changes.get("role", old_role)
    username = changes.get("username", user.username)
    if new_role != old_role:
        protect_last_admin(db, user)
    if repository.username_taken(db, username, user_id):
        raise UserRuleError("duplicate_username")
    if username == user.username and new_role == old_role:
        return user
    user.username = username
    user.role = new_role
    append_audit(
        db, author_id=author_id, action="USER_UPDATED", entity_type="USER", entity_id=str(user.id),
        old_role=old_role if new_role != old_role else None,
        new_role=new_role if new_role != old_role else None,
    )
    db.flush()
    return user


def deactivate_user(db: Session, author_id: UUID, user_id: UUID) -> User:
    authorize_write(db, author_id)
    user = target_user(db, user_id)
    if user.status is UserStatus.INACTIVE:
        raise UserRuleError("already_inactive")
    protect_last_admin(db, user)
    user.status = UserStatus.INACTIVE
    revoke_user_sessions(db, user.id, utc_now())
    append_audit(db, author_id=author_id, action="USER_DEACTIVATED", entity_type="USER", entity_id=str(user.id))
    db.flush()
    return user
