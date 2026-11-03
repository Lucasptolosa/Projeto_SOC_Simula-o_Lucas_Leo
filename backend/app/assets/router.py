from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.assets import service
from app.assets.models import Asset
from app.assets.schemas import CreateAssetInput, PublicAsset, UpdateAssetInput
from app.auth.authorization import require_roles
from app.db.session import get_session
from app.users.models import User, UserRole


router = APIRouter(prefix="/assets", tags=["Administração de Assets"])
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
Database = Annotated[Session, Depends(get_session)]
RULE_ERRORS = {
    "inactive_author": (401, "Autenticação necessária."),
    "forbidden_author": (403, "Permissão insuficiente."),
    "not_found": (404, "Asset não encontrado."),
}


def run_asset_operation(db: Session, operation: Callable[[], Asset]) -> PublicAsset:
    try:
        result = PublicAsset.model_validate(operation())
        db.commit()
        return result
    except service.AssetRuleError as error:
        db.rollback()
        status, detail = RULE_ERRORS[str(error)]
        raise HTTPException(status_code=status, detail=detail) from None
    except Exception:
        db.rollback()
        raise


@router.post("", response_model=PublicAsset, status_code=201)
def create_asset(payload: CreateAssetInput, author: Admin, db: Database):
    return run_asset_operation(db, lambda: service.create_asset(
        db, author.id, payload.name, payload.type, payload.status,
    ))


@router.patch("/{asset_id}", response_model=PublicAsset)
def update_asset(asset_id: UUID, payload: UpdateAssetInput, author: Admin, db: Database):
    return run_asset_operation(db, lambda: service.update_asset(
        db, author.id, asset_id, payload.model_dump(exclude_unset=True),
    ))


@router.post("/{asset_id}/deactivate", response_model=PublicAsset)
def deactivate_asset(asset_id: UUID, author: Admin, db: Database):
    return run_asset_operation(db, lambda: service.deactivate_asset(db, author.id, asset_id))
