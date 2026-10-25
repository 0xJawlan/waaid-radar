from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from waaid_radar.classify import classify
from waaid_radar.config import Config, ConfigError
from waaid_radar.models import Program
from waaid_radar.render import LIMIT, count_phrase, post_link, program_post, status_text

URL = "https://sites.moe.gov.sa/scholarship-program/paths/path-waaid/"


def program(**kw):
    base = dict(title="ماجستير في الأمن السيبراني", company="شركة الاتصالات السعودية (STC)",
                program="Master in Cybersecurity", institution="جامعة موناش", country="أستراليا",
                duration="18 شهرًا", start="فبراير 2027", period_raw="من 25 أكتوبر 2026م إلى 5 نوفمبر 2026م",
                period_start=date(2026, 10, 25), period_end=date(2026, 11, 5),
                conditions=["أن يكون المتقدم سعودي الجنسية"])
    base.update(kw)
    p = Program(**base)
    classify(p)
    return p


def test_program_post_has_every_field_and_tags():
    text = program_post(program(), date(2026, 10, 24), URL)
    for piece in ("🆕", "<b>ماجستير في الأمن السيبراني</b>", "Master in Cybersecurity", "جامعة موناش",
                  "أستراليا", "18 شهرًا", "فبراير 2027", "25 أكتوبر – 5 نوفمبر 2026 · يبدأ غدًا",
                  "<blockquote expandable>• أن يكون المتقدم سعودي الجنسية</blockquote>",
                  "#حاسب #أمن_سيبراني #ماجستير #أستراليا #STC", f'<a href="{URL}">'):
        assert piece in text


def test_program_post_escapes_html_and_respects_the_length_limit():
    p = program(title="برنامج <تجريبي> & جديد", conditions=[f"شرط طويل رقم {i} " + "ن" * 300 for i in range(30)])
    text = program_post(p, date(2026, 10, 24), URL)
    assert "&lt;تجريبي&gt; &amp;" in text
    assert len(text) <= LIMIT and "بقية الشروط في صفحة المسار" in text


def test_status_text():
    p = program()
    assert status_text(p, date(2026, 10, 20)) == "يبدأ بعد 5 أيام"
    assert status_text(p, date(2026, 10, 25)) == "مفتوح — يُغلق بعد 11 يومًا"
    assert status_text(p, date(2026, 11, 4)) == "مفتوح — يُغلق غدًا"
    assert status_text(p, date(2026, 11, 5)) == "مفتوح — اليوم آخر يوم"
    assert status_text(p, date(2026, 11, 6)) == "انتهى التقديم"


def test_count_phrase_and_links():
    assert [count_phrase(n) for n in (1, 2, 3, 11)] == ["برنامج واحد", "برنامجين", "3 برامج", "11 برنامجًا"]
    assert post_link("@waaid_radar", 12) == "https://t.me/waaid_radar/12"
    assert post_link("-1001234567890", 12) == "https://t.me/c/1234567890/12"
    assert post_link("@x", None) is None


def test_config_from_env_defaults_and_overrides():
    cfg = Config.from_env(
        {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHANNEL_ID": "waaid_radar", "TELEGRAM_ADMIN_CHAT_ID": "111"}
    )
    assert cfg.channel == "@waaid_radar" and cfg.main_chat == "@waaid_radar"
    assert cfg.personal_tags == {"حاسب", "لخريجي_الحاسب"} and cfg.quiet_hours == (23, 7)
    assert Config.from_env({"TELEGRAM_CHANNEL_ID": "https://t.me/waaid_radar/"}).channel == "@waaid_radar"
    assert Config.from_env({"TELEGRAM_CHANNEL_ID": "-100123"}).channel == "-100123"
    assert Config.from_env({"PERSONAL_TAGS": "none"}).personal_tags is None
    assert Config.from_env({"PERSONAL_TAGS": "*"}).personal_tags == {"*"}
    custom = Config.from_env({"PERSONAL_TAGS": "#أمن_سيبراني، ذكاء_اصطناعي"})
    assert custom.personal_tags == {"أمن_سيبراني", "ذكاء_اصطناعي"}
    assert Config.from_env({"QUIET_HOURS": "off"}).quiet_hours is None
    with pytest.raises(ConfigError):
        Config.from_env({"QUIET_HOURS": "late"})
    with pytest.raises(ConfigError):
        Config.from_env({"RENDER_JS": "maybe"})


def test_quiet_hours_wrap_around_midnight():
    cfg = Config()
    tz = ZoneInfo("Asia/Riyadh")
    assert [cfg.is_quiet(datetime(2026, 1, 1, h, tzinfo=tz)) for h in (22, 23, 2, 6, 7, 12)] == [
        False, True, True, True, False, False]


def test_personal_filter():
    cfg = Config(admin_chat="1")
    assert cfg.wants(program())
    assert not cfg.wants(program(title="دبلوم فنون الطهي", program=None, conditions=[]))
    assert Config(admin_chat="1", personal_tags=frozenset({"*"})).wants(program(title="دبلوم فنون الطهي"))
    assert Config(channel="@c").posts_to_main(program(title="دبلوم فنون الطهي", program=None, conditions=[]))


def test_require_telegram():
    with pytest.raises(ConfigError):
        Config().require_telegram()
    Config(dry_run=True).require_telegram()
    Config(token="t", admin_chat="1").require_telegram()
