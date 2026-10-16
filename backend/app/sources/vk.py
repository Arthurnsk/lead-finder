"""VK official API: newsfeed.search over all public posts. Free, needs a user access token."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings
from app.sources.base import Candidate, Source, SourceContext, SourceError, register

API = "https://api.vk.com/method/newsfeed.search"
# VK allows ~3 requests/second per token
MIN_INTERVAL = 0.4


@register
class VkSource(Source):
    type = "vk"

    def fetch(self, ctx: SourceContext) -> list[Candidate]:
        token = ctx.secrets.get("vk_token") or os.getenv("VK_TOKEN", "")
        if not token:
            raise SourceError("Нет VK-токена: добавьте интеграцию «VK token» в настройках организации")
        queries = [q for q in ctx.config.get("queries", []) if q.strip()]
        if ctx.since:
            start = datetime(ctx.since.year, ctx.since.month, ctx.since.day, tzinfo=timezone.utc)
        else:
            start = datetime.now(timezone.utc) - timedelta(days=30)

        out: list[Candidate] = []
        last = 0.0
        with httpx.Client(timeout=15.0) as client:
            for q in queries:
                wait = MIN_INTERVAL - (time.monotonic() - last)
                if wait > 0:
                    time.sleep(wait)
                last = time.monotonic()
                r = client.get(API, params={
                    "q": q, "count": min(200, ctx.max_per_query * 5), "extended": 1,
                    "start_time": int(start.timestamp()), "access_token": token, "v": settings.vk_api_version,
                })
                data = r.json()
                if "error" in data:
                    err = data["error"]
                    code, msg = err.get("error_code"), err.get("error_msg", "")
                    if code in (5, 27, 28):  # auth failed / wrong token type
                        raise SourceError(f"VK отклонил токен ({code}): {msg}")
                    ctx.log("warn", f"VK: «{q}»: ошибка {code} {msg}")
                    if code == 6:  # too many requests
                        time.sleep(1.5)
                    continue
                resp = data.get("response") or {}
                names = _author_names(resp)
                items = resp.get("items") or []
                for it in items:
                    text = (it.get("text") or "").strip()
                    if not text:
                        continue
                    owner, pid = it.get("owner_id"), it.get("id")
                    out.append(Candidate(
                        url=f"https://vk.com/wall{owner}_{pid}",
                        title=text.split("\n", 1)[0][:140],
                        text=text[:3000],
                        source=self.type,
                        platform="vk",
                        query=q,
                        posted_at=datetime.fromtimestamp(it.get("date", 0), timezone.utc).date(),
                        author=names.get(it.get("from_id") or owner, ""),
                        extra={"owner_id": owner, "from_id": it.get("from_id")},
                    ))
                ctx.log("info", f"VK: «{q}» → {len(items)} постов")
        return out


def _author_names(resp: dict) -> dict[int, str]:
    names: dict[int, str] = {}
    for p in resp.get("profiles") or []:
        names[p["id"]] = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    for g in resp.get("groups") or []:
        names[-g["id"]] = g.get("name", "")
    return names
