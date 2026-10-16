"""One page that answers «is the system healthy right now» — DB, worker, models, every source."""

from __future__ import annotations

import time
from datetime import timedelta

import feedparser
import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db, utcnow
from app.deps import OrgContext, require_role
from app.engine.enrich import UA
from app.engine.ru_tls import gov_ssl_context
from app.engine.llm import LlmClient
from app.engine.pipeline import fallback_config_for, llm_config_for
from app.engine.providers import detect_provider
from app.integrations.dispatch import org_secrets
from app.models import Heartbeat, Project, ProjectSource

router = APIRouter(prefix="/diagnostics", tags=["system"])


def _check(name: str, ok: bool, detail: str = "", ms: int | None = None, hint: str = "") -> dict:
    return {"name": name, "ok": ok, "detail": detail[:300], "ms": ms, "hint": hint}


def _timed(fn) -> tuple[bool, str, int]:
    t0 = time.monotonic()
    try:
        ok, detail = fn()
    except Exception as exc:  # a probe must never break the page
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    return ok, str(detail), int((time.monotonic() - t0) * 1000)


def probe_source(source: ProjectSource, secrets: dict) -> dict:
    cfg = source.config or {}
    label = f"{source.name or source.type}"

    def run() -> tuple[bool, str]:
        if source.type == "rss":
            feeds = cfg.get("feeds") or []
            if not feeds:
                return False, "не заданы ленты"
            r = httpx.get(feeds[0], timeout=15, follow_redirects=True, headers={"User-Agent": UA})
            n = len(feedparser.parse(r.content).entries)
            return n > 0, f"{len(feeds)} лент, первая отдала {n} записей"
        if source.type == "telegram":
            channels = cfg.get("channels") or []
            if not channels:
                return False, "не заданы каналы"
            r = httpx.get(f"https://t.me/s/{channels[0].lstrip('@')}", timeout=15,
                          headers={"User-Agent": UA})
            return r.status_code == 200, f"{len(channels)} каналов, t.me ответил {r.status_code}"
        if source.type == "vk":
            if not secrets.get("vk_token"):
                return False, "нет VK-токена (Настройки → Интеграции)"
            r = httpx.get("https://api.vk.com/method/users.get",
                          params={"access_token": secrets["vk_token"], "v": settings.vk_api_version}, timeout=15)
            data = r.json()
            if "error" in data:
                return False, f"VK: {data['error'].get('error_msg')}"
            return True, "токен принят"
        if source.type == "telegram_chat":
            from app.sources.telegram_chat import is_authorised

            if not (secrets.get("tg_api_id") and secrets.get("tg_api_hash")):
                return False, "нет api_id/api_hash (Настройки → Интеграции → Telegram-аккаунт)"
            if not is_authorised():
                return False, "аккаунт не авторизован: manage.py telegram-login"
            return True, f"{len(cfg.get('chats') or [])} чатов, сессия на месте"
        if source.type == "tenders":
            provider = (cfg.get("provider") or "torgi").lower()
            if provider == "torgi":
                r = httpx.get("https://torgi.gov.ru/new/api/public/lotcards/search",
                              params={"text": "земельный участок", "page": 0, "size": 1}, timeout=25,
                              headers={"User-Agent": UA}, verify=gov_ssl_context())
                n = len((r.json().get("content") or [])) if r.status_code == 200 else 0
                return n > 0, f"torgi.gov.ru ответил {r.status_code}, лотов на пробу: {n}"
            r = httpx.get("https://zakupki.gov.ru/epz/order/extendedsearch/rss.html",
                          params={"searchString": "кадастровые работы", "fz44": "on", "recordsPerPage": "_10"},
                          timeout=25, headers={"User-Agent": UA}, verify=gov_ssl_context())
            n = len(feedparser.parse(r.content).entries)
            return n > 0, f"zakupki.gov.ru ответил {r.status_code}, извещений: {n}"
        if source.type == "web_watch":
            pages = cfg.get("pages") or []
            if not pages:
                return False, "не заданы страницы"
            r = httpx.get(pages[0], timeout=25, follow_redirects=True, headers={"User-Agent": UA})
            return r.status_code == 200, f"{len(pages)} страниц, первая ответила {r.status_code}"
        if source.type in ("searxng", "ddg"):
            if source.type == "ddg":
                return True, "резервный источник, проверяется только при запуске"
            r = httpx.get(f"{settings.searxng_url.rstrip('/')}/search",
                          params={"q": "тест", "format": "json", "language": "ru"}, timeout=25)
            data = r.json()
            dead = [e[0] for e in data.get("unresponsive_engines") or []]
            n = len(data.get("results") or [])
            return n > 0, f"результатов {n}" + (f", не ответили: {', '.join(dead)}" if dead else "")
        return False, "неизвестный тип источника"

    ok, detail, ms = _timed(run)
    if source.fail_streak:
        detail = f"{detail}; подряд сбоев в запусках: {source.fail_streak}"
    return _check(label, ok, detail, ms,
                  hint="" if ok else "Источник не отдаёт данные — проверьте настройки или подождите")


@router.get("")
def diagnostics(ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    checks: list[dict] = []

    ok, detail, ms = _timed(lambda: (bool(db.execute(text("SELECT 1")).scalar()), "PostgreSQL отвечает"))
    checks.append(_check("База данных", ok, detail, ms))

    hb = db.get(Heartbeat, "worker")
    fresh = bool(hb and utcnow() - hb.ts < timedelta(minutes=2))
    checks.append(_check(
        "Worker (фоновые запуски)", fresh,
        f"последний сигнал: {hb.ts:%Y-%m-%d %H:%M:%S} UTC, состояние: {(hb.info or {}).get('state', '—')}"
        if hb else "сигналов не было",
        hint="" if fresh else "Worker не отвечает: docker compose up -d worker",
    ))

    for which, cfg in (("Основная модель", llm_config_for(db, ctx.org.id)),
                       ("Резервная модель", fallback_config_for(db, ctx.org.id))):
        if cfg is None:
            checks.append(_check(which, True, "не настроена (необязательно)"))
            continue
        client = LlmClient(cfg, timeout=30)
        ok, detail, ms = _timed(lambda c=client: (c.health()[0], f"{detect_provider(c.base_url).label}: {c.health()[1]}"))
        checks.append(_check(which, ok, detail, ms, hint="" if ok else "Проверьте адрес и ключ в Настройках → Модель"))

    secrets = org_secrets(db, ctx.org.id)
    projects = db.scalars(select(Project).where(Project.organization_id == ctx.org.id)).all()
    for project in projects:
        for source in project.sources:
            if not source.enabled:
                continue
            check = probe_source(source, secrets)
            check["name"] = f"{project.name} · {check['name']}"
            checks.append(check)

    return {"checked_at": utcnow().isoformat(), "ok": all(c["ok"] for c in checks), "checks": checks}
