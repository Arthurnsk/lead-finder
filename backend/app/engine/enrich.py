"""Turn a bare link into something a manager can act on: author, profile, full text, way to reply."""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
MIN_INTERVAL = 1.5  # polite: one page at a time, with a pause
_last_fetch = 0.0

_SCRIPTS = re.compile(r"(?is)<(script|style|noscript|svg|iframe).*?</\1>")
_TAGS = re.compile(r"(?is)<[^>]+>")


_NOISE = re.compile(r"(?i)(-->\s*)?(РЕКЛАМА НА ФОРУМХАУС|Реклама\b|Нажмите, чтобы раскрыть\.{0,3})")


def _text(html: str, limit: int = 3000) -> str:
    plain = unescape(_TAGS.sub(" ", _SCRIPTS.sub(" ", html)))
    return " ".join(_NOISE.sub(" ", plain).split())[:limit]


def _fetch(url: str, timeout: float = 15.0, attempts: int = 3) -> str | None:
    """Polite, with retries: a single network hiccup must not cost us a lead."""
    global _last_fetch
    for attempt in range(attempts):
        wait = MIN_INTERVAL - (time.monotonic() - _last_fetch)
        if wait > 0:
            time.sleep(wait)
        _last_fetch = time.monotonic()
        try:
            r = httpx.get(url, timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"})
        except httpx.HTTPError:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code != 200 or "text/html" not in (r.headers.get("content-type") or ""):
            return None
        return r.text
    return None


# XenForo (ForumHouse and most Russian forums)
_POST_START = re.compile(r'<(li|article)[^>]+data-author="([^"]+)"', re.I)
_PROFILE_RE = re.compile(r'href="((?:https?://[^"]+)?/?(?:members|users)/[^"?#]+)"')
# XenForo prints the post date as "23.06.15 в 03:32" (or ISO in <time datetime=…>)
_DATE_TITLE_RE = re.compile(r'class="DateTime"[^>]*title="(\d{2})\.(\d{2})\.(\d{2,4})')
_DATE_TEXT_RE = re.compile(r'<(?:span|abbr)[^>]*class="DateTime"[^>]*>\s*(\d{2})\.(\d{2})\.(\d{2,4})')
_DATE_ISO_RE = re.compile(r'<time[^>]+datetime="(\d{4}-\d{2}-\d{2})')
_DATE_UNIX_RE = re.compile(r'data-time="(\d{9,12})"')
_BODY_RE = re.compile(
    r'<(?:blockquote|div)[^>]*class="[^"]*(?:messageText|bbWrapper)[^"]*"[^>]*>(.*?)'
    r'(?:</blockquote>|<div class="messageTextEndMarker)', re.S)


def _site_root(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}/"


def enrich_forum_thread(url: str) -> dict:
    """Author, profile link and the opening post of a forum thread. Empty dict when unavailable."""
    html = _fetch(url)
    if not html:
        return {}
    first = _POST_START.search(html)
    if not first:
        return {}
    # The post block ends where the next post begins (nested </li> makes a lazy regex stop too early)
    nxt = _POST_START.search(html, first.end())
    block = _SCRIPTS.sub(" ", html[first.start(): nxt.start() if nxt else len(html)])

    out = {"author": first.group(2).strip()[:200]}
    profile = _PROFILE_RE.search(block)
    if profile:
        href = profile.group(1)
        out["profile_url"] = href if href.startswith("http") else urljoin(_site_root(url), href.lstrip("/"))
    posted = _first_post_date(html)
    if posted:
        out["posted_at"] = posted
    body = _BODY_RE.search(block)
    if body:
        text = _text(body.group(1), 2500)
        if len(text) > 40:
            out["text"] = text
    return out


def _first_post_date(html: str) -> date | None:
    """Date the thread was STARTED — the feed date is the last reply, so a bumped 2015 thread
    otherwise looks brand new. The earliest date on page 1 is the opening post."""
    found: list[date] = []
    for m in [*_DATE_TITLE_RE.finditer(html), *_DATE_TEXT_RE.finditer(html)]:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        year += 2000 if year < 100 else 0
        try:
            found.append(date(year, month, day))
        except ValueError:
            continue
    for m in _DATE_ISO_RE.finditer(html):
        try:
            found.append(date.fromisoformat(m.group(1)))
        except ValueError:
            continue
    for m in _DATE_UNIX_RE.finditer(html):
        try:
            found.append(datetime.fromtimestamp(int(m.group(1))).date())
        except (ValueError, OSError):
            continue
    plausible = [d for d in found if date(2000, 1, 1) <= d <= date.today()]
    return min(plausible) if plausible else None


def outreach_for(url: str, platform: str, contacts: dict, enriched: dict) -> dict:
    """How a manager can actually reach this person, in plain words + links."""
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    profile = enriched.get("profile_url") or contacts.get("profile_url") or ""
    author = enriched.get("author") or contacts.get("account") or ""

    if platform == "forum":
        return {
            "channel": "forum",
            "how": "Ответить в теме или написать автору в личные сообщения на форуме",
            "author": author,
            "profile_url": profile,
            "action_url": url,
        }
    if platform == "vk":
        return {"channel": "vk", "how": "Написать автору во ВКонтакте",
                "author": author, "profile_url": profile or url, "action_url": profile or url}
    if platform == "telegram":
        handle = contacts.get("telegram") or author
        return {"channel": "telegram", "how": "Написать в Telegram",
                "author": handle, "profile_url": contacts.get("telegram_url") or url, "action_url": url}
    if platform == "tender":
        return {"channel": "tender",
                "how": "Изучить извещение и подать заявку на площадке; контакты заказчика — в документации",
                "author": author, "profile_url": "", "action_url": url}
    if platform == "qa":
        return {"channel": "qa", "how": "Ответить на вопрос на сайте (публичный ответ эксперта)",
                "author": author, "profile_url": profile, "action_url": url}
    if contacts.get("emails") or contacts.get("phones"):
        return {"channel": "direct", "how": "Связаться по указанным контактам",
                "author": author, "profile_url": profile, "action_url": url}
    return {"channel": host or "web", "how": "Открыть источник и ответить там",
            "author": author, "profile_url": profile, "action_url": url}
