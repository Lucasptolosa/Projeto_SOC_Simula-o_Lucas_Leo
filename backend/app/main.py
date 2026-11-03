
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.auth.router import router as auth_router
from app.core.errors import server_error, validation_error

app = FastAPI(title="Mini SOC")
app.include_router(auth_router)
app.add_exception_handler(RequestValidationError, validation_error)


@app.middleware("http")
async def auth_no_cache(request, call_next):
    try:
        response = await call_next(request)
    except Exception as error:
        response = await server_error(request, error)
    if request.url.path.startswith("/auth/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/health")
def health():
    return {"status": "ok"}
