"""Watch a listing page (Q&A «новые вопросы», forum «новые темы») on sites that have no RSS.

The page is fetched, links that look like items are collected, and each new item page is read for
its title, text and date. Deterministic: no search engines involved, so nothing to rate-limit us.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.engine.dates import extract_post_date
from app.sources.base import Candidate, Source, SourceContext, SourceError, platform_for, register

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
DEFAULT_ITEM_PATTERN = r"/(question|questions|topic|threads?|post|voprosy?)/[\w\-]*\d"
NOISE = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe")
# Blocks that look like sidebars/recommendations, not the question itself
NOISE_ATTR = re.compile(r"similar|related|recommend|popular|sidebar|aside|widget|banner|footer|menu|comment", re.I)


def _get(client: httpx.Client, url: str, attempts: int = 3) -> httpx.Response | None:
    for attempt in range(attempts):
        try:
            r = client.get(url)
        except httpx.HTTPError:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(3 * (attempt + 1))
            continue
        return r
    return None


def _soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(NOISE)):
        tag.decompose()
    return soup


def read_item(client: httpx.Client, url: str) -> dict:
    """Title, text and date of a single item page — works on most question/thread pages."""
    r = _get(client, url)
    if r is None or r.status_code != 200 or "html" not in (r.headers.get("content-type") or ""):
        return {}
    soup = _soup(r.text)
    title = (soup.find("h1") or soup.find("title"))
    title_text = title.get_text(" ", strip=True)[:300] if title else ""

    # Pick the block that reads like prose: long, but not a list of links, and not a «похожие» sidebar
    best, best_score = "", 0.0
    for block in soup.find_all(["article", "section", "div", "main"]):
        attrs = " ".join([*(block.get("class") or []), block.get("id") or ""])
        if NOISE_ATTR.search(attrs):
            continue
        text = block.get_text(" ", strip=True)
        if not (120 <= len(text) <= 8000):
            continue
        link_chars = sum(len(a.get_text(" ", strip=True)) for a in block.find_all("a"))
        prose = 1 - min(1.0, link_chars / max(1, len(text)))
        score = len(text) * (prose ** 2)  # link lists lose hard
        if score > best_score:
            best, best_score = text, score
    body = " ".join((best or soup.get_text(" ", strip=True))[:4000].split())

    posted = None
    for attr in ("datetime", "content", "data-date"):
        for tag in soup.find_all(attrs={attr: re.compile(r"\d{4}-\d{2}-\d{2}")}):
            posted = extract_post_date(str(tag.get(attr, "")))
            if posted:
                break
        if posted:
            break
    # visible date on the page, e.g. «07 сентября 2026»
    posted = posted or extract_post_date(soup.get_text(" ", strip=True)[:1500])
    return {"title": title_text, "text": body, "posted_at": posted}


@register
class WebWatchSource(Source):
    """config: {"pages": [url…], "item_pattern": regex, "max_items": 15, "read_items": true}"""

    type = "web_watch"

    def fetch(self, ctx: SourceContext) -> list[Candidate]:
        pages = [p for p in ctx.config.get("pages", []) if p.strip()]
        if not pages:
            raise SourceError("Не заданы страницы для наблюдения")
        pattern = re.compile(ctx.config.get("item_pattern") or DEFAULT_ITEM_PATTERN, re.I)
        max_items = int(ctx.config.get("max_items") or 15)
        read_items = ctx.config.get("read_items", True)

        out: list[Candidate] = []
        with httpx.Client(timeout=25.0, follow_redirects=True,
                          headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"}) as client:
            for page in pages:
                r = _get(client, page)
                if r is None or r.status_code != 200:
                    ctx.log("warn", f"Наблюдатель: {page}: "
                                    f"{'нет ответа' if r is None else f'HTTP {r.status_code}'}")
                    continue
                host = urlparse(page).netloc
                soup = _soup(r.text)
                links: list[tuple[str, str]] = []
                seen: set[str] = set()
                for a in soup.find_all("a", href=True):
                    url = urljoin(page, a["href"]).split("#")[0]
                    if urlparse(url).netloc != host or url in seen or not pattern.search(urlparse(url).path):
                        continue
                    seen.add(url)
                    links.append((url, a.get_text(" ", strip=True)[:200]))
                    if len(links) >= max_items:
                        break

                for url, anchor in links:
                    item = read_item(client, url) if read_items else {}
                    posted = item.get("posted_at")
                    if ctx.since and posted and posted < ctx.since:
                        continue
                    text = item.get("text") or anchor
                    if len(text) < 40:
                        continue
                    out.append(Candidate(
                        url=url, title=(item.get("title") or anchor)[:200], text=text[:3000],
                        source=self.type, platform=platform_for(url), query=page, posted_at=posted,
                    ))
                    time.sleep(1.0)  # polite: one item page at a time
                ctx.log("info", f"Наблюдатель: {page} → {len(links)} ссылок, взято {len(out)}")
        return out
