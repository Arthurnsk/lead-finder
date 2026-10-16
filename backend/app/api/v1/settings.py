import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.deps import OrgContext, client_ip, csrf_protect, require_role
from app.engine.llm import NON_CHAT_RE, LlmClient
from app.engine.providers import PROVIDERS, detect_provider, key_warnings, mask_key
from app.engine.pipeline import fallback_config_for, llm_config_for
from app.models import AuditLog, Integration, LlmSettings, Project
from app.schemas import AuditOut, IntegrationIn, IntegrationOut, LlmSettingsIn, LlmSettingsOut, ProviderOut
from app.security import decrypt_json, encrypt_json

router = APIRouter(tags=["settings"], dependencies=[Depends(csrf_protect)])

REQUIRED = {"telegram": ("bot_token", "chat_id"), "webhook": ("url",), "vk_token": ("token",),
            "telegram_account": ("api_id", "api_hash")}


# ---------------------------------------------------------------- LLM


@router.get("/settings/llm/providers", response_model=list[ProviderOut])
def list_providers():
    """Known providers for the preset picker (no secrets involved)."""
    return [ProviderOut(**p.public()) for p in PROVIDERS]


@router.get("/settings/llm", response_model=LlmSettingsOut)
def get_llm(ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    cfg = llm_config_for(db, ctx.org.id)
    row = db.scalar(select(LlmSettings).where(LlmSettings.organization_id == ctx.org.id))
    provider = detect_provider(cfg.base_url)
    key = cfg.api_key if row and row.api_key_enc else ""
    if key == "local":
        key = ""
    warnings = key_warnings(provider, key)
    if not cfg.model:
        warnings.append("Модель не выбрана — берётся первая текстовая модель провайдера.")
    fb = fallback_config_for(db, ctx.org.id)
    fb_key = fb.api_key if fb and row and row.fallback_api_key_enc else ""
    return LlmSettingsOut(
        fallback_base_url=fb.base_url if fb else "",
        fallback_model=fb.model if fb else "",
        fallback_has_api_key=bool(fb_key and fb_key != "local"),
        fallback_key_hint=mask_key(fb_key if fb_key != "local" else ""),
        fallback_provider=ProviderOut(**detect_provider(fb.base_url).public()) if fb else None,
        base_url=cfg.base_url,
        model=cfg.model,
        model_source="explicit" if cfg.model else "auto",
        has_api_key=bool(key),
        key_hint=mask_key(key),
        disable_thinking=cfg.disable_thinking,
        provider=ProviderOut(**provider.public()),
        warnings=warnings,
        is_org_override=bool(row and row.base_url),
    )


@router.put("/settings/llm", response_model=LlmSettingsOut)
def put_llm(body: LlmSettingsIn, request: Request, ctx: OrgContext = Depends(require_role("admin")),
            db: Session = Depends(get_db)):
    row = db.scalar(select(LlmSettings).where(LlmSettings.organization_id == ctx.org.id))
    if row is None:
        row = LlmSettings(organization_id=ctx.org.id)
        db.add(row)
    row.base_url, row.model, row.disable_thinking = body.base_url.strip(), body.model.strip(), body.disable_thinking
    if body.api_key is not None:
        row.api_key_enc = encrypt_json({"api_key": body.api_key}) if body.api_key else ""
    row.fallback_base_url = body.fallback_base_url.strip()
    row.fallback_model = body.fallback_model.strip()
    if body.fallback_api_key is not None:
        row.fallback_api_key_enc = encrypt_json({"api_key": body.fallback_api_key}) if body.fallback_api_key else ""
    audit(db, "settings.llm_updated", org_id=ctx.org.id, user_id=ctx.user.id,
          data={"base_url": row.base_url, "model": row.model}, ip=client_ip(request))
    db.commit()
    return get_llm(ctx, db)


@router.get("/settings/llm/models")
def list_models(which: str = Query("primary", pattern="^(primary|fallback)$"),
                ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    """Model ids the configured provider serves (chat models first)."""
    cfg = fallback_config_for(db, ctx.org.id) if which == "fallback" else llm_config_for(db, ctx.org.id)
    if cfg is None:
        return {"ok": False, "error": "Резервная модель не настроена", "models": []}
    client = LlmClient(cfg, timeout=30)
    try:
        served = [m.id for m in client.client.models.list().data]
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "models": []}
    chat = [m for m in served if not NON_CHAT_RE.search(m)]
    other = [m for m in served if NON_CHAT_RE.search(m)]
    return {"ok": True, "models": chat + other, "chat_models": chat}


@router.post("/settings/llm/test")
def test_llm(which: str = Query("primary", pattern="^(primary|fallback)$"),
             ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    cfg = fallback_config_for(db, ctx.org.id) if which == "fallback" else llm_config_for(db, ctx.org.id)
    if cfg is None:
        return {"ok": False, "error": "Резервная модель не настроена", "base_url": "", "provider": "—"}
    provider = detect_provider(cfg.base_url)
    client = LlmClient(cfg, timeout=60)
    base = {"base_url": client.base_url, "provider": provider.label}
    ok, why = client.health()
    if not ok:
        return {**base, "ok": False, "error": why}
    t0 = time.monotonic()
    try:
        reply = client.chat("Ответь одним словом.", "Скажи: работает", max_tokens=20)
    except Exception as exc:
        return {**base, "ok": False, "error": str(exc)[:300]}
    return {**base, "ok": True, "model": client.model, "reply": reply[:100],
            "latency_ms": int((time.monotonic() - t0) * 1000)}


# ---------------------------------------------------------------- integrations


def _mask(v: str) -> str:
    return v[:4] + "…" + v[-3:] if len(v) > 10 else "•••"


def _out(row: Integration) -> IntegrationOut:
    cfg = decrypt_json(row.config_enc)
    summary = {
        "telegram": lambda: f"chat {cfg.get('chat_id')} · бот {_mask(cfg.get('bot_token', ''))}",
        "webhook": lambda: cfg.get("url", ""),
        "vk_token": lambda: f"токен {_mask(cfg.get('token', ''))}",
        "telegram_account": lambda: f"api_id {cfg.get('api_id', '')} · hash {_mask(cfg.get('api_hash', ''))}",
    }[row.type]()
    return IntegrationOut(id=row.id, type=row.type, project_id=row.project_id, enabled=row.enabled, summary=summary)


@router.get("/integrations", response_model=list[IntegrationOut])
def list_integrations(ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Integration).where(Integration.organization_id == ctx.org.id)
                      .order_by(Integration.created_at)).all()
    return [_out(r) for r in rows]


@router.post("/integrations", response_model=IntegrationOut, status_code=201)
def add_integration(body: IntegrationIn, request: Request, ctx: OrgContext = Depends(require_role("admin")),
                    db: Session = Depends(get_db)):
    missing = [k for k in REQUIRED[body.type] if not str(body.config.get(k, "")).strip()]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Не заполнено: {', '.join(missing)}")
    if body.type == "webhook" and not str(body.config["url"]).startswith("https://"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Webhook должен быть https://")
    if body.project_id and not db.scalar(select(Project.id).where(Project.id == body.project_id,
                                                                    Project.organization_id == ctx.org.id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if body.type in ("vk_token", "telegram_account"):  # one per org: replace
        for old in db.scalars(select(Integration).where(Integration.organization_id == ctx.org.id,
                                                        Integration.type == body.type)):
            db.delete(old)
    row = Integration(organization_id=ctx.org.id, project_id=body.project_id, type=body.type,
                      enabled=body.enabled, config_enc=encrypt_json({k: str(v).strip() for k, v in body.config.items()}))
    db.add(row)
    audit(db, "integration.added", org_id=ctx.org.id, user_id=ctx.user.id, entity="integration",
          entity_id=row.id, data={"type": body.type}, ip=client_ip(request))
    db.commit()
    return _out(row)


@router.patch("/integrations/{integration_id}", response_model=IntegrationOut)
def toggle_integration(integration_id: uuid.UUID, enabled: bool, request: Request,
                       ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    row = db.scalar(select(Integration).where(Integration.id == integration_id,
                                              Integration.organization_id == ctx.org.id))
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integration not found")
    row.enabled = enabled
    audit(db, "integration.toggled", org_id=ctx.org.id, user_id=ctx.user.id, entity="integration",
          entity_id=row.id, data={"enabled": enabled}, ip=client_ip(request))
    db.commit()
    return _out(row)


@router.delete("/integrations/{integration_id}", status_code=204)
def delete_integration(integration_id: uuid.UUID, request: Request,
                       ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    row = db.scalar(select(Integration).where(Integration.id == integration_id,
                                              Integration.organization_id == ctx.org.id))
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integration not found")
    db.delete(row)
    audit(db, "integration.deleted", org_id=ctx.org.id, user_id=ctx.user.id, entity="integration",
          entity_id=integration_id, ip=client_ip(request))
    db.commit()


# ---------------------------------------------------------------- audit


@router.get("/audit", response_model=list[AuditOut])
def list_audit(limit: int = Query(200, le=1000), ctx: OrgContext = Depends(require_role("admin")),
               db: Session = Depends(get_db)):
    return db.scalars(select(AuditLog).where(AuditLog.organization_id == ctx.org.id)
                      .order_by(AuditLog.ts.desc()).limit(limit)).all()
