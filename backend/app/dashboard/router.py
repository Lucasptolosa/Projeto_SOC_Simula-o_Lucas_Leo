from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.authorization import require_roles
from app.dashboard.service import DashboardSummary, summarize
from app.db.session import get_session
from app.users.models import User, UserRole


router = APIRouter(tags=["Dashboard"])
Analyst = Annotated[User, Depends(require_roles(UserRole.ANALYST))]
Database = Annotated[Session, Depends(get_session)]


@router.get("/dashboard", response_model=DashboardSummary)
def dashboard(_: Analyst, db: Database):
    return summarize(db)
