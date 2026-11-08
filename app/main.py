from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text

from app.api.routes import router
from app.config import get_settings
from app.db import engine

settings = get_settings()

app = FastAPI(
    title="Memoirs Evidence Extraction Demo",
    version="0.1.0",
)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


@app.get("/health/ready")
def readiness() -> JSONResponse:
    checks: dict[str, str] = {}

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    try:
        client = Redis.from_url(settings.celery_broker_url, socket_connect_timeout=1)
        client.ping()
        checks["broker"] = "ok"
    except Exception:
        checks["broker"] = "unavailable"

    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ok" if ready else "degraded", "checks": checks},
    )
