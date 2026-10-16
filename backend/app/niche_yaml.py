"""Import/export niche templates (the YAML format from the pilot) ↔ Project + sources."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import yaml
from croniter import croniter

from app.models import Project, ProjectSource

_SITE_RE = re.compile(r"\bsite:\S+\s*", re.I)


def next_run(cron: str, after: datetime | None = None) -> datetime | None:
    if not cron:
        return None
    base = after or datetime.now(timezone.utc)
    return croniter(cron, base).get_next(datetime)


def validate_cron(cron: str) -> None:
    if cron and not croniter.is_valid(cron):
        raise ValueError(f"Некорректное cron-выражение: {cron!r}")


def parse_niche_yaml(text: str) -> tuple[dict, list[dict]]:
    """Returns (project fields, sources) from a pilot niche YAML."""
    raw = yaml.safe_load(text) or {}
    search = raw.get("search") or {}
    groups: dict[str, list[str]] = {k: list(v or []) for k, v in (raw.get("queries") or {}).items()}
    all_queries = [q for qs in groups.values() for q in qs]

    # VK newsfeed.search takes plain phrases: strip site: operators, dedupe
    vk_queries = list(dict.fromkeys(_SITE_RE.sub("", q).strip() for q in all_queries if q.strip()))

    project = {
        "name": raw.get("name") or raw.get("id") or "Новый проект",
        "slug": raw.get("id") or "project",
        "site": raw.get("site") or "",
        "offer": (raw.get("offer") or "").strip(),
        "icp": (raw.get("icp") or "").strip(),
        "examples": list(raw.get("examples") or []),
        "blocked_hosts": list(raw.get("blocked_hosts") or []),
        "demand_patterns": list(raw.get("demand_patterns") or []),
        "exclude_patterns": list(raw.get("exclude_patterns") or []),
        "region": search.get("region", "ru-ru"),
        "timelimit": search.get("timelimit", "m") or "",
        "max_age_days": int(search.get("max_age_days", 90)),
    }
    tenders = raw.get("tenders") or {}
    sources = [
        {"type": "vk", "name": "VK: поиск по постам", "enabled": True, "config": {"queries": vk_queries}},
        {"type": "telegram_chat", "name": "Telegram-чаты", "enabled": bool(raw.get("chats")),
         "config": {"chats": list(raw.get("chats") or []), "keywords": list(raw.get("chat_keywords") or [])}},
        {"type": "tenders", "name": "Торги по земле (torgi.gov.ru)", "enabled": bool(tenders.get("torgi")),
         "config": {"provider": "torgi", "queries": list(tenders.get("torgi") or []),
                    "regions": [str(r) for r in (tenders.get("regions") or [])]}},
        {"type": "tenders", "name": "Закупки работ (zakupki.gov.ru)", "enabled": bool(tenders.get("zakupki")),
         "config": {"provider": "zakupki", "queries": list(tenders.get("zakupki") or [])}},
        {"type": "web_watch", "name": "Наблюдатель за страницами", "enabled": bool(raw.get("watch_pages")),
         "config": {"pages": list(raw.get("watch_pages") or []), "max_items": 15}},
        {"type": "searxng", "name": "Веб: SearXNG", "enabled": True,
         "config": {"queries": all_queries, "groups": groups}},
        {"type": "rss", "name": "RSS-ленты", "enabled": False, "config": {"feeds": list(raw.get("feeds") or [])}},
        {"type": "ddg", "name": "Веб: DuckDuckGo (резерв)", "enabled": False, "config": {"queries": all_queries}},
    ]
    return project, sources


def project_to_yaml(project: Project) -> str:
    web = next((s for s in project.sources if s.type == "searxng"), None)
    rss = next((s for s in project.sources if s.type == "rss"), None)
    data = {
        "id": project.slug,
        "name": project.name,
        "site": project.site,
        "offer": project.offer,
        "icp": project.icp,
        "search": {
            "region": project.region,
            "timelimit": project.timelimit,
            "max_age_days": project.max_age_days,
        },
        "queries": (web.config.get("groups") if web else None) or {"web": web.config.get("queries", []) if web else []},
        "feeds": rss.config.get("feeds", []) if rss else [],
        "chats": next((s2.config.get("chats", []) for s2 in project.sources if s2.type == "telegram_chat"), []),
        "watch_pages": next((s2.config.get("pages", []) for s2 in project.sources if s2.type == "web_watch"), []),
        "tenders": {
            "torgi": next((s2.config.get("queries", []) for s2 in project.sources
                           if s2.type == "tenders" and s2.config.get("provider") == "torgi"), []),
            "zakupki": next((s2.config.get("queries", []) for s2 in project.sources
                             if s2.type == "tenders" and s2.config.get("provider") == "zakupki"), []),
        },
        "blocked_hosts": project.blocked_hosts,
        "demand_patterns": project.demand_patterns,
        "exclude_patterns": project.exclude_patterns,
        "examples": project.examples,
    }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)


def build_sources(project: Project, sources: list[dict]) -> list[ProjectSource]:
    return [
        ProjectSource(organization_id=project.organization_id, project_id=project.id, **s) for s in sources
    ]
