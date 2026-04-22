import os
import secrets
import shutil

from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from .routes.external_routes import external_router
from .routes.operations_routes import operations_router

app = FastAPI()
MAX_REQUEST_BYTES = int(os.environ.get("WEBAPP_MAX_REQUEST_BYTES", str(5 * 1024 * 1024)))

DEFAULT_ORIGINS = [
    "http://localhost:8080",
    "http://localhost:8000",
    "http://localhost:5500",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:5500",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]


def get_allowed_origins():
    raw_origins = os.environ.get("WEBAPP_ALLOWED_ORIGINS")
    if not raw_origins:
        return DEFAULT_ORIGINS
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


API_KEY = os.environ.get("WEBAPP_API_KEY")
PUBLIC_PATHS = {
    "/healthz",
    "/readyz",
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            request_size = int(content_length)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "invalid content-length"})
        if request_size > MAX_REQUEST_BYTES:
            return JSONResponse(status_code=413, content={"detail": "request too large"})
    provided_key = request.headers.get("x-api-key")
    if API_KEY and not (provided_key and secrets.compare_digest(provided_key, API_KEY)):
        return JSONResponse(status_code=401, content={"detail": "invalid api key"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


app.include_router(external_router)
app.include_router(operations_router, prefix="/operations")


@app.on_event("startup")
async def startup_resources():
    from .routes.external_routes import get_resource_monitor

    try:
        get_resource_monitor()
    except Exception:
        # Readiness should reflect dependency failures; startup should stay non-fatal.
        pass


@app.on_event("shutdown")
async def shutdown_resources():
    from .routes.external_routes import shutdown_external_resources
    from .routes.operations_routes import shutdown_operations_resources

    shutdown_external_resources()
    shutdown_operations_resources()


def check_database_readiness():
    from sqlalchemy import text
    from ..shared.database.database import get_engine

    engine = get_engine()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def check_config_readiness():
    from .routes.external_routes import get_cfg

    get_cfg()


def check_rabbit_settings():
    from ..shared.rabbit_messenger import get_rabbit_settings

    get_rabbit_settings()


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    checks = {}
    failures = []

    for name, fn in [
        ("config", check_config_readiness),
        ("database", check_database_readiness),
        ("rabbitmq_env", check_rabbit_settings),
    ]:
        try:
            fn()
            checks[name] = "ok"
        except Exception as exc:
            checks[name] = f"error: {exc}"
            failures.append(name)

    checks["ffmpeg"] = "ok" if shutil.which("ffmpeg") else "missing"
    if checks["ffmpeg"] != "ok":
        failures.append("ffmpeg")

    if failures:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "checks": checks, "failures": failures},
        )

    return {"status": "ready", "checks": checks}


@app.get("/")
async def root():
    return {"message": "Hearthlight Real Time Backend"}
