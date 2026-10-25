import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from waaid_radar.config import Config
from waaid_radar.engine import Radar
from waaid_radar.parser import parse_text
from waaid_radar.telegram import DryRunTelegram, TelegramError

TZ = ZoneInfo("Asia/Riyadh")
CHANNEL, ME = "@waaid_radar", "111"

NEW_BLOCK = (
    "ماجستير في هندسة البيانات​بدء التقديم على برنامج الابتعاث المبتدئ بالتوظيف في شركة نون التعليمية "
    "ضمن مسار واعد البرنامج: Master in Data Engineering مدة البرنامج: سنة واحدة المركز التدريبي: جامعة تورنتو "
    "الدولة: كندا بداية الدراسة: سبتمبر 2027 فترة التقديم:من 20 أكتوبر 2026م إلى 30 أكتوبر 2026م "
    "شارك:الشروط الخاصة بالبرنامج:أن يكون المتقدم سعودي الجنسية.بكالوريوس في علوم الحاسب.شارك:"
)
CULINARY_BLOCK = (
    "دبلوم فنون الطهي​بدء التقديم على برنامج الابتعاث المبتدئ بالتوظيف في شركة القدية للاستثمار "
    "ضمن مسار واعد: مدة البرنامج: 9 أشهر المعهد: معهد دوكاس الدولة: فرنسا بداية الدراسة: يناير 2027 "
    "فترة التقديم:من 20 أكتوبر 2026م إلى 30 أكتوبر 2026م "
    "شارك:الشروط الخاصة بالبرنامج:أن يكون المتقدم سعودي الجنسية.شارك:"
)


def at(month, day, hour=10, minute=0):
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


def with_block(page: str, block: str) -> str:
    """Insert a block at the top of the list, as the ministry does for new programs."""
    header, rest = page.split("\n", 1)
    return f"{header}\n{block}\n{rest}"


class Harness:
    def __init__(self, tmp_path, page, **overrides):
        settings = {"token": "t", "channel": CHANNEL, "admin_chat": ME, "state_path": tmp_path / "state.json"}
        settings.update(overrides)
        self.cfg = Config(**settings)
        self.tg = DryRunTelegram(out=lambda _: None)
        self.page = page

    def run(self, when, page=None):
        page = self.page if page is None else page
        return Radar(self.cfg, self.tg, now=lambda: when, load=lambda d: parse_text(page, d)).run()

    def digest(self, when):
        return Radar(self.cfg, self.tg, now=lambda: when, load=lambda d: parse_text(self.page, d)).digest()

    def sent(self, chat=None, since=0):
        return [m for m in self.tg.sent[since:] if chat is None or m["chat_id"] == chat]

    def state(self):
        return json.loads(self.cfg.state_path.read_text(encoding="utf-8"))


@pytest.fixture
def h(tmp_path, lines_text):
    return Harness(tmp_path, lines_text)


def test_first_run_publishes_only_what_is_still_open(h):
    rep = h.run(at(10, 24, 20, 30))
    assert rep.first_run and rep.exit_code == 0 and rep.parsed == 26
    channel = h.sent(CHANNEL)
    assert len(channel) == 11 and all("STC" in m["text"] for m in channel)
    assert not any(m["silent"] for m in channel)
    mine = h.sent(ME)
    assert len(mine) == 2  # one summary of the 11 matching programs + the start-up report
    assert "برامج جديدة تطابق اهتماماتك (11)" in mine[0]["text"]
    assert "https://t.me/waaid_radar/" in mine[0]["text"]
    assert "رادار واعد يعمل الآن" in mine[1]["text"] and "26 برنامجًا" in mine[1]["text"]
    events = [r["events"] for r in h.state()["programs"].values()]
    assert events.count(["new"]) == 11 and events.count(["seeded"]) == 15


def test_nothing_new_means_no_messages_and_no_state_change(h):
    h.run(at(10, 24, 20, 30))
    before = len(h.tg.sent)
    rep = h.run(at(10, 24, 23, 30))
    assert len(h.tg.sent) == before and not rep.saved


def test_new_program_is_posted_and_forwarded(h):
    h.run(at(10, 24, 12))
    before = len(h.tg.sent)
    rep = h.run(at(10, 24, 15), page=with_block(h.page, NEW_BLOCK))
    assert rep.posted == ["ماجستير في هندسة البيانات"]
    channel_post, forward = h.sent(since=before)
    assert channel_post["chat_id"] == CHANNEL and "جامعة تورنتو" in channel_post["text"]
    assert "#علم_البيانات" in channel_post["text"] and "#كندا" in channel_post["text"]
    assert forward == {**forward, "kind": "forward", "chat_id": ME, "from_chat_id": CHANNEL,
                       "forwarded": channel_post["message_id"]}


