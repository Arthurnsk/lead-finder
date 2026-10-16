"""Source plugin interface. A source turns a project's config into fresh candidates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date

Log = Callable[[str, str], None]  # (level, message)


@dataclass
class Candidate:
    url: str
    title: str
    text: str
    source: str  # vk / searxng / rss / ddg
    platform: str = "web"  # vk / forum / telegram / qa / web …
    query: str = ""
    posted_at: date | None = None
    author: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posted_at"] = self.posted_at.isoformat() if self.posted_at else ""
        return d


@dataclass
class SourceContext:
    config: dict  # ProjectSource.config
    region: str
    timelimit: str  # d/w/m/y/""
    since: date | None  # drop anything older (from project.max_age_days)
    secrets: dict  # decrypted org integrations, e.g. {"vk_token": "..."}
    log: Log
    max_per_query: int = 10


class SourceError(RuntimeError):
    """Source misconfigured/unavailable — reported in the run log, other sources continue."""


class Source:
    type: str = ""

    def fetch(self, ctx: SourceContext) -> list[Candidate]:
        raise NotImplementedError


REGISTRY: dict[str, type[Source]] = {}


def register(cls: type[Source]) -> type[Source]:
    REGISTRY[cls.type] = cls
    return cls


PLATFORM_HOSTS = {
    "vk.com": "vk", "m.vk.com": "vk", "t.me": "telegram", "telegram.me": "telegram", "ok.ru": "ok",
    "forumhouse.ru": "forum", "houseme.ru": "forum", "pravoved.ru": "qa", "otvet.mail.ru": "qa",
    "yandex.ru": "qa", "avito.ru": "marketplace",
}


def platform_for(url: str) -> str:
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower().removeprefix("www.")
    for needle, name in PLATFORM_HOSTS.items():
        if host == needle or host.endswith("." + needle):
            return name
    return "web"
