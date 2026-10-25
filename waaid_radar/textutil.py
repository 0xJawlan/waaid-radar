"""Arabic-aware text helpers shared by the parser, classifier and renderer."""

from __future__ import annotations

import re

# Invisible characters SharePoint sprinkles through the page (zero-width
# spaces, bidi marks, soft hyphens). They silently break pattern matching.
_INVISIBLE = re.compile("[­​-‏‪-‮⁠⁦-⁩﻿]")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_TASHKEEL = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_INLINE_SPACE = re.compile(r"[^\S\n]+")

ARABIC_LETTERS = "ء-ي"


def clean(text: str) -> str:
    """Drop invisible characters, use Latin digits, tidy spaces; keep line breaks."""
    text = _INVISIBLE.sub("", text).replace("\xa0", " ").translate(_DIGITS)
    lines = (_INLINE_SPACE.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def squash(text: str) -> str:
    """Collapse every run of whitespace, line breaks included, into one space."""
    return re.sub(r"\s+", " ", text).strip()


def fold(text: str) -> str:
    """Aggressive normalisation used for matching and identity, never for display."""
    text = _TASHKEEL.sub("", clean(text))
    text = re.sub("[أإآٱ]", "ا", text)
    text = text.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    text = re.sub(r"[^\w]+", " ", text.lower())
    return squash(text.replace("_", " "))


def tidy(text: str) -> str:
    """Make an extracted value presentable: one line, no stray punctuation."""
    text = squash(text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\s+([،,.:؛])", r"\1", text)
    return text.strip(" :-–—،,.؛")
