"""Public Telegram channels via the t.me web preview — no API key, no account, no login.

t.me/s/<channel> renders the last ~20 posts as plain HTML for any public channel.
Private channels and group chats are not available this way (that needs a user account).
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from html import unescape

import httpx

from app.sources.base import Candidate, Source, SourceContext, register

PREVIEW = "https://t.me/s/{}"
POST_RE = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>\s*(?:<div class="tgme_widget_message_footer|<div class="tgme_widget_message_bubble)',
    re.S,
)
LINK_RE = re.compile(r'<a class="tgme_widget_message_date" href="([^"]+)"')
TIME_RE = re.compile(r'<time datetime="([^"]+)"')
TAGS_RE = re.compile(r"(?is)<br\s*/?>|</p>")
STRIP_RE = re.compile(r"(?is)<[^>]+>")


def _clean(html: str) -> str:
    return " ".join(unescape(STRIP_RE.sub(" ", TAGS_RE.sub("\n", html))).split())


@register
class TelegramSource(Source):
    type = "telegram"

    def fetch(self, ctx: SourceContext) -> list[Candidate]:
        channels = [c.strip().lstrip("@").removeprefix("https://t.me/").strip("/")
                    for c in ctx.config.get("channels", []) if c.strip()]
        keywords = [k.lower() for k in ctx.config.get("keywords", []) if k.strip()]
        out: list[Candidate] = []
        with httpx.Client(timeout=20.0, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (Macintosh) LeadFinder/1.0"}) as client:
            for channel in channels:
                try:
                    r = client.get(PREVIEW.format(channel))
                except httpx.HTTPError as exc:
                    ctx.log("warn", f"Telegram: @{channel}: {exc}")
                    continue
                if r.status_code != 200:
                    ctx.log("warn", f"Telegram: @{channel}: канал недоступен для публичного просмотра "
                                    f"(HTTP {r.status_code})")
                    continue
                texts = POST_RE.findall(r.text)
                links = LINK_RE.findall(r.text)
                stamps = TIME_RE.findall(r.text)
                kept = 0
                for i, raw in enumerate(texts):
                    text = _clean(raw)
                    if len(text) < 40:
                        continue
                    if keywords and not any(k in text.lower() for k in keywords):
                        continue
                    url = links[i] if i < len(links) else f"https://t.me/{channel}"
                    posted = None
                    if i < len(stamps):
                        try:
                            posted = datetime.fromisoformat(stamps[i]).date()
                        except ValueError:
                            posted = None
                    if ctx.since and posted and posted < ctx.since:
                        continue
                    out.append(Candidate(
                        url=url, title=text.split("\n")[0][:140], text=text[:3000], source=self.type,
                        platform="telegram", query=f"@{channel}", posted_at=posted, author=f"@{channel}",
                    ))
                    kept += 1
                ctx.log("info", f"Telegram: @{channel} → {kept} из {len(texts)} постов")
                time.sleep(1.0)
        return out
