"""RSS/Atom feeds (forums, Q&A sections). Stable and always fresh."""

from __future__ import annotations

import re
import time
from datetime import date

import feedparser
import httpx

from app.sources.base import Candidate, Source, SourceContext, platform_for, register

_TAG_RE = re.compile(r"<[^>]+>")


@register
class RssSource(Source):
    type = "rss"

    def fetch(self, ctx: SourceContext) -> list[Candidate]:
        out: list[Candidate] = []
        with httpx.Client(timeout=20.0, follow_redirects=True,
                          headers={"User-Agent": "LeadFinder/1.0 (+RSS reader)"}) as client:
            for feed_url in [f for f in ctx.config.get("feeds", []) if f.strip()]:
                r = None
                for attempt in range(3):
                    try:
                        r = client.get(feed_url)
                        r.raise_for_status()
                        break
                    except httpx.HTTPError as exc:
                        r = None
                        if attempt == 2:
                            ctx.log("warn", f"RSS: {feed_url}: {exc} (3 попытки)")
                        else:
                            time.sleep(2 * (attempt + 1))
                if r is None:
                    continue
                feed = feedparser.parse(r.content)
                n = 0
                for e in feed.entries:
                    url = e.get("link") or ""
                    if not url:
                        continue
                    st = e.get("published_parsed") or e.get("updated_parsed")
                    posted = date(st.tm_year, st.tm_mon, st.tm_mday) if st else None
                    text = _TAG_RE.sub(" ", e.get("summary") or "")
                    out.append(Candidate(
                        url=url, title=e.get("title") or "", text=" ".join(text.split())[:3000],
                        source=self.type, platform=platform_for(url), query=feed_url,
                        posted_at=posted, author=e.get("author") or "",
                    ))
                    n += 1
                ctx.log("info", f"RSS: {feed_url} → {n} записей")
        return out
