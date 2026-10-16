"""Find new sources for a project: Telegram channels, forum RSS feeds, Q&A sites.

Everything here is free and needs no API keys: SearXNG for finding candidates, plain HTTP for
verifying them, and the project's own LLM for judging whether a source is worth watching.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urljoin, urlparse

import feedparser
import httpx

from app.config import settings
from app.engine.enrich import UA
from app.engine.evaluator import format_examples
from app.engine.llm import LlmClient
from app.models import Project

TME_RE = re.compile(r"https?://t\.me/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})")
FEED_LINK_RE = re.compile(
    r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]*>', re.I)
HREF_RE = re.compile(r'href="([^"]+)"', re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


@dataclass
class SourceCandidate:
    type: str  # telegram / rss
    name: str
    ref: str  # channel name or feed url
    url: str  # human-openable link
    sample: str = ""
    score: float = 0.0
    reason: str = ""
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


QUERY_SYSTEM = (
    "Ты помогаешь найти ПЛОЩАДКИ, где потенциальные клиенты компании сами пишут о своей задаче. "
    "Нужны форумы, тематические сайты вопросов-ответов и Telegram-каналы/чаты — не сами клиенты."
)


def propose_queries(llm: LlmClient, project: Project, kinds: list[str]) -> dict[str, list[str]]:
    want = []
    if "telegram" in kinds:
        want.append('"telegram": ["запросы для поиска телеграм-каналов и чатов по теме"]')
    if "rss" in kinds:
        want.append('"forums": ["запросы для поиска форумов и сайтов вопросов-ответов по теме"]')
    user = f"""
Компания: {project.name} ({project.site})
Что продаёт: {project.offer[:800]}
Кого ищем:
{project.icp[:1200]}