def test_programs_outside_personal_tags_reach_the_channel_only(h):
    h.run(at(10, 24, 12))
    before = len(h.tg.sent)
    h.run(at(10, 24, 15), page=with_block(h.page, CULINARY_BLOCK))
    assert [m["chat_id"] for m in h.sent(since=before)] == [CHANNEL]


def test_opening_day_reminder_is_grouped_and_sent_once(h):
    h.run(at(10, 24, 20, 30))
    before = len(h.tg.sent)
    rep = h.run(at(10, 25, 9, 17))
    channel = h.sent(CHANNEL, since=before)
    assert len(channel) == 1
    assert "بدأ اليوم التقديم على 11 برنامجًا" in channel[0]["text"]
    assert channel[0]["text"].count("https://t.me/waaid_radar/") == 11
    assert len(h.sent(ME, since=before)) == 1
    assert len(rep.reminders) == 11
    before = len(h.tg.sent)
    h.run(at(10, 25, 15, 17))
    assert len(h.tg.sent) == before


def test_reminders_wait_until_quiet_hours_end(h):
    h.run(at(10, 24, 20, 30))
    before = len(h.tg.sent)
    h.run(at(10, 25, 3, 17))
    assert len(h.tg.sent) == before
    h.run(at(10, 25, 9, 17))
    assert len(h.tg.sent) > before


def test_new_posts_at_night_are_silent(h):
    h.run(at(10, 24, 12))
    before = len(h.tg.sent)
    h.run(at(10, 25, 2), page=with_block(h.page, NEW_BLOCK))
    assert all(m["silent"] for m in h.sent(since=before))


def test_closing_reminder_the_day_before(h):
    h.run(at(10, 24, 12))
    h.run(at(10, 25, 9))
    before = len(h.tg.sent)
    h.run(at(11, 4, 9))
    channel = h.sent(CHANNEL, since=before)
    assert len(channel) == 1 and "غدًا آخر يوم للتقديم على 11 برنامجًا" in channel[0]["text"]
    assert all("closing" in r["events"] for r in h.state()["programs"].values() if "new" in r["events"])


def test_single_reminder_replies_to_its_post(tmp_path, lines_text):
    header, first, *_ = lines_text.split("\n")
    h = Harness(tmp_path, f"{header}\n{first}")
    h.run(at(10, 24, 12))
    post_id = h.sent(CHANNEL)[0]["message_id"]
    before = len(h.tg.sent)
    h.run(at(10, 25, 9))
    reminder = h.sent(CHANNEL, since=before)[0]
    assert reminder["reply_to"] == post_id and "بدأ التقديم اليوم" in reminder["text"]
    assert "آخر موعد: 5 نوفمبر 2026" in reminder["text"]


def test_deadline_extension_posts_update_and_rearms_reminder(h):
    h.run(at(10, 24, 12))
    h.run(at(10, 25, 9))
    h.run(at(11, 4, 9))  # closing reminders for 5 November go out
    extended = h.page.replace("إلى 5 نوفمبر 2026مشارك:", "إلى 12 نوفمبر 2026مشارك:", 1)
    before = len(h.tg.sent)
    rep = h.run(at(11, 4, 12), page=extended)
    assert rep.updates == ["ماجستير في الحوسبة في الذكاء الاصطناعي"]
    update = h.sent(CHANNEL, since=before)[0]
    assert update["reply_to"] and "السابق: 25 أكتوبر – 5 نوفمبر 2026" in update["text"]
    assert "الجديد: 25 أكتوبر – 12 نوفمبر 2026" in update["text"]
    before = len(h.tg.sent)
    h.run(at(11, 11, 9), page=extended)
    closing = h.sent(CHANNEL, since=before)
    assert len(closing) == 1 and "غدًا آخر يوم للتقديم" in closing[0]["text"]


def test_small_edit_on_the_page_does_not_repost(h):
    h.run(at(10, 24, 12))
    old_ids = set(h.state()["programs"])
    edited = h.page.replace("الجامعة الوطنية في سنغافورة ( NUS)", "جامعة سنغافورة الوطنية (NUS)", 1)
    before = len(h.tg.sent)
    rep = h.run(at(10, 24, 15), page=edited)
    assert rep.posted == [] and len(h.tg.sent) == before
    new_ids = set(h.state()["programs"])
    assert len(new_ids - old_ids) == 1 and len(old_ids - new_ids) == 1  # same record, new id
    moved = h.state()["programs"][(new_ids - old_ids).pop()]
    assert moved["institution"] == "جامعة سنغافورة الوطنية (NUS)" and moved["events"] == ["new"]


