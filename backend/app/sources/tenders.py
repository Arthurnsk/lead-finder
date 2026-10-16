"""State procurement and property auctions — official, stable, and the customer's contacts are public.

torgi.gov.ru  — land lots (auctions for sale/lease of plots): a lead for «сопровождение торгов».
zakupki.gov.ru — notices (44-ФЗ/223-ФЗ): organisations ordering cadastral/land works.
Both are federal systems: no keys, no scraping, documented endpoints, no CAPTCHAs.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from html import unescape

import feedparser
import httpx

from app.engine.ru_tls import gov_ssl_context
from app.sources.base import Candidate, Source, SourceContext, SourceError, register

TORGI_API = "https://torgi.gov.ru/new/api/public/lotcards/search"
TORGI_LOT = "https://torgi.gov.ru/new/public/lots/lot/{}"
ZAKUPKI_RSS = "https://zakupki.gov.ru/epz/order/extendedsearch/rss.html"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
TAGS = re.compile(r"(?is)<[^>]+>")
# Works this business actually performs — a notice must be ABOUT one of these
DEFAULT_SUBJECT_PATTERN = (r"кадастров\w*\s+(работ|услуг|учет|учёт)|межевани|землеустро|"
                           r"схем\w+\s+расположения|топографо-геодез|геодезическ\w+\s+работ|"
                           r"постановк\w+\s+на\s+кадастровый|оценк\w+\s+(земельн|рыночн)")


# The EIS wraps matched words in <span class="highlightColor">…</span>; replacing those with a space
# breaks words apart («межеван ию»), so they are removed without a separator.
SPANS = re.compile(r"(?is)</?span[^>]*>")


def _text(html: str, limit: int = 2500) -> str:
    return " ".join(unescape(TAGS.sub(" ", SPANS.sub("", html))).split())[:limit]


def _get(client: httpx.Client, url: str, params: dict, attempts: int = 3) -> httpx.Response | None:
    for attempt in range(attempts):
        try:
            r = client.get(url, params=params)
        except httpx.HTTPError:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(3 * (attempt + 1))
            continue
        return r
    return None


@register
class TendersSource(Source):
    """config: {"provider": "torgi"|"zakupki", "queries": [...], "regions": ["50","77"], "laws": ["fz44","fz223"]}"""

    type = "tenders"

    def fetch(self, ctx: SourceContext) -> list[Candidate]:
        provider = (ctx.config.get("provider") or "torgi").lower()
        queries = [q for q in ctx.config.get("queries", []) if q.strip()] or ["земельный участок"]
        with httpx.Client(timeout=30.0, follow_redirects=True, verify=gov_ssl_context(),
                          headers={"User-Agent": UA, "Accept": "application/json, */*"}) as client:
            if provider == "torgi":
                return self._torgi(client, ctx, queries)
            if provider == "zakupki":
                return self._zakupki(client, ctx, queries)
        raise SourceError(f"Неизвестный источник тендеров: {provider}")

    # ------------------------------------------------------------------ torgi.gov.ru

    def _torgi(self, client: httpx.Client, ctx: SourceContext, queries: list[str]) -> list[Candidate]:
        regions = [str(r) for r in ctx.config.get("regions", []) if str(r).strip()]
        out: list[Candidate] = []
        for q in queries:
            # only lots that are open right now; ZK = «Аренда и продажа земельных участков»
            params = {
                "text": q, "page": 0, "size": min(50, ctx.max_per_query * 5), "sort": "createDate,desc",
                "lotStatus": ctx.config.get("lot_status") or "PUBLISHED,APPLICATIONS_SUBMISSION",
                "biddType": ctx.config.get("bidd_type", "ZK"),
            }
            if regions:
                params["dynSubjRF"] = ",".join(regions)
            r = _get(client, TORGI_API, params)
            if r is None:
                raise SourceError("torgi.gov.ru не отвечает")
            if r.status_code != 200:
                ctx.log("warn", f"torgi.gov.ru: «{q}»: HTTP {r.status_code}")
                continue
            try:
                items = (r.json().get("content") or [])
            except ValueError:
                ctx.log("warn", f"torgi.gov.ru: «{q}»: неожиданный ответ")
                continue
            kept = 0
            for it in items:
                lot_id = it.get("id") or ""
                published = _parse_dt(it.get("createDate") or it.get("firstVersionPublicationDate"))
                if ctx.since and published and published < ctx.since:
                    continue
                name = (it.get("lotName") or "")[:400]
                body = " ".join(filter(None, [
                    name,
                    (it.get("lotDescription") or "")[:1500],
                    f"Тип торгов: {(it.get('biddType') or {}).get('name', '')}",
                    f"Начальная цена: {it.get('priceMin')}" if it.get("priceMin") else "",
                    f"Приём заявок до: {(it.get('biddEndTime') or '')[:10]}",
                    f"Статус: {it.get('lotStatus')}",
                    f"Регион (код): {it.get('subjectRFCode')}",
                ]))
                out.append(Candidate(
                    url=TORGI_LOT.format(lot_id), title=name[:140], text=body[:3000], source=self.type,
                    platform="tender", query=f"torgi: {q}", posted_at=published,
                    author=(it.get("biddType") or {}).get("name", ""),
                    extra={"lot_id": lot_id, "notice": it.get("noticeNumber"), "provider": "torgi"},
                ))
                kept += 1
            ctx.log("info", f"torgi.gov.ru: «{q}» → {kept} из {len(items)} лотов")
            time.sleep(1.0)
        return out

    # ------------------------------------------------------------------ zakupki.gov.ru

    def _zakupki(self, client: httpx.Client, ctx: SourceContext, queries: list[str]) -> list[Candidate]:
        laws = ctx.config.get("laws") or ["fz44", "fz223"]
        # The EIS search is fuzzy: a notice about rubbish removal matches «кадастровые работы» just
        # because the plot's cadastral NUMBER is in the text. Require the subject to be our work.
        subject_re = re.compile(ctx.config.get("subject_pattern") or DEFAULT_SUBJECT_PATTERN, re.I)
        out: list[Candidate] = []
        skipped = 0
        for q in queries:
            params = {"searchString": q, "morphology": "on", "pageNumber": 1, "sortDirection": "false",
                      "recordsPerPage": "_50", "sortBy": "UPDATE_DATE", "af": "on", "ca": "on"}
            params.update({law: "on" for law in laws})
            r = _get(client, ZAKUPKI_RSS, params)
            if r is None:
                raise SourceError("zakupki.gov.ru не отвечает")
            entries = feedparser.parse(r.content).entries
            kept = 0
            for e in entries:
                published = None
                st = e.get("published_parsed") or e.get("updated_parsed")
                if st:
                    published = date(st.tm_year, st.tm_mon, st.tm_mday)
                if ctx.since and published and published < ctx.since:
                    continue
                summary = _text(e.get("summary") or "", 4000)
                subject = _subject(summary)
                if not subject_re.search(subject):
                    skipped += 1  # the subject is something else entirely
                    continue
                customer = _customer(summary) or (e.get("author") or "")
                price = _PRICE_RE.search(summary)
                link = _fix_link(e.get("link") or "")
                body = " ".join(filter(None, [
                    f"Предмет закупки: {subject}",
                    f"Заказчик: {customer}" if customer else "",
                    f"Начальная цена: {price.group(1).strip()}" if price else "",
                    f"Извещение: {e.get('title', '')}",
                ]))
                out.append(Candidate(
                    url=link, title=subject[:200], text=body[:3000], source=self.type, platform="tender",
                    query=f"zakupki: {q}", posted_at=published, author=customer[:200],
                    extra={"provider": "zakupki", "customer": customer},
                ))
                kept += 1
            ctx.log("info", f"zakupki.gov.ru: «{q}» → {kept} из {len(entries)} извещений"
                            + (f", отсеяно по предмету: {skipped}" if skipped else ""))
            time.sleep(1.0)
        return out


def _parse_dt(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _fix_link(link: str) -> str:
    """The EIS feed glues its host in front of an already absolute url."""
    marker = "https://zakupki.gov.ru"
    return marker + link.split(marker)[-1] if link.count(marker) > 1 else link


_CUSTOMER_RE = re.compile(
    r"(?:Наименование Заказчика|Заказчик|Организатор)\s*[:\-]?\s*(.+?)"
    r"(?:\s*(?:Начальная цена|Размещение выполняется|Дата|$))", re.S | re.I)
# The feed prefixes every item with the search parameters — including OUR query, which otherwise
# ends up in the text and convinces the model that the notice is about our subject.
_BOILERPLATE_RE = re.compile(r"Параметры поиска:.*?Найденный результат:\s*", re.S | re.I)
_SUBJECT_RE = re.compile(r"Наименование объекта закупки\s*[:\-]?\s*(.+?)(?:Размещение выполняется|"
                         r"Наименование Заказчика|Начальная цена|$)", re.S | re.I)
_PRICE_RE = re.compile(r"Начальная цена контракта\s*[:\-]?\s*([\d\s.,]+)", re.I)


def _customer(summary: str) -> str:
    m = _CUSTOMER_RE.search(summary)
    return " ".join(m.group(1).split())[:200] if m else ""


def _subject(summary: str) -> str:
    """What is actually being procured, without the feed's own search-parameters header."""
    clean = _BOILERPLATE_RE.sub(" ", summary)
    m = _SUBJECT_RE.search(clean)
    return " ".join((m.group(1) if m else clean).split())[:1200]
