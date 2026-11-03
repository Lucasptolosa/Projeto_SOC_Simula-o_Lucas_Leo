from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import Asset


def by_id(db: Session, asset_id: UUID) -> Asset | None:
    query = select(Asset).where(Asset.id == asset_id)
    return db.scalar(query.with_for_update().execution_options(populate_existing=True))
