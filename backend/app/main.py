
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

from app.auth.router import router as auth_router
from app.users.router import router as users_router
from app.audit.router import router as audit_router
from app.assets.router import router as assets_router
from app.logs.router import router as logs_router
from app.investigations.router import router as investigations_router
from app.incidents.router import router as incidents_router
from app.detection.router import router as detection_rules_router
from app.alerts.router import router as alerts_router
from app.core.errors import server_error, validation_error
from app.web.router import DIRECTORY, router as web_router

app = FastAPI(title="Mini SOC")
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(audit_router)
app.include_router(assets_router)
app.include_router(logs_router)
app.include_router(investigations_router)
app.include_router(incidents_router)
app.include_router(detection_rules_router)
app.include_router(alerts_router)
app.include_router(web_router)
app.mount("/static", StaticFiles(directory=DIRECTORY / "static"), name="static")
app.add_exception_handler(RequestValidationError, validation_error)


@app.middleware("http")
async def auth_no_cache(request, call_next):
    try:
        response = await call_next(request)
    except Exception as error:
        response = await server_error(request, error)
    if request.url.path.startswith(("/auth/", "/users", "/audit-logs", "/assets", "/logs", "/investigations", "/incidents", "/detection-rules", "/alerts")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    if request.url.path in {"/", "/login", "/app"} or request.url.path.startswith(("/app/", "/static/")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/health")
def health():
    return {"status": "ok"}