def test_unreachable_page_alerts_once_and_fails_the_third_time(tmp_path, lines_text):
    h = Harness(tmp_path, lines_text)

    def broken(_):
        raise RuntimeError("HTTP 503")

    codes = []
    for hour in (9, 12, 15):
        rep = Radar(h.cfg, h.tg, now=lambda hour=hour: at(10, 24, hour), load=broken).run()
        codes.append(rep.exit_code)
    assert codes == [0, 0, 1]
    alerts = h.sent(ME)
    assert len(alerts) == 1 and "تعذّر جلب صفحة مسار واعد (2 مرات متتالية)" in alerts[0]["text"]
    rep = h.run(at(10, 24, 18))
    assert rep.exit_code == 0 and "consecutive_failures" not in h.state()["health"]


def test_page_without_programs_alerts(h):
    rep = h.run(at(10, 24, 12), page="صفحة تحت الصيانة")
    assert rep.exit_code == 1 and rep.alerts == ["empty"]
    assert len(h.sent(ME)) == 1 and not h.sent(CHANNEL)


def test_sudden_drop_in_program_count_alerts(h):
    h.run(at(10, 24, 12))
    rep = h.run(at(10, 24, 15), page="\n".join(h.page.split("\n")[:6]))
    assert "drop" in rep.alerts


def test_failed_post_is_retried_next_run(h):
    class Flaky(DryRunTelegram):
        failures = 1

        def send(self, chat_id, text, **kw):
            if "جامعة تورنتو" in text and self.failures:
                self.failures -= 1
                raise TelegramError("sendMessage", 500, "boom")
            return super().send(chat_id, text, **kw)

    h.tg = Flaky(out=lambda _: None)
    h.run(at(10, 24, 12))
    page = with_block(h.page, NEW_BLOCK)
    rep = h.run(at(10, 24, 15), page=page)
    assert rep.exit_code == 1 and not rep.posted
    rep = h.run(at(10, 24, 18), page=page)
    assert rep.posted == ["ماجستير في هندسة البيانات"]


def test_private_chat_only_setup(tmp_path, lines_text):
    h = Harness(tmp_path, lines_text, channel=None)
    h.run(at(10, 24, 12))
    assert len(h.sent(ME)) == 12  # 11 computing programs + start-up report
    before = len(h.tg.sent)
    h.run(at(10, 24, 15), page=with_block(lines_text, CULINARY_BLOCK))
    assert len(h.tg.sent) == before
    culinary = [r for r in h.state()["programs"].values() if r["title"] == "دبلوم فنون الطهي"]
    assert culinary[0]["events"] == ["filtered"]


def test_seeding_without_posting(tmp_path, lines_text):
    h = Harness(tmp_path, lines_text, seed_post_active=False)
    h.run(at(10, 24, 12))
    assert not h.sent(CHANNEL) and len(h.sent(ME)) == 1
    before = len(h.tg.sent)
    h.run(at(10, 25, 9))  # seeded programs still get the grouped opening reminder (without links)
    reminder = h.sent(CHANNEL, since=before)
    assert len(reminder) == 1 and "https://t.me" not in reminder[0]["text"]


def test_dry_run_never_writes_state(tmp_path, lines_text):
    h = Harness(tmp_path, lines_text, dry_run=True)
    rep = h.run(at(10, 24, 12))
    assert len(rep.posted) == 11 and not h.cfg.state_path.exists()


def test_digest_lists_open_programs_with_links(h):
    h.run(at(10, 24, 12))
    before = len(h.tg.sent)
    h.digest(at(10, 26, 9, 7))
    digest = h.sent(CHANNEL, since=before)
    assert len(digest) == 1
    assert "مفتوح الآن (11)" in digest[0]["text"] and digest[0]["text"].count("https://t.me/waaid_radar/") == 11


def test_monthly_heartbeat_touches_state(h):
    h.run(at(10, 24, 12))
    assert h.state()["meta"]["heartbeat"] == "2026-10-24"
    rep = h.run(at(11, 26, 12))
    assert rep.saved and h.state()["meta"]["heartbeat"] == "2026-11-26"
