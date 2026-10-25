"""Arabic date ranges as written on the page, e.g. «من 25 أكتوبر 2026م إلى 5 نوفمبر 2026م».

Handles the variants seen in practice: Arabic-Indic digits, numeric dates
(23/7/2025), a year written only once («من 3 أغسطس إلى 17 أغسطس 2026»),
ranges across a new year, missing spaces («إلى13 أغسطس») and «وحتى».
"""

from __future__ import annotations

import re
from datetime import date

from .textutil import clean

_MONTHS = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "ابريل": 4, "مايو": 5, "يونيو": 6, "يونيه": 6,
    "يوليو": 7, "يوليه": 7, "اغسطس": 8, "سبتمبر": 9, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
}
MONTH_NAMES = ("", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
               "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")

_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_TOKEN = re.compile(
    r"(?P<nd>\d{1,2})\s*[/\-]\s*(?P<nm>\d{1,2})\s*[/\-]\s*(?P<ny>\d{4})"
    rf"|(?P<d>\d{{1,2}})\s*(?P<m>{_MONTH_ALT})\s*(?P<y>\d{{4}})?"
)
_UNTIL_BEFORE = re.compile(r"(?:حتى|الى|لغاية)\s*$")


def parse_period(text: str | None, ref: date | None = None) -> tuple[date | None, date | None]:
    """Return (start, end) of an application period; either may be None."""
    if not text:
        return None, None
    norm = re.sub("[أإآ]", "ا", clean(text))
    tokens: list[tuple[int, int, int | None, int]] = []
    for m in _TOKEN.finditer(norm):
        if m.group("nd"):
            day, month, year = int(m.group("nd")), int(m.group("nm")), int(m.group("ny"))
        else:
            day, month = int(m.group("d")), _MONTHS[m.group("m")]
            year = int(m.group("y")) if m.group("y") else None
        if 1 <= day <= 31 and 1 <= month <= 12:
            tokens.append((day, month, year, m.start()))
    if not tokens:
        return None, None

    fallback_year = ref.year if ref else None
    if len(tokens) == 1:
        day, month, year, pos = tokens[0]
        single = _make(year or fallback_year, month, day)
        return (None, single) if _UNTIL_BEFORE.search(norm[:pos]) else (single, None)

    (d1, m1, y1, _), (d2, m2, y2, _) = tokens[0], tokens[1]
    if y1 is None and y2 is None:
        y1 = y2 = fallback_year
        if y1 is not None and (m2, d2) < (m1, d1):
            y2 = y1 + 1
    elif y1 is None:
        y1 = y2 if (m1, d1) <= (m2, d2) else y2 - 1
    elif y2 is None:
        y2 = y1 if (m2, d2) >= (m1, d1) else y1 + 1
    return _make(y1, m1, d1), _make(y2, m2, d2)


def _make(year: int | None, month: int, day: int) -> date | None:
    if year is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def fmt_date(d: date) -> str:
    return f"{d.day} {MONTH_NAMES[d.month]} {d.year}"


def fmt_range(start: date | None, end: date | None) -> str:
    if start and end:
        if start.year != end.year:
            return f"{fmt_date(start)} – {fmt_date(end)}"
        if start.month != end.month:
            return f"{start.day} {MONTH_NAMES[start.month]} – {end.day} {MONTH_NAMES[end.month]} {end.year}"
        if start.day != end.day:
            return f"{start.day}–{end.day} {MONTH_NAMES[end.month]} {end.year}"
        return fmt_date(end)
    if end:
        return f"حتى {fmt_date(end)}"
    if start:
        return f"من {fmt_date(start)}"
    return ""


def days_phrase(n: int) -> str:
    """Arabic count of days: يوم واحد، يومين، 3 أيام، 11 يومًا."""
    if n == 1:
        return "يوم واحد"
    if n == 2:
        return "يومين"
    if 3 <= n <= 10:
        return f"{n} أيام"
    return f"{n} يومًا"
