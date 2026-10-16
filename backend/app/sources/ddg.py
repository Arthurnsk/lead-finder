"""DuckDuckGo directly (fallback). Flaky: empty SERPs and TLS drops are expected."""

from __future__ import annotations

import time

from ddgs import DDGS

from app.engine.dates import extract_post_date
from app.sources.base import Candidate, Source, SourceContext, platform_for, register


@register
class DdgSource(Source):
    type = "ddg"

    def fetch(self, ctx: SourceContext) -> list[Candidate]:
        out: list[Candidate] = []
        for q in [q for q in ctx.config.get("queries", []) if q.strip()]:
            rows: list[dict] = []
            for attempt in range(2):
                try:
                    rows = DDGS().text(q, region=ctx.region, timelimit=ctx.timelimit or None,
                                       max_results=ctx.max_per_query * 2)
                    break
                except Exception as exc:
                    if "no results" in str(exc).lower():
                        break
                    ctx.log("warn", f"DDG: «{q}»: {exc}")
                    time.sleep(4 * (attempt + 1))
            for row in rows:
                url = (row.get("href") or "").split("#")[0]
                if not url.startswith("http"):
                    continue
                title, body = row.get("title") or "", row.get("body") or ""
                out.append(Candidate(url=url, title=title, text=body, source=self.type,
                                     platform=platform_for(url), query=q,
                                     posted_at=extract_post_date(f"{title} {body}")))
            ctx.log("info", f"DDG: «{q}» → {len(rows)}")
            time.sleep(2.5)
        return out
