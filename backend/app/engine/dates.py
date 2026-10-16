"""Best-effort post date from a search snippet/title. Returns None when unsure."""

from __future__ import annotations

import re
from datetime import date, timedelta

_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "12 мар. 2021", "3 марта 2024 г.", "Mar 12, 2021"
_RU_TEXT_DATE = re.compile(r"\b(\d{1,2})\s+([а-яё]{3,9})\.?\s+(\d{4})\b", re.I)
_EN_TEXT_DATE = re.compile(r"\b([a-z]{3})[a-z]*\.?\s+(\d{1,2}),\s+(\d{4})\b", re.I)
# "12.03.2021", "2021-03-12"
_NUM_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# "3 дня назад", "2 weeks ago"
_AGO = re.compile(
    r"\b(\d{1,3})\s+(дн|день|дня|недел|месяц|час|минут|day|week|month|hour)\w*\s+(назад|ago)\b",
    re.I,
)


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def extract_post_date(text: str, today: date | None = None) -> date | None:
    """Return the most recent plausible date found in text (snippets lead with the post date)."""
    today = today or date.today()
    found: list[date] = []

    for m in _AGO.finditer(text):
        n, unit = int(m.group(1)), m.group(2).lower()
        if unit.startswith(("час", "минут", "hour")):
            days = 0
        elif unit.startswith(("недел", "week")):
            days = 7 * n
        elif unit.startswith(("месяц", "month")):
            days = 30 * n
        else:
            days = n
        found.append(today - timedelta(days=days))

    for m in _RU_TEXT_DATE.finditer(text):
        mon = _MONTHS.get(m.group(2).lower()[:3])
        if mon:
            found.append(_safe(int(m.group(3)), mon, int(m.group(1))))
    for m in _EN_TEXT_DATE.finditer(text):
        mon = _MONTHS.get(m.group(1).lower()[:3])
        if mon:
            found.append(_safe(int(m.group(3)), mon, int(m.group(2))))
    for m in _NUM_DATE.finditer(text):
        found.append(_safe(int(m.group(3)), int(m.group(2)), int(m.group(1))))
    for m in _ISO_DATE.finditer(text):
        found.append(_safe(int(m.group(1)), int(m.group(2)), int(m.group(3))))

    plausible = [d for d in found if d and date(2000, 1, 1) <= d <= today + timedelta(days=1)]
    return max(plausible) if plausible else None


def is_stale(posted: date | None, max_age_days: int, today: date | None = None) -> bool:
    if posted is None or max_age_days <= 0:
        return False
    return (today or date.today()) - posted > timedelta(days=max_age_days)
