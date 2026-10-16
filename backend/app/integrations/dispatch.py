"""Deliver new leads: Telegram bot message and/or signed webhook (e.g. into a CRM)."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import uuid

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Integration, Lead, Project
from app.security import decrypt_json


def org_secrets(db: Session, org_id: uuid.UUID) -> dict:
    """Org-wide secrets consumed by sources (VK token, Telegram account credentials)."""
    out: dict = {}
    rows = db.scalars(select(Integration).where(
        Integration.organization_id == org_id, Integration.enabled,
        Integration.type.in_(["vk_token", "telegram_account"]),
    )).all()
    for row in rows:
        cfg = decrypt_json(row.config_enc)
        if row.type == "vk_token":
            out["vk_token"] = cfg.get("token", "")
        elif row.type == "telegram_account":
            out["tg_api_id"] = cfg.get("api_id", "")
            out["tg_api_hash"] = cfg.get("api_hash", "")
    return out


def lead_payload(lead: Lead, project: Project) -> dict:
    return {
        "id": str(lead.id), "project": project.slug, "project_name": project.name, "url": lead.url,
        "source": lead.source, "platform": lead.platform, "score": lead.score, "segment": lead.segment,
        "interest": lead.interest_signal, "reason": lead.reason, "title": lead.title, "text": lead.text[:1000],
        "posted_at": lead.posted_at.isoformat() if lead.posted_at else None,
        "found_at": lead.found_at.isoformat() if lead.found_at else None, "contacts": lead.contacts,
    }


def telegram_text(p: dict) -> str:
    e = lambda v: html.escape(str(v or ""))  # noqa: E731
    lines = [f"🟢 <b>{int(p['score'] * 100)}%</b> · {e(p['project_name'])} · {e(p['platform'])}"]
    if p["segment"]:
        lines.append(f"Сегмент: {e(p['segment'])}")
    lines.append(f"Интерес: {e(p['interest'] or '—')}")
    lines.append(f"Почему: {e(p['reason'])}")
    if p["posted_at"]:
        lines.append(f"Дата поста: {e(p['posted_at'])}")
    lines.append(f"\n<i>{e(p['text'][:400])}</i>")
    lines.append(f'\n<a href="{e(p["url"])}">Открыть источник</a>')
    return "\n".join(lines)


def send_telegram(cfg: dict, payload: dict) -> None:
    r = httpx.post(
        f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
        json={"chat_id": cfg["chat_id"], "text": telegram_text(payload), "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=10.0,
    )
    r.raise_for_status()


def send_webhook(cfg: dict, payload: dict) -> None:
    body = json.dumps({"event": "lead.created", "lead": payload}, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json"}
    if cfg.get("secret"):
        headers["X-LeadFinder-Signature"] = hmac.new(cfg["secret"].encode(), body, hashlib.sha256).hexdigest()
    httpx.post(cfg["url"], content=body, headers=headers, timeout=10.0).raise_for_status()


SENDERS = {"telegram": send_telegram, "webhook": send_webhook}


def dispatch_lead(db: Session, lead: Lead, project: Project, log) -> None:
    rows = db.scalars(select(Integration).where(
        Integration.organization_id == project.organization_id,
        Integration.enabled,
        Integration.type.in_(SENDERS),
        or_(Integration.project_id.is_(None), Integration.project_id == project.id),
    )).all()
    if not rows:
        return
    payload = lead_payload(lead, project)
    for row in rows:
        try:
            SENDERS[row.type](decrypt_json(row.config_enc), payload)
        except Exception as exc:  # delivery failures are logged, never fail the run
            log("warn", f"  доставка {row.type} не удалась: {exc}")
