"""Telegram groups/chats you are a member of, read through your own account (Telethon).

Unlike t.me previews (channels only), this reaches the посёлок/СНТ/регион chats where people
actually ask questions — and every message carries the author's @username for a direct reply.
The account is authorised once by the owner: `manage.py telegram-login`. We only read.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from app.sources.base import Candidate, Source, SourceContext, SourceError, register

SESSION_DIR = Path(os.getenv("TELEGRAM_SESSION_DIR", "/data/telegram"))
SESSION_NAME = "account"


def session_path() -> Path:
    return SESSION_DIR / SESSION_NAME


def is_authorised() -> bool:
    return (SESSION_DIR / f"{SESSION_NAME}.session").exists()


@register
class TelegramChatSource(Source):
    """config: {"chats": ["@snt_chat", "https://t.me/…"], "keywords": [...], "limit_per_chat": 80}"""

    type = "telegram_chat"

    def fetch(self, ctx: SourceContext) -> list[Candidate]:
        try:
            from telethon.sync import TelegramClient  # noqa: F401  (import here: optional dependency)
        except ImportError as exc:  # pragma: no cover - depends on the image
            raise SourceError("Не установлена библиотека telethon") from exc

        api_id = ctx.secrets.get("tg_api_id") or os.getenv("TELEGRAM_API_ID", "")
        api_hash = ctx.secrets.get("tg_api_hash") or os.getenv("TELEGRAM_API_HASH", "")
        if not (api_id and api_hash):
            raise SourceError("Нет api_id/api_hash Telegram: добавьте интеграцию «Telegram-аккаунт»")
        if not is_authorised():
            raise SourceError(
                "Аккаунт Telegram не авторизован: выполните на сервере "
                "docker compose run --rm worker python manage.py telegram-login"
            )
        chats = [c.strip() for c in ctx.config.get("chats", []) if c.strip()]
        if not chats:
            raise SourceError("Не заданы чаты")
        keywords = [k.lower() for k in ctx.config.get("keywords", []) if k.strip()]
        limit = int(ctx.config.get("limit_per_chat") or 80)
        since = (
            datetime(ctx.since.year, ctx.since.month, ctx.since.day, tzinfo=timezone.utc)
            if ctx.since else None
        )
        return asyncio.run(_collect(int(api_id), api_hash, chats, keywords, limit, since, ctx))


async def _collect(api_id: int, api_hash: str, chats, keywords, limit, since, ctx) -> list[Candidate]:
    from telethon import TelegramClient

    out: list[Candidate] = []
    client = TelegramClient(str(session_path()), api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise SourceError("Сессия Telegram устарела — выполните telegram-login заново")
        for chat in chats:
            ref = chat.replace("https://t.me/", "").lstrip("@").strip("/")
            try:
                entity = await client.get_entity(ref)
            except Exception as exc:
                ctx.log("warn", f"Telegram-чат @{ref}: {exc}")
                continue
            kept = total = 0
            async for msg in client.iter_messages(entity, limit=limit, offset_date=None):
                if since and msg.date and msg.date < since:
                    break  # messages come newest-first
                text = (msg.message or "").strip()
                total += 1
                if len(text) < 40:
                    continue
                if keywords and not any(k in text.lower() for k in keywords):
                    continue
                sender = await msg.get_sender() if msg.sender_id else None
                username = getattr(sender, "username", None)
                name = " ".join(filter(None, [getattr(sender, "first_name", ""),
                                              getattr(sender, "last_name", "")])).strip()
                out.append(Candidate(
                    url=f"https://t.me/{ref}/{msg.id}",
                    title=text.split("\n")[0][:140], text=text[:3000], source="telegram_chat",
                    platform="telegram", query=f"@{ref}",
                    posted_at=msg.date.date() if msg.date else None,
                    author=(f"@{username}" if username else name)[:200],
                    extra={"chat": ref, "message_id": msg.id,
                           "username": username or "", "user_id": msg.sender_id},
                ))
                kept += 1
            ctx.log("info", f"Telegram-чат @{ref}: {kept} подходящих из {total} сообщений")
    finally:
        await client.disconnect()
    return out
