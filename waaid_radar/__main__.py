"""Command line: python -m waaid_radar {run,digest,preview,check}."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from .config import Config, ConfigError, load_dotenv
from .engine import Radar, load_programs
from .fetch import FetchError
from .models import Program, Status
from .parser import parse_html, parse_text
from .render import count_phrase, period_text
from .telegram import DryRunTelegram, Telegram, TelegramError

STATUS_AR = {Status.OPEN: "مفتوح", Status.UPCOMING: "قادم", Status.ENDED: "منتهٍ", Status.UNKNOWN: "غير معروف"}


def _client(cfg: Config):
    return DryRunTelegram() if cfg.dry_run else Telegram(cfg.token)


def _read_file(path: str, today) -> list[Program]:
    """Parse a saved copy of the page (HTML, or the page's text)."""
    raw = Path(path).read_text(encoding="utf-8")
    return parse_html(raw, today) if "<" in raw[:2000] else parse_text(raw, today)


def _radar(cfg: Config, file: str | None) -> Radar:
    cfg.require_telegram()
    load = (lambda today: _read_file(file, today)) if file else None
    return Radar(cfg, _client(cfg), load=load)


def cmd_run(cfg: Config, file: str | None = None) -> int:
    report = _radar(cfg, file).run()
    logging.info(report.summary())
    for error in report.errors:
        logging.error(error)
    return report.exit_code


def cmd_digest(cfg: Config, file: str | None = None) -> int:
    report = _radar(cfg, file).digest()
    logging.info(report.summary())
    return report.exit_code


def _as_dict(p: Program, today) -> dict:
    return {
        "id": p.pid, "status": p.status(today).value, "title": p.title, "company": p.company,
        "program": p.program, "institution": p.institution, "country": p.country,
        "duration": p.duration, "start": p.start, "period": p.period_raw,
        "period_start": p.period_start.isoformat() if p.period_start else None,
        "period_end": p.period_end.isoformat() if p.period_end else None,
        "degree": p.degree, "tags": p.tags, "conditions": p.conditions,
    }


def cmd_preview(cfg: Config, file: str | None, as_json: bool, show_all: bool) -> int:
    today = datetime.now(cfg.tz).date()
    try:
        programs = _read_file(file, today) if file else load_programs(cfg, today)
    except FetchError as exc:
        logging.error("تعذّر جلب الصفحة: %s", exc)
        return 1
    shown = programs if show_all else [p for p in programs if p.status(today) is not Status.ENDED]
    if as_json:
        print(json.dumps([_as_dict(p, today) for p in shown], ensure_ascii=False, indent=1))
    else:
        for p in shown:
            print(f"\n[{STATUS_AR[p.status(today)]}] {p.title}")
            for label, value in (("الشركة", p.company), ("البرنامج", p.program), ("الجهة", p.institution),
                                 ("الدولة", p.country), ("المدة", p.duration), ("البداية", p.start),
                                 ("التقديم", period_text(p, today))):
                if value:
                    print(f"   {label}: {value}")
            print(f"   الوسوم: {' '.join('#' + t for t in p.tags)}   ({len(p.conditions)} شروط)")
    counts = Counter(p.status(today) for p in programs)
    missing = {name: sum(1 for p in programs if not getattr(p, attr))
               for name, attr in (("بدون شركة", "company"), ("بدون فترة تقديم", "period_start"))}
    summary = " · ".join(f"{STATUS_AR[s]}: {n}" for s, n in counts.items())
    gaps = " · ".join(f"{k}: {v}" for k, v in missing.items())
    print(f"\nالمجموع {count_phrase(len(programs))} — {summary} — {gaps}", file=sys.stderr)
    return 0 if programs else 1


def cmd_check(cfg: Config, send_test: bool) -> int:
    ok = True

    def report(good: bool, message: str) -> None:
        nonlocal ok
        ok = ok and good
        print(("✓ " if good else "✗ ") + message)

    if not cfg.token:
        report(False, "TELEGRAM_BOT_TOKEN غير مضبوط")
        return 1
    tg = Telegram(cfg.token)
    try:
        me = tg.get_me()
        report(True, f"البوت: @{me['username']}")
    except TelegramError as exc:
        report(False, f"التوكن غير صحيح: {exc.description}")
        return 1

    if cfg.channel:
        try:
            chat = tg.get_chat(cfg.channel)
            member = tg.get_chat_member(cfg.channel, me["id"])
            can_post = member.get("status") == "creator" or (
                member.get("status") == "administrator" and member.get("can_post_messages", True))
            report(True, f"القناة: {chat.get('title')} ({cfg.channel})")
            report(can_post, "البوت مشرف ويقدر ينشر في القناة" if can_post
                   else "البوت ليس مشرفًا بصلاحية النشر — أضِفه مشرفًا مع صلاحية «نشر الرسائل»")
        except TelegramError as exc:
            report(False, f"تعذّر الوصول للقناة {cfg.channel}: {exc.description} — تأكد من المعرّف وأن البوت مشرف فيها")
    else:
        print("• لا توجد قناة: كل شيء سيُرسل لمحادثتك الخاصة")

    if cfg.admin_chat:
        try:
            tg.get_chat(cfg.admin_chat)
            report(True, f"المحادثة الخاصة ({cfg.admin_chat}) جاهزة")
            if send_test:
                tg.send(cfg.admin_chat, "✅ رسالة تجربة من رادار واعد — الإعدادات سليمة.")
                report(True, "أُرسلت رسالة تجربة")
        except TelegramError as exc:
            report(False, f"تعذّر الوصول لمحادثتك {cfg.admin_chat}: {exc.description} — أرسل /start للبوت أولًا")
    else:
        report(False, "TELEGRAM_ADMIN_CHAT_ID غير مضبوط: لن تصلك تنبيهات الأعطال")

    tags = "معطّلة" if cfg.personal_tags is None else ("كل البرامج" if "*" in cfg.personal_tags
                                                      else " ".join("#" + t for t in sorted(cfg.personal_tags)))
    print(f"• التنبيهات الخاصة: {tags}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="waaid_radar", description="رادار مسار واعد")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("run", "فحص الصفحة ونشر الجديد والتذكيرات"), ("digest", "ملخص البرامج المفتوحة والقادمة")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--file", help="ملف HTML أو نص محلي بدل جلب الصفحة")
    preview = sub.add_parser("preview", help="عرض البرامج المستخرجة بدون نشر")
    preview.add_argument("--file", help="ملف HTML أو نص محلي بدل جلب الصفحة")
    preview.add_argument("--json", action="store_true", help="إخراج JSON")
    preview.add_argument("--all", action="store_true", help="يشمل البرامج المنتهية")
    check = sub.add_parser("check", help="التحقق من إعدادات تلقرام")
    check.add_argument("--send-test", action="store_true", help="إرسال رسالة تجربة لمحادثتك")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        load_dotenv()
        cfg = Config.from_env()
        if args.command == "run":
            return cmd_run(cfg, args.file)
        if args.command == "digest":
            return cmd_digest(cfg, args.file)
        if args.command == "preview":
            return cmd_preview(cfg, args.file, args.json, args.all)
        return cmd_check(cfg, args.send_test)
    except ConfigError as exc:
        logging.error("إعداد ناقص: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
