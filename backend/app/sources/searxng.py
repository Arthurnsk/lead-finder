"""Self-hosted SearXNG metasearch (JSON API). Several engines, so one being blocked doesn't kill the run."""

from __future__ import annotations

import time
from datetime import datetime

import httpx

from app.config import settings
from app.engine.dates import extract_post_date
from app.sources.base import Candidate, Source, SourceContext, SourceError, platform_for, register

TIME_RANGE = {"d": "day", "w": "week", "m": "month", "y": "year"}
# From one IP most engines rate-limit or CAPTCHA quickly; Brave gives relevant dated results if paced.
DEFAULT_ENGINES = "brave,duckduckgo,mojeek,startpage"
DEFAULT_INTERVAL_SEC = 8.0


@register
class SearxngSource(Source):
    type = "searxng"

    def fetch(self, ctx: SourceContext) -> list[Candidate]:
        base = (ctx.config.get("url") or settings.searxng_url).rstrip("/")
        queries = [q for q in ctx.config.get("queries", []) if q.strip()]
        lang = ctx.region.split("-")[0] if ctx.region else "ru"
        engines = ctx.config.get("engines") or DEFAULT_ENGINES
        interval = float(ctx.config.get("interval_sec") or DEFAULT_INTERVAL_SEC)
        out: list[Candidate] = []
        with httpx.Client(timeout=20.0) as client:
            for q in queries:
                params = {"q": q, "format": "json", "language": lang, "safesearch": 0, "engines": engines}
                if ctx.timelimit in TIME_RANGE:
                    params["time_range"] = TIME_RANGE[ctx.timelimit]
                try:
                    r = client.get(f"{base}/search", params=params)
                except httpx.HTTPError as exc:
                    raise SourceError(f"SearXNG недоступен ({base}): {exc}") from exc
                if r.status_code == 403:
                    raise SourceError("SearXNG: JSON API выключен (search.formats: json в settings.yml)")
                if r.status_code >= 400:
                    ctx.log("warn", f"SearXNG: «{q}»: HTTP {r.status_code}")
                    continue
                data = r.json()
                results = (data.get("results") or [])[: ctx.max_per_query * 2]
                for res in results:
                    url = res.get("url") or ""
                    if not url.startswith("http"):
                        continue
                    title, content = res.get("title") or "", res.get("content") or ""
                    posted = _parse_date(res.get("publishedDate")) or extract_post_date(f"{title} {content}")
                    out.append(Candidate(
                        url=url.split("#")[0], title=title, text=content, source=self.type,
                        platform=platform_for(url), query=q, posted_at=posted,
                        extra={"engines": res.get("engines", [])},
                    ))
                dead = [e[0] for e in data.get("unresponsive_engines") or []]
                ctx.log("info", f"SearXNG: «{q}» → {len(results)}" + (f" (не ответили: {', '.join(dead)})" if dead else ""))
                if not results and len(dead) >= len(engines.split(",")):
                    ctx.log("warn", "SearXNG: все движки временно недоступны — остальные запросы пропущены")
                    break
                time.sleep(interval)
        return out


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None
