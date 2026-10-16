"""Hard filters so marketplace/SEO junk never reaches the LLM."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Niche-agnostic junk: marketplaces, encyclopedias, media, banks.
# Niche-specific hosts (own site, competitors) come from niches/<id>.yaml.
BLOCKED_HOST_SUFFIXES = (
    "youla.ru",
    "wildberries.ru",
    "ozon.ru",
    "wikipedia.org",
    "wiktionary.org",
    "youtube.com",
    "youtu.be",
    "dzen.ru",
    "zen.yandex.ru",
    "vc.ru",
    "habr.com",
    "tinkoff.ru",
    "sberbank.ru",
    "banki.ru",
)

# Path/title patterns of listing engines / how-to content.
BLOCKED_TITLE_RE = re.compile(
    r"(купить земельный участок в|участки? в продаже|объявлени[яе]|каталог участок|"
    r"пошаговая инструкция|как купить земельный|ипотека на участок|"
    r"лучшие вложения|топ[- ]?\d+|обзор рынка)",
    re.I,
)

DEMAND_RE = re.compile(
    r"(ищу|ищем|куплю|купим|нужн[аоы]|помогите|подскажите|хочу (купить|оформить|проверить)|"
    r"где (купить|оформить)|кто помогал|нужен (юрист|аудит|риелтор)|посоветуйте|"
    r"кто сталкивался|как быть|что делать)",
    re.I,
)

PAST_EXPERIENCE_RE = re.compile(
    r"\b(купил|купила|оформил|оформила|построил|построила|продал|продала)\b",
    re.I,
)

SUPPLY_SPAM_RE = re.compile(
    r"(прода[её]м|в продаже|агентство недвижимости|риэлторские услуги|оставьте заявку|"
    r"узнайте стоимость|бесплатная консультация|курс по|научим инвестировать)",
    re.I,
)


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def is_blocked_host(url: str, extra_hosts: tuple[str, ...] | list[str] = ()) -> bool:
    host = host_of(url)
    return any(host == s or host.endswith("." + s) for s in (*BLOCKED_HOST_SUFFIXES, *extra_hosts))


def _has_demand(text: str, extra_demand: re.Pattern | None) -> bool:
    return bool(DEMAND_RE.search(text) or (extra_demand and extra_demand.search(text)))


def looks_like_demand(title: str, snippet: str, extra_demand: re.Pattern | None = None) -> bool:
    text = f"{title} {snippet}"
    if BLOCKED_TITLE_RE.search(text):
        return False
    demand = _has_demand(text, extra_demand)
    if PAST_EXPERIENCE_RE.search(text) and not demand:
        return False
    if SUPPLY_SPAM_RE.search(text) and not demand:
        return False
    return demand


# A single thread/post, not a forum section, tag or search listing.
DISCUSSION_PATH_RE = re.compile(
    r"/(threads?|topic|showthread|question|questions|posts?)/[^/]+|/wall-?\d+_\d+|[?&](t|topic|w)=",
    re.I,
)
TG_POST_RE = re.compile(r"^/(s/)?[a-z0-9_]+/\d+/?$", re.I)  # t.me/<chat>/<msg_id>


def is_discussion_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc.lower().removeprefix("www.") in {"t.me", "telegram.me"}:
        return bool(TG_POST_RE.match(parsed.path))
    return bool(DISCUSSION_PATH_RE.search(parsed.path + ("?" + parsed.query if parsed.query else "")))


def compile_patterns(patterns: list[str]) -> re.Pattern | None:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I) if patterns else None


def prefilter_hit(
    url: str,
    title: str,
    snippet: str,
    extra_hosts: tuple[str, ...] | list[str] = (),
    extra_demand: re.Pattern | None = None,
    exclude: re.Pattern | None = None,
    require_demand: bool = True,
) -> tuple[bool, str]:
    if is_blocked_host(url, extra_hosts):
        return False, "blocked_host"
    # Off-topic subjects (building, gardening, utilities…) never reach the LLM
    if exclude and exclude.search(f"{title} {snippet}"):
        return False, "off_topic"
    host = host_of(url)
    soft_ok = any(
        host.endswith(x)
        for x in ("forumhouse.ru", "vk.com", "t.me", "telegram.me", "ok.ru", "houseme.ru")
    )
    # Forum sections / channel roots carry fresh dates but aren't a person's question
    if soft_ok and not is_discussion_url(url):
        return False, "listing_page"
    text = f"{title} {snippet}"
    if not require_demand:
        return True, "structured_source"
    if PAST_EXPERIENCE_RE.search(text) and not _has_demand(text, extra_demand):
        return False, "past_experience"
    if looks_like_demand(title, snippet, extra_demand):
        return True, "demand_ok"
    # Allow forums/vk/telegram threads with weaker text only if not pure supply spam
    if soft_ok and len(text.strip()) > 20 and not SUPPLY_SPAM_RE.search(text):
        return True, "soft_social"
    return False, "no_demand_signal"
