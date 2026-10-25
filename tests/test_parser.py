from datetime import date

from conftest import TODAY
from waaid_radar.models import Status
from waaid_radar.parser import parse_html, parse_text, split_conditions


def find(programs, title, institution=None):
    matches = [p for p in programs if p.title == title and (institution is None or p.institution == institution)]
    assert len(matches) == 1, f"{title!r} / {institution!r}: {len(matches)} matches"
    return matches[0]


def snapshot(programs):
    return [(p.pid, p.title, p.company, p.program, p.institution, p.country, p.duration, p.start,
             p.period_start, p.period_end, p.ended_flag, p.conditions, p.tags) for p in programs]


def test_reads_every_program(lines_text):
    programs = parse_text(lines_text, TODAY)
    assert len(programs) == 26
    assert programs[0].title == "ماجستير في الحوسبة في الذكاء الاصطناعي"
    assert programs[-1].title == "برنامج تدريبي في تأهيل طياري المستقبل"
    assert len({p.pid for p in programs}) == 26


def test_flattened_text_gives_identical_result(lines_text, flat_text):
    assert snapshot(parse_text(flat_text, TODAY)) == snapshot(parse_text(lines_text, TODAY))


def test_first_program_fields(lines_text):
    p = parse_text(lines_text, TODAY)[0]
    assert p.company == "شركة الاتصالات السعودية (STC)"
    assert p.program == "Master of Computing in Artificial Intelligence"
    assert p.institution == "الجامعة الوطنية في سنغافورة (NUS)"
    assert p.country == "سنغافورة"
    assert p.duration == "2 سنة"
    assert p.start == "أغسطس 2027"
    assert (p.period_start, p.period_end) == (date(2026, 10, 25), date(2026, 11, 5))
    assert p.status(TODAY) is Status.UPCOMING
    assert p.degree == "ماجستير"
    assert p.conditions[0] == "أن يكون المتقدم سعودي الجنسية"
    assert p.conditions[-1] == "درجة اختبار اللغة الانجليزية لا تقل عن: IELTS Academic (6) أو ما يعادلها"
    assert len(p.conditions) == 7


def test_only_stc_programs_are_still_open(lines_text):
    programs = parse_text(lines_text, TODAY)
    active = [p for p in programs if p.status(TODAY) is not Status.ENDED]
    assert len(active) == 11
    assert {p.company for p in active} == {"شركة الاتصالات السعودية (STC)"}


def test_labels_glued_to_previous_value(lines_text):
    p = find(parse_text(lines_text, TODAY), "ماجستير في الأمن السيبراني")
    assert (p.institution, p.country, p.duration) == ("جامعة موناش", "أستراليا", "18 شهرًا")


def test_same_title_different_university(lines_text):
    programs = parse_text(lines_text, TODAY)
    monash = find(programs, "ماجستير في علم البيانات", "جامعة موناش")
    melbourne = find(programs, "ماجستير في علم البيانات", "جامعة ملبورن")
    assert monash.pid != melbourne.pid
    assert melbourne.start == "مارس 2027"


def test_misspelled_and_variant_labels(lines_text):
    programs = parse_text(lines_text, TODAY)
    geo = find(programs, "برنامج تدريبي في تخصص الاستخبارات الجغرافية المكانية")  # «لمؤسسة التعليمية»
    assert (geo.duration, geo.institution) == ("9 أشهر", "جامعة جورج مايسون")
    noon = find(programs, "برنامج تدريبي في تخصص هندسة البرمجيات")  # «أسم البرنامج», Arabic-Indic digits
    assert noon.program == "برنامج تدريبي في تخصص هندسة البرمجيات"
    assert (noon.period_start, noon.period_end) == (date(2025, 6, 23), date(2025, 7, 3))
    tabuk = find(programs, "ماجستير في الهندسة الكهربائية والإلكترونية")  # «الجامعة:», 23/7/2025
    assert tabuk.institution == "جامعة غرينتش"
    assert (tabuk.period_start, tabuk.period_end) == (date(2025, 7, 23), date(2025, 7, 27))


def test_block_without_program_label(lines_text):
    p = find(parse_text(lines_text, TODAY), "بكالوريوس في الهندسة الكهربائية")
    assert p.company == "شركة التعدين العربية السعودية (معادن)"
    assert p.program is None
    assert (p.institution, p.duration) == ("Colorado School of Mines", "5 سنوات")
    assert "IELTS درجة إجمالية 6.5، على أن لا تقل أي مهارة عن 6" in p.conditions