Придумай короткие поисковые запросы на русском (по 6 в каждой группе), чтобы найти площадки,
где такие люди задают вопросы. Для Telegram используй слова вроде «телеграм канал», «чат».
Верни JSON: {{{', '.join(want)}}}
""".strip()
    try:
        data = llm.chat_json(QUERY_SYSTEM, user, max_tokens=600)
    except Exception:
        return {}
    return {k: [str(q) for q in (v or [])][:8] for k, v in data.items() if isinstance(v, list)}


# Engines are asked together: any single one may be rate-limited or CAPTCHA'd at a given moment.
SEARCH_ENGINES = "duckduckgo,mojeek,startpage,brave"


def _searxng(query: str, limit: int = 10) -> list[dict]:
    try:
        r = httpx.get(f"{settings.searxng_url.rstrip('/')}/search",
                      params={"q": query, "format": "json", "language": "ru",
                              "engines": SEARCH_ENGINES}, timeout=30.0)
        if r.status_code != 200:
            return []
        return (r.json().get("results") or [])[:limit]
    except (httpx.HTTPError, ValueError):
        return []


def search(query: str, limit: int = 10) -> list[dict]:
    """Small indexes often return nothing for a long phrase — retry with its first words."""
    results = _searxng(query, limit)
    if results:
        return results
    words = query.split()
    if len(words) > 3:
        return _searxng(" ".join(words[:3]), limit)
    return []


def _get(url: str, timeout: float = 15.0) -> httpx.Response | None:
    try:
        return httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})
    except httpx.HTTPError:
        return None


# ---------------------------------------------------------------- Telegram


def verify_telegram(channel: str) -> SourceCandidate | None:
    """Public channels render at t.me/s/<name>; anything else can't be read without an account."""
    r = _get(f"https://t.me/s/{channel}")
    if r is None or r.status_code != 200:
        return None
    html = r.text
    posts = re.findall(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', html, re.S)
    if len(posts) < 3:
        return None
    title = TITLE_RE.search(html)
    name = re.sub(r"\s*–\s*Telegram.*$", "", title.group(1).strip()) if title else channel
    subs = re.search(r'([\d\s ]+)\s*(?:subscribers|подписчик)', html)
    sample = " ".join(re.sub(r"<[^>]+>", " ", " ".join(posts[:4])).split())[:1200]
    return SourceCandidate(
        type="telegram", name=name[:120], ref=channel, url=f"https://t.me/{channel}", sample=sample,
        stats={"posts_on_page": len(posts), "subscribers": (subs.group(1).strip() if subs else "")},
    )


# ---------------------------------------------------------------- RSS / forums


def discover_feeds(page_url: str) -> list[str]:
    """Feeds declared by a page, plus the usual XenForo/WordPress paths."""
    out: list[str] = []
    r = _get(page_url)
    if r is not None and r.status_code == 200 and "html" in (r.headers.get("content-type") or ""):
        for tag in FEED_LINK_RE.findall(r.text):
            href = HREF_RE.search(tag)
            if href:
                out.append(urljoin(page_url, href.group(1)))
    root = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
    for guess in ("/index.rss", "/feed/", "/rss/", "/forums/-/index.rss"):
        out.append(root + guess)
    return list(dict.fromkeys(out))


def verify_feed(feed_url: str) -> SourceCandidate | None:
    r = _get(feed_url)
    if r is None or r.status_code != 200:
        return None
    parsed = feedparser.parse(r.content)
    entries = parsed.entries
    if len(entries) < 3:
        return None
    titles = [e.get("title", "") for e in entries[:8]]
    sample = " · ".join(t for t in titles if t)[:1200]
    name = (parsed.feed.get("title") or urlparse(feed_url).netloc)[:120]
    return SourceCandidate(type="rss", name=name, ref=feed_url, url=feed_url, sample=sample,
                           stats={"entries": len(entries)})


# ---------------------------------------------------------------- rating


RATE_SYSTEM = (
    "Ты оцениваешь ПЛОЩАДКУ (не отдельный пост) как источник лидов для компании. "
    "Хорошая площадка — та, где люди сами описывают задачу, которую решают услуги компании. "
    "Плохая — новости ведомств, реклама, блогеры, оффтоп, другая тематика."
)


def rate_candidate(llm: LlmClient, project: Project, cand: SourceCandidate) -> SourceCandidate:
    user = f"""
Компания: {project.name}. Что продаёт: {project.offer[:600]}
Кого ищем:
{project.icp[:900]}
Примеры разметки лидов:
{format_examples(project.examples or [], limit=6)}

Площадка: {cand.type} · {cand.name} · {cand.url}
Свежие сообщения/заголовки с неё:
{cand.sample[:1200]}

Верни JSON: {{"score": 0.0-1.0, "reason": "до 15 слов, почему подходит или нет",
"expected_leads": "часто|иногда|редко"}}
""".strip()
    try:
        data = llm.chat_json(RATE_SYSTEM, user, max_tokens=200)
        cand.score = max(0.0, min(1.0, float(data.get("score") or 0)))
        cand.reason = str(data.get("reason") or "")[:200]
        cand.stats["expected_leads"] = str(data.get("expected_leads") or "")[:20]
    except Exception as exc:
        cand.score, cand.reason = 0.0, f"не удалось оценить: {exc}"[:200]
    return cand


# ---------------------------------------------------------------- orchestration


def discover_sources(llm: LlmClient, project: Project, kinds: list[str], log, max_per_kind: int = 6,
                     known_refs: set[str] | None = None) -> list[SourceCandidate]:
    known = known_refs or set()
    queries = propose_queries(llm, project, kinds)
    log("info", "Запросы для поиска площадок: " + "; ".join(q for v in queries.values() for q in v)[:500])
    found: dict[str, SourceCandidate] = {}

    if "telegram" in kinds:
        for q in queries.get("telegram", [])[:4]:
            for res in search(f"{q} site:t.me", limit=10) + search(q, limit=10):
                m = TME_RE.search(res.get("url") or "")
                if not m:
                    continue
                channel = m.group(1)
                if channel in known or channel in found or channel.lower() in {"s", "joinchat", "share"}:
                    continue
                cand = verify_telegram(channel)
                if cand:
                    found[channel] = cand
                    log("info", f"Telegram-кандидат: @{channel} — {cand.name}")
                if len([c for c in found.values() if c.type == "telegram"]) >= max_per_kind:
                    break
            if len([c for c in found.values() if c.type == "telegram"]) >= max_per_kind:
                break

    if "rss" in kinds:
        seen_hosts: set[str] = set()
        for q in queries.get("forums", [])[:4]:
            for res in search(q, limit=10):
                url = res.get("url") or ""
                host = urlparse(url).netloc
                if not host or host in seen_hosts:
                    continue
                seen_hosts.add(host)
                for feed_url in discover_feeds(url)[:4]:
                    if feed_url in known or feed_url in found:
                        continue
                    cand = verify_feed(feed_url)
                    if cand:
                        found[feed_url] = cand
                        log("info", f"RSS-кандидат: {cand.name} — {feed_url}")
                        break
                if len([c for c in found.values() if c.type == "rss"]) >= max_per_kind:
                    break
            if len([c for c in found.values() if c.type == "rss"]) >= max_per_kind:
                break

    log("info", f"Найдено площадок: {len(found)}. Оцениваю релевантность…")
    rated = [rate_candidate(llm, project, c) for c in found.values()]
    rated.sort(key=lambda c: c.score, reverse=True)
    return rated
