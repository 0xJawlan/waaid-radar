"""Telegram message templates (HTML parse mode)."""

from __future__ import annotations

from datetime import date
from html import escape

from .dates import days_phrase, fmt_date, fmt_range
from .models import Program, Status
from .textutil import fold

LIMIT = 3900  # Telegram allows 4096 characters; keep a margin for formatting

Item = tuple[Program, "str | None"]  # a program and the link to its channel post


def _e(text: str | None) -> str:
    return escape(text or "", quote=False)


def _attr(text: str) -> str:
    return escape(text, quote=True)


def count_phrase(n: int) -> str:
    """برنامج واحد، برنامجين، 3 برامج، 11 برنامجًا."""
    if n == 1:
        return "برنامج واحد"
    if n == 2:
        return "برنامجين"
    if 3 <= n <= 10:
        return f"{n} برامج"
    return f"{n} برنامجًا"


def post_link(channel: str | None, message_id: int | None) -> str | None:
    if not channel or not message_id:
        return None
    channel = str(channel)
    if channel.startswith("@"):
        return f"https://t.me/{channel[1:]}/{message_id}"
    if channel.startswith("-100"):
        return f"https://t.me/c/{channel[4:]}/{message_id}"
    return None


def _closes_in(p: Program, today: date) -> str:
    days = (p.period_end - today).days
    if days <= 0:
        return "اليوم آخر يوم"
    if days == 1:
        return "يُغلق غدًا"
    return f"يُغلق بعد {days_phrase(days)}"


def status_text(p: Program, today: date) -> str:
    status = p.status(today)
    if status is Status.UPCOMING and p.period_start:
        days = (p.period_start - today).days
        return "يبدأ غدًا" if days == 1 else f"يبدأ بعد {days_phrase(days)}"
    if status is Status.OPEN:
        return f"مفتوح — {_closes_in(p, today)}" if p.period_end else "مفتوح الآن"
    if status is Status.ENDED:
        return "انتهى التقديم"
    return ""


def period_text(p: Program, today: date) -> str:
    when = fmt_range(p.period_start, p.period_end) or (p.period_raw or "")
    return " · ".join(part for part in (when, status_text(p, today)) if part)


STATUS_LINE = {
    Status.UPCOMING: "🔜 <b>الحالة:</b> لم يبدأ التقديم بعد",
    Status.OPEN: "🟢 <b>الحالة:</b> التقديم مفتوح",
    Status.ENDED: "🔴 <b>الحالة:</b> انتهى التقديم",
}


def program_post(p: Program, today: date, page_url: str) -> str:
    """The full announcement of one program.

    The post stays in the channel, so it carries fixed dates and a status label
    only (never «يُغلق بعد 3 أيام»); the engine edits it when either changes.
    Countdowns belong in reminders, which are read when they arrive.
    """
    title = [f"<b>{_e(p.title)}</b>"]
    if p.program and fold(p.program) != fold(p.title):
        title.append(_e(p.program))
    fields = [
        f"{icon} <b>{label}:</b> {_e(value)}"
        for icon, label, value in (
            ("🏢", "الشركة", p.company),
            ("🎓", "الجهة التعليمية", p.institution),
            ("🌍", "الدولة", p.country),
            ("⏳", "المدة", p.duration),
            ("🗓", "بداية الدراسة", p.start),
            ("📝", "فترة التقديم", fmt_range(p.period_start, p.period_end) or p.period_raw),
        )
        if value
    ]
    status = STATUS_LINE.get(p.status(today))
    if status:
        fields.append(status)
    footer = ([" ".join(f"#{t}" for t in p.tags)] if p.tags else []) + [
        f'<a href="{_attr(page_url)}">صفحة المسار في موقع الوزارة</a>'
    ]

    conditions = list(p.conditions)
    trimmed = False
    while True:
        parts = ["🆕 <b>برنامج جديد — مسار واعد</b>", "\n".join(title), "\n".join(fields)]
        if conditions:
            lines = [f"• {_e(c)}" for c in conditions]
            if trimmed:
                lines.append("• … بقية الشروط في صفحة المسار")
            parts.append("<b>الشروط:</b>\n<blockquote expandable>" + "\n".join(lines) + "</blockquote>")
        parts.append("\n".join(footer))
        text = "\n\n".join(part for part in parts if part)
        if len(text) <= LIMIT or not conditions:
            return text
        conditions.pop()
        trimmed = True


