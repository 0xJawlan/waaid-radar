"""Hashtags for a program: field, degree, eligibility, country and company."""

from __future__ import annotations

import re

from .models import Program
from .textutil import fold


def _p(*phrases: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(fold(p) for p in phrases))


# Matched against the program title and name only (not the conditions).
COMPUTING: dict[str, tuple[str, ...]] = {
    "ذكاء_اصطناعي": _p("الذكاء الاصطناعي", "ذكاء اصطناعي", "تعلم الآلة",
                       "artificial intelligence", "machine learning", "ai"),
    "علم_البيانات": _p("علم البيانات", "علوم البيانات", "تحليل البيانات", "هندسة البيانات", "البيانات الضخمة",
                       "data science", "data analytics", "data engineering", "big data"),
    "أمن_سيبراني": _p("سيبراني", "سبراني", "cyber"),
    "هندسة_البرمجيات": _p("البرمجيات", "برمجة", "software", "programming"),
    "علوم_الحاسب": _p("علوم الحاسب", "علم الحاسب", "علوم الحاسوب", "الحوسبة", "هندسة الحاسب",
                      "computer science", "computing", "computer engineering"),
    "شبكات": _p("شبكات", "networks", "networking"),
    "نظم_المعلومات": _p("نظم المعلومات", "نظم معلومات", "تقنية المعلومات",
                        "information systems", "information technology"),
}

OTHER: dict[str, tuple[str, ...]] = {
    "هندسة": _p("هندسة", "engineering"),
    "روبوتات": _p("روبوت", "ميكاترون", "robot", "mechatron"),
    "طيران": _p("طيران", "طيار", "طائرات", "aviation", "aeronaut", "pilot",
                "الملاحة الجوية", "المراقبة الجوية"),
    "أعمال_وإدارة": _p("إدارة", "أعمال", "business", "management", "تسويق", "marketing", "مبيعات",
                       "sales", "تجارة", "سلاسل الإمداد", "supply chain", "لوجست", "logistic",
                       "استثمار", "تمويل", "finance"),
    "ضيافة_وسياحة": _p("ضيافة", "فنادق", "فندق", "سياح", "hospitality", "hotel"),
    "طهي": _p("طهي", "الطاهي", "culinary"),
    "إعلام_وتصميم": _p("إعلام", "أفلام", "سينما", "سينمائي", "إنتاج", "مؤثرات", "رسوم متحركة", "تصميم",
                       "فنون", "صحافة", "film", "media", "design", "animation"),
    "رياضة": _p("رياضي", "رياضة", "sport"),
    "صحة": _p("مختبرات", "الطبية", "طبية", "صحة", "صحي", "صيدل", "تمريض", "medical", "health", "laborator"),
    "قانون": _p("قانون", "law", "legal", "الملكية الفكرية"),
    "بيئة_واستدامة": _p("بيئ", "استدامة", "sustainab", "environment"),
    "تعدين_وجيولوجيا": _p("تعدين", "معادن", "جيولوج", "جيوفيزي", "mining", "geolog"),
    "بحري": _p("بحري", "بحرية", "سفن", "marine", "maritime", "ship"),
    "فلك": _p("فلك", "astronom"),
}

# Phrases removed before testing a tag, to avoid false hits
# («هندسة البرمجيات» is computing, «الرياضيات» is maths, not sport).
_EXCLUDE: dict[str, tuple[str, ...]] = {
    "هندسة": _p("هندسة البرمجيات", "هندسة الحاسب", "هندسة علوم الحاسب", "هندسة البيانات",
                "software engineering", "computer engineering", "data engineering"),
    "رياضة": _p("الرياضيات", "رياضيات"),
}

DEGREES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("دكتوراه", _p("دكتوراه", "دكتوراة", "phd", "doctorate")),
    ("ماجستير", _p("ماجستير", "master", "msc", "mba", "mtech")),
    ("بكالوريوس", _p("بكالوريوس", "bachelor", "bsc")),
    ("دبلوم", _p("دبلوم", "diploma")),
    ("تدريب", _p("تدريب", "تأهيل", "اعتماد", "training", "certificate")),
)

# Graduates of these majors are eligible (checked in the conditions).
ELIGIBLE_CS = _p("علوم الحاسب", "علم الحاسب", "علوم الحاسوب", "الحاسب الآلي", "تقنية المعلومات",
                 "هندسة البرمجيات", "الحوسبة", "هندسة الحاسب", "نظم المعلومات", "الأمن السيبراني",
                 "الأمن السبراني", "علوم البيانات", "الذكاء الاصطناعي",
                 "computer science", "information technology", "software engineering")

_COUNTRIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (_p("المتحدة الأمريكية", "أمريكا"), "أمريكا"),
    (_p("المملكة المتحدة", "بريطانيا", "إنجلترا", "اسكتلندا"), "بريطانيا"),
    (_p("أستراليا"), "أستراليا"),
    (_p("سنغافورة"), "سنغافورة"),
    (_p("كندا"), "كندا"),
    (_p("ألمانيا"), "ألمانيا"),
    (_p("فرنسا"), "فرنسا"),
    (_p("إسبانيا"), "إسبانيا"),
    (_p("سويسرا"), "سويسرا"),
    (_p("إيطاليا"), "إيطاليا"),
    (_p("نيوزيلاندا", "نيوزيلندا"), "نيوزيلندا"),
    (_p("جنوب أفريقيا", "جنوب افريقيا"), "جنوب_أفريقيا"),
    (_p("هولندا"), "هولندا"),
    (_p("اليابان"), "اليابان"),
    (_p("كوريا"), "كوريا"),
    (_p("الصين"), "الصين"),
)


def _find(text: str, phrase: str) -> int | None:
    """Position of a folded phrase in folded text (whole words for short Latin tokens)."""
    if phrase.isascii():
        pattern = rf"\b{re.escape(phrase)}\b" if len(phrase) <= 3 else rf"\b{re.escape(phrase)}"
        m = re.search(pattern, text)
        return m.start() if m else None
    pos = text.find(phrase)
    return pos if pos >= 0 else None


def _has(text: str, phrases: tuple[str, ...]) -> bool:
    return any(_find(text, ph) is not None for ph in phrases)


def hashtag(text: str | None) -> str | None:
    if not text:
        return None
    tag = re.sub(r"[^\w]+", "_", text.strip())
    tag = re.sub(r"_+", "_", tag).strip("_")
    return tag if tag and not tag.isdigit() else None


def country_tag(country: str | None) -> str | None:
    if not country:
        return None
    folded = fold(country)
    for keys, name in _COUNTRIES:
        if any(key in folded for key in keys):
            return name
    return hashtag(country)


def company_tag(company: str | None) -> str | None:
    """«شركة الاتصالات السعودية (STC)» → STC; «الشركة الوطنية للإسكان» → الوطنية_للإسكان."""
    if not company:
        return None
    shorts = re.findall(r"\(([^()]{1,30})\)", company) + re.findall(r"\s[-–]\s*([^-–]{1,30})$", company)
    for short in shorts:
        if len(short.split()) <= 2:
            return hashtag(short)
    name = re.sub(r"\([^()]*\)", " ", company)
    name = re.sub(r"^\s*(?:الشركة|شركات|شركة|مجموعة)\s+", "", name)
    return hashtag(" ".join(name.split()[:5]))


def detect_degree(p: Program) -> str | None:
    """The degree word that appears first in the title (or, failing that, the program name)."""
    for source in (p.title, p.program):
        if not source:
            continue
        text = fold(source)
        best: tuple[int, str] | None = None
        for name, phrases in DEGREES:
            for phrase in phrases:
                pos = _find(text, phrase)
                if pos is not None and (best is None or pos < best[0]):
                    best = (pos, name)
        if best:
            return best[1]
    return None


def classify(p: Program) -> None:
    """Fill p.degree and p.tags."""
    name = fold(" ".join(x for x in (p.title, p.program) if x))
    computing = [tag for tag, phrases in COMPUTING.items() if _has(name, phrases)]
    other = []
    for tag, phrases in OTHER.items():
        text = name
        for excluded in _EXCLUDE.get(tag, ()):
            text = text.replace(excluded, " ")
        if _has(text, phrases):
            other.append(tag)

    p.degree = detect_degree(p)
    tags = (["حاسب"] if computing else []) + computing + other
    if p.degree:
        tags.append(p.degree)
    # «لخريجي الحاسب»: programs that admit computing graduates. Bachelor
    # programs admit high-school leavers, so the tag would be misleading there.
    if p.degree != "بكالوريوس" and p.conditions and _has(fold(" ".join(p.conditions)), ELIGIBLE_CS):
        tags.append("لخريجي_الحاسب")
    for extra in (country_tag(p.country), company_tag(p.company)):
        if extra:
            tags.append(extra)
    p.tags = list(dict.fromkeys(tags))