def test_block_without_application_period(lines_text):
    p = find(parse_text(lines_text, TODAY), "ماجستير هندسة السيارات الكهربائية")
    assert p.period_raw is None and p.period_start is None
    assert p.ended_flag and p.status(TODAY) is Status.ENDED


def test_conditions_label_without_colon_and_until(lines_text):
    p = find(parse_text(lines_text, TODAY), "التدريب في ما بعد الإنتاج في الأفلام والتلفزيون")
    assert (p.period_start, p.period_end) == (date(2026, 8, 30), date(2026, 9, 3))
    assert p.conditions[0] == "أن يكون المتقدم سعودي الجنسية"
    assert p.degree == "تدريب"


def test_no_share_widget_or_footer_in_conditions(lines_text):
    programs = parse_text(lines_text, TODAY)
    for p in programs:
        for c in p.conditions:
            assert "شارك" not in c and "الحقوق" not in c
    assert programs[-1].conditions[-1].startswith("اجتياز اختبار اللغة الإنجليزية ELP")


def test_tags(lines_text):
    programs = parse_text(lines_text, TODAY)
    cyber = find(programs, "ماجستير في الأمن السيبراني")
    assert cyber.tags == ["حاسب", "أمن_سيبراني", "ماجستير", "لخريجي_الحاسب", "أستراليا", "STC"]
    robots = find(programs, "برنامج الروبوتات والميكاترونيات الكمية")
    assert "لخريجي_الحاسب" in robots.tags and "حاسب" not in robots.tags
    marine = find(programs, "بكالوريوس في تخصص هندسة الاتصالات")  # mentions a high-school «مسار علوم الحاسب»
    assert "لخريجي_الحاسب" not in marine.tags and "حاسب" not in marine.tags
    law = find(programs, "ماجستير العلوم في تخصص القانون الرياضي")
    assert {"رياضة", "قانون", "إسبانيا"} <= set(law.tags)
    se = find(programs, "ماجستير في التكنولوجيا في هندسة البرمجيات")
    assert "هندسة" not in se.tags and "هندسة_البرمجيات" in se.tags
    mbc = find(programs, "بكالوريوس العلوم في علوم الحاسب تخصص الأمن السيبراني والتحقيقات الجنائية الرقمية")
    assert "إم_بي_سي" in mbc.tags and "أمريكا" in mbc.tags


def test_html_page(page_html):
    programs = parse_html(page_html, TODAY)
    assert [p.title for p in programs] == [
        "ماجستير في الأمن السيبراني",
        "ماجستير في علم البيانات",
        "برنامج تدريبي في تخصص هندسة البرمجيات",
        "التدريب في ما بعد الإنتاج في الأفلام والتلفزيون",
        "بكالوريوس في علوم الحاسب",
    ]
    cyber, data, noon, jathr, bsc = programs
    assert cyber.country == "أستراليا" and len(cyber.conditions) == 4
    assert data.institution == "جامعة ملبورن"
    assert noon.ended_flag and noon.institution == "معهد فلات أيرون"
    assert jathr.program == "Post-Production Certificate Program"
    assert jathr.institution == "يو سي إل إكستنشن (UCLA Extension)"
    assert jathr.status(TODAY) is Status.ENDED
    assert bsc.conditions == ["شهادة ثانوية (المسار العلمي) بمعدل تراكمي لا يقل عن 90%",
                              "درجة اختبار القدرات العامة لا تقل عن 85%"]


def test_same_program_same_id_in_html_and_text(lines_text, page_html):
    text_ids = {(p.title, p.institution): p.pid for p in parse_text(lines_text, TODAY)}
    for p in parse_html(page_html, TODAY):
        if (p.title, p.institution) in text_ids:
            assert p.pid == text_ids[(p.title, p.institution)]


def test_split_conditions():
    assert split_conditions("أن يكون سعوديًا.أن يكون حسن السيرة.● IELTS 6.5\no TOEFL 80 شارك:") == [
        "أن يكون سعوديًا", "أن يكون حسن السيرة", "IELTS 6.5", "TOEFL 80",
    ]
    assert split_conditions("بمعدل 3.5 من 4.درجة اختبار") == ["بمعدل 3.5 من 4", "درجة اختبار"]


def test_empty_page():
    assert parse_text("لا يوجد شيء هنا") == []
    assert parse_html("<html><body><p>صيانة</p></body></html>") == []