def _item(p: Program, link: str | None, note: str = "") -> str:
    name = f'<a href="{_attr(link)}">{_e(p.title)}</a>' if link else f"<b>{_e(p.title)}</b>"
    line = f"• {name}"
    if p.company:
        line += f" — {_e(p.company)}"
    if note:
        line += f" · {_e(note)}"
    return line


def _chunks(header: str, lines: list[str]) -> list[str]:
    """Split a long list across messages, repeating the header."""
    messages: list[str] = []
    current = header + "\n"
    for line in lines:
        if len(current) + len(line) + 1 > LIMIT and current.strip() != header:
            messages.append(current.rstrip())
            current = header + " (تابع)\n"
        current += "\n" + line
    messages.append(current.rstrip())
    return messages


def _single(icon_title: str, p: Program, link: str | None, extra: str | None) -> list[str]:
    lines = [icon_title, "", f"<b>{_e(p.title)}</b>"]
    if p.company:
        lines.append(_e(p.company))
    if extra:
        lines.append(extra)
    if link:
        lines.append(f'<a href="{_attr(link)}">تفاصيل البرنامج</a>')
    return ["\n".join(lines)]


def opening_messages(items: list[Item], today: date) -> list[str]:
    if len(items) == 1:
        p, link = items[0]
        extra = f"📝 آخر موعد: {fmt_date(p.period_end)} ({_closes_in(p, today)})" if p.period_end else None
        return _single("🔔 <b>بدأ التقديم اليوم</b>", p, link, extra)
    header = f"🔔 <b>بدأ اليوم التقديم على {count_phrase(len(items))}</b>"
    return _chunks(header, [_item(p, link, f"حتى {fmt_date(p.period_end)}" if p.period_end else "")
                            for p, link in items])


def closing_messages(items: list[Item], today: date) -> list[str]:
    if len(items) == 1:
        p, link = items[0]
        extra = f"📝 آخر موعد: {fmt_date(p.period_end)}" if p.period_end else None
        return _single("⏰ <b>غدًا آخر يوم للتقديم</b>", p, link, extra)
    header = f"⏰ <b>غدًا آخر يوم للتقديم على {count_phrase(len(items))}</b>"
    return _chunks(header, [_item(p, link) for p, link in items])


def period_update(p: Program, old_period: str, today: date, link: str | None = None) -> str:
    lines = ["✏️ <b>تحديث في فترة التقديم</b>", "", f"<b>{_e(p.title)}</b>"]
    if p.company:
        lines.append(_e(p.company))
    lines += [f"السابق: {_e(old_period)}", f"الجديد: {_e(period_text(p, today))}"]
    if link:
        lines.append(f'<a href="{_attr(link)}">تفاصيل البرنامج</a>')
    return "\n".join(lines)


def digest_messages(open_items: list[Item], upcoming_items: list[Item], today: date) -> list[str]:
    lines: list[str] = []
    if open_items:
        lines.append(f"<b>مفتوح الآن ({len(open_items)})</b>")
        lines += [_item(p, link, _closes_in(p, today) if p.period_end else "") for p, link in open_items]
    if upcoming_items:
        if lines:
            lines.append("")
        lines.append(f"<b>يفتح قريبًا ({len(upcoming_items)})</b>")
        lines += [_item(p, link, f"يبدأ {fmt_date(p.period_start)}") for p, link in upcoming_items]
    return _chunks(f"📋 <b>ملخص مسار واعد</b> — {fmt_date(today)}", lines)


def personal_summary(items: list[Item], today: date) -> list[str]:
    header = f"📌 <b>برامج جديدة تطابق اهتماماتك ({len(items)})</b>"
    return _chunks(header, [_item(p, link, status_text(p, today)) for p, link in items])
