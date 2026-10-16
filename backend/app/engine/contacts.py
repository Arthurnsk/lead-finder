"""Extract real contact handles/links from text and URLs — never invent."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote, urlparse


EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")
# RU / international phones, fairly strict
PHONE_RE = re.compile(
    r"(?:(?:\+7|8)[\s\-()]*)?(?:\d[\s\-()]*){10}|\+\d{11,15}"
)
TG_AT_RE = re.compile(r"(?<!\w)@([a-zA-Z][a-zA-Z0-9_]{3,31})\b")
# Forum / discussion author hints often appear in SERP snippets
FORUM_USER_RE = re.compile(
    r"(?:автор|участник|user|от)\s*[:\-–]?\s*([A-Za-zА-Яа-яЁё0-9_\-.]{3,32})"
    r"|([A-Za-zА-Яа-яЁё0-9_\-.]{3,32})\s+(?:пишет|написал|написала|спросил|спрашивает)",
    re.I,
)
FH_MEMBER_RE = re.compile(r"forumhouse\.ru/members/([a-zA-Z0-9_\-\.]+)", re.I)
TG_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z][a-zA-Z0-9_]{3,31})(?:/\S*)?",
    re.I,
)
VK_LINK_RE = re.compile(
    r"(?:https?://)?(?:m\.)?vk\.com/([a-zA-Z0-9._]+)",
    re.I,
)
IG_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/([a-zA-Z0-9._]+)/?",
    re.I,
)
OK_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?ok\.ru/(?:profile/)?([a-zA-Z0-9._]+)",
    re.I,
)
YT_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:@|channel/|c/|user/)|youtu\.be/)([a-zA-Z0-9_\-]+)",
    re.I,
)
WA_RE = re.compile(
    r"(?:https?://)?(?:wa\.me|api\.whatsapp\.com/send\?phone=)(\+?\d{10,15})",
    re.I,
)
MAX_RE = re.compile(
    r"(?:https?://)?(?:max\.ru|vk\.com/write)[^\s\"'<>]*",
    re.I,
)

SKIP_VK_PATHS = {
    "wall", "video", "topic", "clip", "music", "podcasts", "apps", "feed",
    "login", "search", "write", "mail", "im", "settings", "support",
}
SKIP_TG_PATHS = {"s", "share", "proxy", "iv", "addstickers", "joinchat"}


@dataclass
class Contacts:
    profile_url: str = ""
    account: str = ""
    telegram: str = ""
    telegram_url: str = ""
    vk_url: str = ""
    instagram_url: str = ""
    ok_url: str = ""
    youtube_url: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    other_links: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def merge(self, other: "Contacts") -> "Contacts":
        def first(*vals: str) -> str:
            for v in vals:
                if v:
                    return v
            return ""

        def uniq(a: list[str], b: list[str]) -> list[str]:
            out: list[str] = []
            for x in a + b:
                x = x.strip()
                if x and x not in out:
                    out.append(x)
            return out

        return Contacts(
            profile_url=first(self.profile_url, other.profile_url),
            account=first(self.account, other.account),
            telegram=first(self.telegram, other.telegram),
            telegram_url=first(self.telegram_url, other.telegram_url),
            vk_url=first(self.vk_url, other.vk_url),
            instagram_url=first(self.instagram_url, other.instagram_url),
            ok_url=first(self.ok_url, other.ok_url),
            youtube_url=first(self.youtube_url, other.youtube_url),
            emails=uniq(self.emails, other.emails),
            phones=uniq(self.phones, other.phones),
            other_links=uniq(self.other_links, other.other_links),
            sources=uniq(self.sources, other.sources),
        )

    def as_dict(self) -> dict:
        d = asdict(self)
        return d

    def summary_line(self) -> str:
        parts: list[str] = []
        if self.account:
            parts.append(f"аккаунт: {self.account}")
        if self.telegram:
            parts.append(f"tg: @{self.telegram.lstrip('@')}")
        elif self.telegram_url:
            parts.append(f"tg: {self.telegram_url}")
        if self.vk_url:
            parts.append(f"vk: {self.vk_url}")
        if self.instagram_url:
            parts.append(f"ig: {self.instagram_url}")
        if self.emails:
            parts.append("email: " + ", ".join(self.emails[:2]))
        if self.phones:
            parts.append("тел: " + ", ".join(self.phones[:2]))
        if self.profile_url and self.profile_url not in " ".join(parts):
            parts.append(f"профиль: {self.profile_url}")
        return " · ".join(parts) if parts else ""

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False)


def _norm_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return "+" + digits
    if 11 <= len(digits) <= 15:
        return "+" + digits
    return None


def _profile_from_url(url: str) -> Contacts:
    c = Contacts(sources=["url"])
    if not url:
        return c
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = unquote(parsed.path or "").strip("/")
    parts = [p for p in path.split("/") if p]

    c.profile_url = url.split("?")[0].split("#")[0]

    if host in {"t.me", "telegram.me"} and parts:
        slug = parts[0]
        if slug.lower() not in SKIP_TG_PATHS and not slug.startswith("+"):
            c.telegram = slug
            c.telegram_url = f"https://t.me/{slug}"
            c.account = f"@{slug}"
    elif host.endswith("vk.com") and parts:
        slug = parts[0]
        if slug.lower() not in SKIP_VK_PATHS and not slug.startswith("wall") and not re.match(r"^(id|club|public)\d+$", slug):
            # id123 / club123 still useful as account
            pass
        if slug.lower() not in SKIP_VK_PATHS:
            if re.match(r"^(id|club|public)\d+$", slug) or re.match(r"^[a-zA-Z][a-zA-Z0-9._]*$", slug):
                c.vk_url = f"https://vk.com/{slug}"
                c.account = slug
                c.profile_url = c.vk_url
    elif "instagram.com" in host and parts:
        slug = parts[0]
        if slug not in {"p", "reel", "stories", "explore"}:
            c.instagram_url = f"https://instagram.com/{slug}"
            c.account = f"@{slug}"
            c.profile_url = c.instagram_url
    elif host.endswith("ok.ru") and parts:
        slug = parts[-1]
        c.ok_url = f"https://ok.ru/{slug}"
        c.account = slug
        c.profile_url = c.ok_url
    elif "youtube.com" in host or host == "youtu.be":
        m = YT_LINK_RE.search(url)
        if m:
            c.youtube_url = url.split("?")[0]
            c.account = m.group(1)
    return c


def extract_from_text(text: str, source: str = "text") -> Contacts:
    c = Contacts(sources=[source])
    if not text:
        return c

    for m in EMAIL_RE.findall(text):
        email = m.lower()
        if email not in c.emails and not email.endswith((".png", ".jpg", ".gif")):
            c.emails.append(email)

    for m in PHONE_RE.findall(text):
        phone = _norm_phone(m)
        if phone and phone not in c.phones:
            c.phones.append(phone)

    for m in TG_LINK_RE.finditer(text):
        slug = m.group(1)
        if slug.lower() in SKIP_TG_PATHS:
            continue
        c.telegram = c.telegram or slug
        c.telegram_url = c.telegram_url or f"https://t.me/{slug}"
        c.account = c.account or f"@{slug}"

    for m in TG_AT_RE.finditer(text):
        slug = m.group(1)
        # skip very generic words
        if slug.lower() in {"mail", "email", "admin", "support", "http", "https"}:
            continue
        c.telegram = c.telegram or slug
        c.telegram_url = c.telegram_url or f"https://t.me/{slug}"
        c.account = c.account or f"@{slug}"

    for m in VK_LINK_RE.finditer(text):
        slug = m.group(1)
        if slug.lower() in SKIP_VK_PATHS:
            continue
        c.vk_url = c.vk_url or f"https://vk.com/{slug}"
        c.account = c.account or slug

    for m in IG_LINK_RE.finditer(text):
        slug = m.group(1)
        if slug in {"p", "reel", "stories", "explore"}:
            continue
        c.instagram_url = c.instagram_url or f"https://instagram.com/{slug}"
        c.account = c.account or f"@{slug}"

    for m in OK_LINK_RE.finditer(text):
        c.ok_url = c.ok_url or f"https://ok.ru/{m.group(1)}"

    for m in YT_LINK_RE.finditer(text):
        c.youtube_url = c.youtube_url or m.group(0)
        if not c.youtube_url.startswith("http"):
            c.youtube_url = "https://" + c.youtube_url

    for m in WA_RE.finditer(text):
        phone = _norm_phone(m.group(1))
        if phone and phone not in c.phones:
            c.phones.append(phone)

    for m in FH_MEMBER_RE.finditer(text):
        slug = m.group(1)
        c.account = c.account or slug
        member = f"https://www.forumhouse.ru/members/{slug}"
        if member not in c.other_links:
            c.other_links.append(member)
        c.profile_url = c.profile_url or member

    if not c.account:
        m = FORUM_USER_RE.search(text)
        if m:
            name = next((g for g in m.groups() if g), "")
            if name and name.lower() not in {"http", "https", "www", "forum", "участник"}:
                c.account = name

    return c


def extract_contacts(url: str = "", *texts: str) -> Contacts:
    merged = _profile_from_url(url)
    for i, t in enumerate(texts):
        if t:
            merged = merged.merge(extract_from_text(t, source=f"text:{i}"))
    if url and not merged.profile_url:
        merged.profile_url = url.split("?")[0]
    return merged
