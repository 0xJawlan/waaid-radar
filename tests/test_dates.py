from datetime import date

import pytest

from waaid_radar.dates import days_phrase, fmt_range, parse_period


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("من 25 أكتوبر 2026م إلى 5 نوفمبر 2026م", date(2026, 10, 25), date(2026, 11, 5)),
        ("25 أكتوبر 2026م إلى 5 نوفمبر 2026م", date(2026, 10, 25), date(2026, 11, 5)),
        ("من 3 أغسطس إلى 17 أغسطس 2026", date(2026, 8, 3), date(2026, 8, 17)),
        ("من 25 ديسمبر 2025م إلى 1 يناير 2026م", date(2025, 12, 25), date(2026, 1, 1)),
        ("من 23/7/2025 م إلى 27/7/2025 م", date(2025, 7, 23), date(2025, 7, 27)),
        ("من٢٣ يونيو 2025م إلى ٣ يوليو 2025م", date(2025, 6, 23), date(2025, 7, 3)),
        ("من 2 أغسطس 2026م إل​ى 6 أغسطس 2026م", date(2026, 8, 2), date(2026, 8, 6)),
        ("من 30 أغسطس 2026م وحتى 3 سبتمبر 2026م", date(2026, 8, 30), date(2026, 9, 3)),
        ("من 2 أغسطس إلى13 أغسطس 2026م", date(2026, 8, 2), date(2026, 8, 13)),
        ("من 8مارس 2026 إلى 15 مارس 2026م", date(2026, 3, 8), date(2026, 3, 15)),
        ("من 09 ابريل 2026م إلى 30 ابريل 2026م", date(2026, 4, 9), date(2026, 4, 30)),
        ("09 سبتمبر 2025م الى 13 سبتمبر 2025م", date(2025, 9, 9), date(2025, 9, 13)),
    ],
)
def test_parse_period_variants(text, start, end):
    assert parse_period(text) == (start, end)


def test_parse_period_without_years_uses_reference():
    assert parse_period("من 28 ديسمبر إلى 5 يناير", ref=date(2026, 12, 1)) == (date(2026, 12, 28), date(2027, 1, 5))


def test_parse_period_single_date():
    assert parse_period("حتى 5 نوفمبر 2026") == (None, date(2026, 11, 5))
    assert parse_period("يبدأ 5 نوفمبر 2026") == (date(2026, 11, 5), None)


def test_parse_period_nothing_usable():
    assert parse_period(None) == (None, None)
    assert parse_period("يعلن لاحقًا") == (None, None)
    assert parse_period("من 31 فبراير 2026 إلى 3 مارس 2026") == (None, date(2026, 3, 3))


def test_fmt_range():
    assert fmt_range(date(2026, 10, 25), date(2026, 11, 5)) == "25 أكتوبر – 5 نوفمبر 2026"
    assert fmt_range(date(2026, 5, 10), date(2026, 5, 12)) == "10–12 مايو 2026"
    assert fmt_range(date(2025, 12, 25), date(2026, 1, 1)) == "25 ديسمبر 2025 – 1 يناير 2026"
    assert fmt_range(None, date(2026, 1, 1)) == "حتى 1 يناير 2026"
    assert fmt_range(None, None) == ""


@pytest.mark.parametrize(
    ("n", "text"), [(1, "يوم واحد"), (2, "يومين"), (3, "3 أيام"), (10, "10 أيام"), (11, "11 يومًا")]
)
def test_days_phrase(n, text):
    assert days_phrase(n) == text
