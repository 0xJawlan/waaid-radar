"""The radar: compare the page with the saved state and publish what changed.

Per program it publishes, at most once each:
  new      — the first announcement, with every detail
  opens    — on the day the application opens (if it was announced earlier)
  closing  — the day before the application closes
and a reply when the application period changes (e.g. an extension).
Reminders for several programs on the same day go out as one grouped message.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html import escape

from . import render
from .config import Config
from .dates import fmt_range
from .models import Program, Status
from .store import load_state, save_state
from .telegram import TelegramError, strip_html
from .textutil import fold

log = logging.getLogger("waaid_radar")

ALERT_COOLDOWN = timedelta(hours=12)
HEARTBEAT_EVERY = timedelta(days=30)   # keeps the repo active so GitHub never pauses the schedule
PERSONAL_FORWARD_MAX = 3               # more than this → one summary message instead of forwards
SETTLED = {"new", "seeded", "seen_ended", "filtered"}


@dataclass
class Report:
    parsed: int = 0
    posted: list[str] = field(default_factory=list)
    reminders: list[str] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    first_run: bool = False
    saved: bool = False
    exit_code: int = 0

    def summary(self) -> str:
        return (f"parsed={self.parsed} posted={len(self.posted)} reminders={len(self.reminders)} "
                f"updates={len(self.updates)} alerts={self.alerts or '-'} errors={len(self.errors)} "
                f"first_run={self.first_run} state_saved={self.saved}")


def load_programs(cfg: Config, today: date) -> list[Program]:
    """Fetch and parse the live page (with the optional JavaScript fallback)."""
    from .fetch import fetch_html, fetch_rendered
    from .parser import parse_html

    if cfg.render_js == "true":
        return parse_html(fetch_rendered(cfg.url, user_agent=cfg.user_agent), today)
    programs = parse_html(fetch_html(cfg.url, user_agent=cfg.user_agent), today)
    if not programs and cfg.render_js == "auto":
        log.info("no programs in the static HTML, rendering the page with JavaScript")
        programs = parse_html(fetch_rendered(cfg.url, user_agent=cfg.user_agent), today)
    return programs


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _record_fields(p: Program) -> dict:
    return {
        "title": p.title, "company": p.company, "institution": p.institution, "country": p.country,
        "start": p.start, "period_raw": p.period_raw,
        "period_start": _iso(p.period_start), "period_end": _iso(p.period_end), "tags": p.tags,
    }


def _period_of(record: dict) -> str:
    start, end = record.get("period_start"), record.get("period_end")
    text = fmt_range(date.fromisoformat(start) if start else None, date.fromisoformat(end) if end else None)
    return text or record.get("period_raw") or "غير محددة"


class Radar:
    def __init__(
        self,
        cfg: Config,
        telegram,
        *,
        now: Callable[[], datetime] | None = None,
        load: Callable[[date], list[Program]] | None = None,
    ):
        self.cfg = cfg
        self.tg = telegram
        self._now = now or (lambda: datetime.now(cfg.tz))
        self._load = load or (lambda today: load_programs(cfg, today))

    # ------------------------------------------------------------------ run

    def run(self) -> Report:
        rep = Report()
        now = self._now()
        today = now.date()
        state = load_state(self.cfg.state_path)
        health = state["health"]

        try:
            programs = self._load(today)
        except Exception as exc:  # noqa: BLE001 — any failure here means the page could not be read
            log.exception("could not load the page")
            fails = int(health.get("consecutive_failures", 0)) + 1
            health["consecutive_failures"] = fails
            if fails >= 2:
                self._alert(state, now, rep, "fetch",
                            f"⚠️ تعذّر جلب صفحة مسار واعد ({fails} مرات متتالية).\n<code>{escape(str(exc)[:300])}</code>")
            rep.exit_code = 1 if fails >= 3 else 0  # one-off hiccups should not mark the workflow red
            rep.saved = self._save(state)
            return rep

        if health.pop("consecutive_failures", None):
            health.get("alerts", {}).pop("fetch", None)
        rep.parsed = len(programs)
        if not programs:
            self._alert(state, now, rep, "empty",
                        "⚠️ وصل الرادار إلى صفحة مسار واعد لكنه لم يجد فيها أي برنامج. "
                        "غالبًا تغيّر تصميم الصفحة: جرّب ضبط RENDER_JS على auto، أو راجع المحلل.")
            rep.exit_code = 1
            rep.saved = self._save(state)
            return rep
        last_count = health.get("last_count")
        if last_count and len(programs) < 0.5 * last_count:
            self._alert(state, now, rep, "drop",
                        f"⚠️ عدد البرامج في الصفحة نزل من {last_count} إلى {len(programs)}؛ "
                        "قد تكون الصفحة لم تُقرأ كاملة.")
        health["last_count"] = len(programs)

        rep.first_run = not state["programs"]
        quiet = self.cfg.is_quiet(now)
        live = {p.pid for p in programs}
        fresh: list[tuple[Program, dict]] = []
        for prog in reversed(programs):  # the page lists newest first; announce oldest first
            record = state["programs"].get(prog.pid) or self._adopt(state, prog, live)
            if record is None:
                record = {**_record_fields(prog), "first_seen": today.isoformat(), "posts": {}, "events": []}
                state["programs"][prog.pid] = record
            else:
                self._refresh(prog, record, today, quiet, rep)
            if not SETTLED & set(record["events"]) and self._introduce(prog, record, today, quiet, rep):
                fresh.append((prog, record))

        self._personal_new(fresh, today, quiet, rep)
        if not quiet:
            self._reminders(programs, state, today, rep)
        if rep.first_run:
            self._seed_report(len(programs), len(fresh), rep)
        meta = state["meta"]
        if not meta.get("heartbeat") or today - date.fromisoformat(meta["heartbeat"]) >= HEARTBEAT_EVERY:
            meta["heartbeat"] = today.isoformat()
        rep.saved = self._save(state)
        if rep.errors:
            rep.exit_code = 1
        return rep

    # ------------------------------------------------------------ programs

    def _adopt(self, state: dict, prog: Program, live: set[str]) -> dict | None:
        """Re-attach a record whose id changed because of a small edit on the page
        (same title, company and dates, and the old id is no longer on the page)."""
        if not (prog.period_start or prog.period_end):
            return None
        key = (fold(prog.title), fold(prog.company or ""), _iso(prog.period_start), _iso(prog.period_end))
        for pid, record in list(state["programs"].items()):
            if pid in live:
                continue
            if (fold(record.get("title") or ""), fold(record.get("company") or ""),
                    record.get("period_start"), record.get("period_end")) == key:
                state["programs"][prog.pid] = state["programs"].pop(pid)
                log.info("program id changed %s → %s (%s)", pid, prog.pid, prog.title)
                return state["programs"][prog.pid]
        return None

    def _introduce(self, prog: Program, record: dict, today: date, quiet: bool, rep: Report) -> bool:
        status = prog.status(today)
        if rep.first_run and not (self.cfg.seed_post_active and status in (Status.OPEN, Status.UPCOMING)):
            record["events"].append("seeded")
            return False
        if status is Status.ENDED:
            record["events"].append("seen_ended")
            return False
        if not self.cfg.posts_to_main(prog):
            record["events"].append("filtered")
            return False
        try:
            message_id = self.tg.send(self.cfg.main_chat, render.program_post(prog, today, self.cfg.url), silent=quiet)
        except TelegramError as exc:  # the record stays unsettled, so the next run retries
            log.error("posting %s failed: %s", prog.title, exc)
            rep.errors.append(f"{prog.title}: {exc}")
            return False
        record["posts"]["main"] = message_id
        record["events"].append("new")
        rep.posted.append(prog.title)
        return True

    def _refresh(self, prog: Program, record: dict, today: date, quiet: bool, rep: Report) -> None:
        old = (record.get("period_start"), record.get("period_end"))
        new = (_iso(prog.period_start), _iso(prog.period_end))
        changed = all(new) and any(old) and new != old
        if changed and "new" in record["events"] and prog.status(today) is not Status.ENDED:
            link = render.post_link(self.cfg.channel, record["posts"].get("main"))
            try:
                self.tg.send(self.cfg.main_chat, render.period_update(prog, _period_of(record), today),
                             reply_to=record["posts"].get("main"), silent=quiet)
                if self._personal_target() and self.cfg.wants(prog):
                    self.tg.send(self._personal_target(), render.period_update(prog, _period_of(record), today, link),
                                 silent=quiet)
            except TelegramError as exc:  # keep the old dates so the update is retried
                rep.errors.append(f"update {prog.title}: {exc}")
                return
            rep.updates.append(prog.title)
        if changed:
            if old[0] != new[0]:
                record["events"] = [e for e in record["events"] if e != "opens"]
            if old[1] != new[1]:
                record["events"] = [e for e in record["events"] if e != "closing"]
        record.update(_record_fields(prog))

    # ------------------------------------------------------------ personal

    def _personal_target(self) -> str | None:
        target = self.cfg.personal_chat
        return target if target and target != self.cfg.main_chat else None

    def _personal_new(self, fresh: list[tuple[Program, dict]], today: date, quiet: bool, rep: Report) -> None:
        target = self._personal_target()
        mine = [(p, r) for p, r in fresh if self.cfg.wants(p)] if target else []
        if not mine:
            return
        try:
            if len(mine) <= PERSONAL_FORWARD_MAX and self.cfg.channel:
                for _, record in mine:
                    self.tg.forward(target, self.cfg.channel, record["posts"]["main"], silent=quiet)
            else:
                items = [(p, render.post_link(self.cfg.channel, r["posts"].get("main"))) for p, r in mine]
                for text in render.personal_summary(items, today):
                    self.tg.send(target, text, silent=quiet)
        except TelegramError as exc:
            rep.errors.append(f"personal alert: {exc}")

    # ------------------------------------------------------------ reminders

    def _remindable(self, prog: Program, record: dict) -> bool:
        return "new" in record["events"] or ("seeded" in record["events"] and self.cfg.posts_to_main(prog))

    def _reminders(self, programs: list[Program], state: dict, today: date, rep: Report) -> None:
        tomorrow = today + timedelta(days=1)
        opening: list[tuple[Program, dict]] = []
        closing: list[tuple[Program, dict]] = []
        for prog in programs:
            record = state["programs"].get(prog.pid)
            if not record or not self._remindable(prog, record):
                continue
            if record.get("first_seen", "") >= today.isoformat() or prog.status(today) is Status.ENDED:
                continue  # announced today: the announcement already says where things stand
            if prog.period_start == today and "opens" not in record["events"]:
                opening.append((prog, record))
            elif prog.period_end == tomorrow and "closing" not in record["events"]:
                closing.append((prog, record))
        self._send_reminders("opens", opening, today, rep)
        self._send_reminders("closing", closing, today, rep)

    def _send_reminders(self, kind: str, items: list[tuple[Program, dict]], today: date, rep: Report) -> None:
        if not items:
            return
        items.sort(key=lambda item: (item[0].company or "", item[0].title))
        build = render.opening_messages if kind == "opens" else render.closing_messages
        link = lambda record: render.post_link(self.cfg.channel, record["posts"].get("main"))  # noqa: E731
        try:
            if len(items) == 1:
                prog, record = items[0]
                self.tg.send(self.cfg.main_chat, build([(prog, None)], today)[0], reply_to=record["posts"].get("main"))
            else:
                for text in build([(p, link(r)) for p, r in items], today):
                    self.tg.send(self.cfg.main_chat, text)
        except TelegramError as exc:
            rep.errors.append(f"{kind} reminder: {exc}")
            return
        tomorrow = today + timedelta(days=1)
        for prog, record in items:
            record["events"].append(kind)
            if kind == "opens" and prog.period_end == tomorrow:
                record["events"].append("closing")  # the opening message already gives the deadline
            rep.reminders.append(f"{kind}: {prog.title}")

        target = self._personal_target()
        mine = [(p, link(r)) for p, r in items if self.cfg.wants(p)] if target else []
        try:
            for text in build(mine, today) if mine else []:
                self.tg.send(target, text)
        except TelegramError as exc:
            rep.errors.append(f"personal {kind} reminder: {exc}")

    # ------------------------------------------------------------ admin

    def _seed_report(self, parsed: int, posted: int, rep: Report) -> None:
        if not self.cfg.admin_chat:
            return
        lines = ["✅ <b>رادار واعد يعمل الآن</b>", "", f"قرأ {render.count_phrase(parsed)} من صفحة المسار."]
        lines.append(f"ونشر {render.count_phrase(posted)} لم ينتهِ تقديمها بعد." if posted
                     else "لا يوجد حاليًا برنامج مفتوح أو قادم.")
        lines.append("وسيتابع الصفحة تلقائيًا وينبّه بأي جديد.")
        try:
            self.tg.send(self.cfg.admin_chat, "\n".join(lines))
        except TelegramError as exc:
            rep.errors.append(f"seed report: {exc}")

    def _alert(self, state: dict, now: datetime, rep: Report, key: str, text: str) -> None:
        rep.alerts.append(key)
        log.warning(strip_html(text))
        alerts = state["health"].setdefault("alerts", {})
        last = alerts.get(key)
        if last and now - datetime.fromisoformat(last) < ALERT_COOLDOWN:
            return
        if not self.cfg.admin_chat:
            return
        try:
            self.tg.send(self.cfg.admin_chat, text)
            alerts[key] = now.isoformat(timespec="minutes")
        except TelegramError as exc:
            log.error("could not deliver the alert: %s", exc)

    def _save(self, state: dict) -> bool:
        return False if self.cfg.dry_run else save_state(self.cfg.state_path, state)

    # ------------------------------------------------------------ digest

    def digest(self) -> Report:
        """A summary of every program that is open now or opens soon."""
        rep = Report()
        now = self._now()
        today = now.date()
        state = load_state(self.cfg.state_path)
        try:
            programs = self._load(today)
        except Exception as exc:  # noqa: BLE001
            log.exception("could not load the page")
            rep.errors.append(str(exc))
            rep.exit_code = 1
            return rep
        rep.parsed = len(programs)

        def item(p: Program):
            record = state["programs"].get(p.pid) or {}
            return p, render.post_link(self.cfg.channel, record.get("posts", {}).get("main"))

        chosen = [p for p in programs if self.cfg.posts_to_main(p)]
        opened = sorted((p for p in chosen if p.status(today) is Status.OPEN), key=lambda p: p.period_end or date.max)
        upcoming = sorted((p for p in chosen if p.status(today) is Status.UPCOMING), key=lambda p: p.period_start)
        if not opened and not upcoming:
            log.info("digest: nothing open or upcoming, nothing sent")
            return rep
        try:
            for text in render.digest_messages([item(p) for p in opened], [item(p) for p in upcoming], today):
                self.tg.send(self.cfg.main_chat, text, silent=self.cfg.is_quiet(now))
        except TelegramError as exc:
            rep.errors.append(f"digest: {exc}")
            rep.exit_code = 1
        rep.posted = [p.title for p in opened + upcoming]
        return rep
