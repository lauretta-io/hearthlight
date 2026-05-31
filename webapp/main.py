import ipaddress
import os
import secrets
import shutil
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from .routes.external_routes import MAX_UPLOAD_BYTES, external_router
from .routes.operations_routes import operations_router

app = FastAPI(
    title="Hearthlight API",
    version="0.8.1",
    description="Hearthlight control-plane and runtime management API.",
)
MAX_REQUEST_BYTES = int(os.environ.get("WEBAPP_MAX_REQUEST_BYTES", str(5 * 1024 * 1024)))
UPLOAD_REQUEST_PATHS = {
    "/sources/uploads",
    "/settings/input-sources/uploads",
}

DEFAULT_ORIGINS = [
    "http://localhost:8080",
    "http://localhost:8000",
    "http://localhost:5500",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3100",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:5500",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3100",
]
DEFAULT_LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


def get_allowed_origins():
    raw_origins = os.environ.get("WEBAPP_ALLOWED_ORIGINS")
    if not raw_origins:
        return DEFAULT_ORIGINS
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


def get_allowed_origin_regex():
    raw_regex = os.environ.get("WEBAPP_ALLOWED_ORIGIN_REGEX")
    if raw_regex is not None:
        return raw_regex.strip() or None
    return DEFAULT_LOCAL_ORIGIN_REGEX


API_KEY = os.environ.get("WEBAPP_API_KEY")
ALLOW_REMOTE_WITHOUT_API_KEY = os.environ.get("WEBAPP_ALLOW_REMOTE_WITHOUT_API_KEY", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LOCAL_STACK_MODE = os.environ.get("HEARTHLIGHT_LOCAL_STACK", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
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
    allow_origin_regex=get_allowed_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _is_loopback_host(value: str | None) -> bool:
    host = str(value or "").strip().strip("[]")
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _loopback_hosts_align(origin_host: str | None, host_name: str | None) -> bool:
    explicit_hosts = [host for host in (origin_host, host_name) if host]
    if not explicit_hosts:
        return False
    return all(_is_loopback_host(host) for host in explicit_hosts)


def _extract_hostname(header_value: str | None) -> str | None:
    raw_value = str(header_value or "").strip()
    if not raw_value:
        return None
    if "://" in raw_value:
        return urlparse(raw_value).hostname
    if raw_value.startswith("[") and "]" in raw_value:
        return raw_value[1 : raw_value.index("]")]
    return raw_value.split(":", 1)[0]


def _extract_forwarded_hosts(header_value: str | None) -> list[str]:
    raw_value = str(header_value or "").strip()
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def request_is_local_only(request: Request) -> bool:
    client_host = getattr(getattr(request, "client", None), "host", None)

    origin_host = _extract_hostname(request.headers.get("origin"))
    host_header = request.headers.get("host")
    host_name = _extract_hostname(host_header)
    has_explicit_hosts = bool(origin_host or host_name)

    if has_explicit_hosts:
        if not _loopback_hosts_align(origin_host, host_name):
            return False
        if LOCAL_STACK_MODE:
            return True

    if _is_loopback_host(client_host):
        return True

    real_ip = request.headers.get("x-real-ip")
    forwarded_hosts = _extract_forwarded_hosts(request.headers.get("x-forwarded-for"))
    if _is_loopback_host(real_ip) and forwarded_hosts and all(_is_loopback_host(host) for host in forwarded_hosts):
        return True

    return not has_explicit_hosts


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
        max_request_bytes = (
            MAX_UPLOAD_BYTES if request.url.path in UPLOAD_REQUEST_PATHS else MAX_REQUEST_BYTES
        )
        if request_size > max_request_bytes:
            return JSONResponse(status_code=413, content={"detail": "request too large"})
    provided_key = request.headers.get("x-api-key")
    if API_KEY and not (provided_key and secrets.compare_digest(provided_key, API_KEY)):
        return JSONResponse(status_code=401, content={"detail": "invalid api key"})
    if not API_KEY and not ALLOW_REMOTE_WITHOUT_API_KEY and not request_is_local_only(request):
        return JSONResponse(
            status_code=401,
            content={"detail": "remote API access requires WEBAPP_API_KEY"},
        )
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
