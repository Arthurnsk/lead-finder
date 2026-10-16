from fastapi import FastAPI, Request
from sqlalchemy import text

from app.api.v1 import auth, dashboard, diagnostics, leads, orgs, projects, runs, settings as settings_api
from app.config import settings
from app.db import engine

if settings.env == "prod" and (settings.secret_key == "change-me-in-prod" or len(settings.secret_key) < 32):
    raise RuntimeError("В prod задайте SECRET_KEY длиной ≥32 символов (python manage.py gen-key)")

app = FastAPI(
    title="Lead Finder API",
    version="1.0.0",
    docs_url="/api/docs" if settings.env != "prod" else None,
    openapi_url="/api/openapi.json" if settings.env != "prod" else None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/api/v1"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/api/health", tags=["system"])
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


for module in (auth, orgs, projects, runs, leads, dashboard, settings_api, diagnostics):
    app.include_router(module.router, prefix="/api/v1")
