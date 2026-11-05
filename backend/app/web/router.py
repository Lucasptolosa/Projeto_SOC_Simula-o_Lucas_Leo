from pathlib import Path
from typing import Annotated, get_args
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.alerts.schemas import AlertStatus, Severity
from app.auth.authorization import require_roles
from app.auth.dependencies import get_current_user
from app.dashboard.service import summarize
from app.db.session import get_session
from app.users.models import User, UserRole


DIRECTORY = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=DIRECTORY / "templates")


class PageRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def page_handler(request: Request):
            try:
                return await handler(request)
            except HTTPException as error:
                if error.status_code == 401:
                    return RedirectResponse("/login?reason=session", status_code=303)
                if error.status_code == 403:
                    return templates.TemplateResponse(request, "forbidden.html", status_code=403)
                raise

        return page_handler


router = APIRouter(route_class=PageRoute, include_in_schema=False)
CurrentUser = Annotated[User, Depends(get_current_user)]
Administrator = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
Analyst = Annotated[User, Depends(require_roles(UserRole.ANALYST))]
Database = Annotated[Session, Depends(get_session)]


def render_page(request: Request, user: User, page: str, title: str, **context):
    # Contexto público mínimo
    return templates.TemplateResponse(request, page + ".html", {
        "is_admin": user.role == UserRole.ADMIN, "is_analyst": user.role == UserRole.ANALYST,
        "page": page, "title": title, **context,
    })


@router.get("/")
def index():
    return RedirectResponse("/app", status_code=303)


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@router.get("/app")
def home_page(request: Request, user: CurrentUser):
    return render_page(request, user, "home", "Visão geral")


@router.get("/app/users")
def users_page(request: Request, user: Administrator):
    return render_page(request, user, "users", "Usuários")


@router.get("/app/audit-logs")
def audit_page(request: Request, user: Administrator):
    return render_page(request, user, "audit", "Registros de auditoria")


@router.get("/app/logs/import")
def import_logs_page(request: Request, user: Administrator):
    return render_page(request, user, "log-import", "Importar Logs")


@router.get("/app/incidents")
def incidents_page(request: Request, user: Analyst):
    return render_page(request, user, "incidents", "Incidents")


@router.get("/app/dashboard")
def dashboard_page(request: Request, user: Analyst, db: Database):
    return render_page(request, user, "dashboard", "Dashboard de segurança", counts=summarize(db))


@router.get("/app/incidents/{incident_id}")
def incident_page(request: Request, incident_id: UUID, user: Analyst):
    return render_page(request, user, "incident-detail", "Detalhe do Incident", incident_id=str(incident_id))


@router.get("/app/investigations")
def investigations_page(request: Request, user: Analyst, alert_id: UUID | None = None):
    return render_page(request, user, "investigations", "Investigations", initial_alert_id=alert_id)


@router.get("/app/alerts")
def alerts_page(request: Request, user: Analyst):
    return render_page(request, user, "alerts", "Alerts", severities=get_args(Severity), statuses=get_args(AlertStatus))


@router.get("/app/alerts/{alert_id}")
def alert_page(request: Request, alert_id: UUID, user: Analyst):
    return render_page(request, user, "alert-detail", "Detalhe do Alert", alert_id=str(alert_id))


@router.get("/app/investigations/{investigation_id}")
def investigation_page(request: Request, investigation_id: UUID, user: Analyst):
    return render_page(request, user, "investigation-detail", "Detalhe da Investigation",
                       investigation_id=str(investigation_id))
