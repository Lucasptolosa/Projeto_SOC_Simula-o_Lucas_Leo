import logging
from datetime import datetime, timezone

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


logger = logging.getLogger("mini_soc.server")


async def validation_error(request: Request, error: RequestValidationError):
    if request.url.path.startswith(("/auth/", "/users")):
        return JSONResponse(
            status_code=422, content={"detail": "Requisição inválida."},
            headers={"Cache-Control": "no-store"},
        )
    return await request_validation_exception_handler(request, error)


async def server_error(request: Request, error: Exception):
    route = request.scope.get("route")
    operation = getattr(route, "path", "server")
    logger.error(
        "timestamp=%s operation=%s category=%s",
        datetime.now(timezone.utc).isoformat(), operation, type(error).__name__,
    )
    return JSONResponse(
        status_code=500, content={"detail": "Falha interna do servidor."},
        headers={"Cache-Control": "no-store"},
    )
