from uuid import UUID

from sqlalchemy.orm import Session

from app.assets import repository
from app.assets.models import Asset, AssetStatus, AssetType
from app.assets.schemas import CreateAssetInput, UpdateAssetInput
from app.audit.service import append_audit
from app.users import repository as user_repository
from app.users.models import UserRole, UserStatus


class AssetRuleError(ValueError):
    pass


def authorize_write(db: Session, author_id: UUID) -> None:
    user_repository.serialize_user_writes(db)
    author = user_repository.current_user(db, author_id)
    if author is None or author.status is not UserStatus.ACTIVE:
        raise AssetRuleError("inactive_author")
    if author.role is not UserRole.ADMIN:
        raise AssetRuleError("forbidden_author")


def target_asset(db: Session, asset_id: UUID) -> Asset:
    asset = repository.by_id(db, asset_id)
    if asset is None:
        raise AssetRuleError("not_found")
    return asset


def record_change(db: Session, author_id: UUID, asset: Asset, action: str) -> None:
    append_audit(db, author_id=author_id, action=action,
                 entity_type="ASSET", entity_id=str(asset.id))
    db.flush()


def create_asset(
    db: Session, author_id: UUID, name: str, kind: AssetType, status: AssetStatus,
) -> Asset:
    authorize_write(db, author_id)
    payload = CreateAssetInput(name=name, type=kind, status=status)
    asset = Asset(**payload.model_dump())
    db.add(asset)
    db.flush()
    record_change(db, author_id, asset, "ASSET_CREATED")
    return asset


def update_asset(db: Session, author_id: UUID, asset_id: UUID, changes: dict) -> Asset:
    authorize_write(db, author_id)
    changes = UpdateAssetInput.model_validate(changes).model_dump(exclude_unset=True)
    asset = target_asset(db, asset_id)
    if all(getattr(asset, field) == value for field, value in changes.items()):
        return asset
    for field, value in changes.items():
        setattr(asset, field, value)
    record_change(db, author_id, asset, "ASSET_UPDATED")
    return asset


def deactivate_asset(db: Session, author_id: UUID, asset_id: UUID) -> Asset:
    authorize_write(db, author_id)
    asset = target_asset(db, asset_id)
    if asset.status is AssetStatus.INACTIVE:
        return asset
    asset.status = AssetStatus.INACTIVE
    record_change(db, author_id, asset, "ASSET_DEACTIVATED")
    return asset
