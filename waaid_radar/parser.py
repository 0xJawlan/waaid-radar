"""Extract programs from the Waaid page.

The page is one long SharePoint rich-text area. Each opportunity is a title,
the sentence «بدء التقديم على برنامج الابتعاث … في <الشركة> ضمن مسار واعد»,
a run of «label: value» fields, the conditions, and «شارك:» share widgets.
The markup carries no dependable structure, so parsing works on the visible
text and copes with both line-separated and completely flattened text.
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup
from bs4.element import CData, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction, Tag

from .classify import classify
from .dates import parse_period
from .models import Program
from .textutil import ARABIC_LETTERS, clean, fold, squash, tidy

try:  # lxml is faster and more forgiving; html.parser is the stdlib fallback
    import lxml  # noqa: F401

    _HTML_PARSER = "lxml"
except ImportError:  # pragma: no cover
    _HTML_PARSER = "html.parser"

_AL = ARABIC_LETTERS
_GAP = r"[\s​-‏⁠﻿]*"

ANCHOR = re.compile(r"بدء\s*التقديم\s*على\s*برنامج")
_ANCHOR_RAW = re.compile(rf"بدء{_GAP}التقديم{_GAP}على{_GAP}برنامج")
# «شارك:» — also when glued to «2026م» or «التقديم» after invisible spaces are removed.
SHARE = re.compile(rf"(?:(?<![{_AL}])|(?<=\dم)|(?<=التقديم))شارك\s*:")
ENDED = re.compile(r"انتهت\s*فترة\s*التقديم")
COND_LABEL = re.compile(r"الشروط\s*الخاصة\s*بال?برنامج\s*:?")
_COMPANY = re.compile(r"بالتوظيف\s*(?:في|لدى)\s*(?P<company>.+?)\s*ضمن\s*مسار\s*واعد")
_BREADCRUMB_END = re.compile(r"مسار\s*واعد")

# (field, label) — most specific first; a label always ends with a colon.
_LABELS: tuple[tuple[str, str], ...] = (
    ("program", r"[اأ]سم\s*البرنامج"),
    ("duration", r"مدة\s*البرنامج"),
    ("duration", r"مدة\s*الدراسة"),
    ("duration", r"مدة\s*التدريب"),
    ("duration", r"فترة\s*الدراسة"),
    ("duration", r"فترة\s*التدريب"),
    ("start", r"بداية\s*الدراسة"),
    ("start", r"بداية\s*البرنامج"),
    ("start", r"بداية\s*التدريب"),
    ("period", r"فترة\s*التقديم"),
    ("institution", r"المركز\s*التدريبي"),
    ("institution", r"ا?لمؤسسة\s*التعليمية"),
    ("institution", r"مكان\s*التدريب"),
    ("institution", r"مكان\s*الدراسة"),
    ("institution", r"الجهة\s*التدريبية"),
    ("institution", r"الجامعة"),
    ("institution", r"المعهد"),
    ("country", r"الدولة"),
    ("program", r"(?<!ب)البرنامج"),
)
_LABEL_RE = re.compile("|".join(rf"(?P<f{i}>{pattern})\s*:" for i, (_, pattern) in enumerate(_LABELS)))

_BULLETS = re.compile(r"[●•▪◦·]|(?:(?<=\s)|^)o(?=\s)", re.M)
_SENTENCE_END = re.compile(rf"(?<=[.؛])\s*(?=[{_AL}])")

_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "fieldset", "figcaption",
    "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav",
    "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
})
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "iframe", "head", "select",
                        "option", "button", "input", "textarea", "object"})
_CHROME_TAGS = frozenset({"nav", "header", "footer", "aside"})
_NON_TEXT = (Comment, Declaration, Doctype, ProcessingInstruction, CData)
_BREAK = object()


# --------------------------------------------------------------------------- HTML

def html_to_text(root: Tag, *, skip_chrome: bool = False) -> str:
    """Visible text with line breaks around block elements, the way a browser shows it."""
    out: list[str] = []
    stack: list[object] = [root]
    while stack:
        node = stack.pop()
        if node is _BREAK:
            out.append("\n")
        elif isinstance(node, NavigableString):
            if not isinstance(node, _NON_TEXT):
                out.append(re.sub(r"\s+", " ", str(node)))
        elif isinstance(node, Tag):
            if node.name in _SKIP_TAGS or (skip_chrome and node.name in _CHROME_TAGS):
                continue
            if node.name in _BLOCK_TAGS:
                out.append("\n")
                stack.append(_BREAK)
            stack.extend(reversed(node.contents))
    return "".join(out)


def _content_box(soup: BeautifulSoup) -> Tag | None:
    """The smallest element that contains every opportunity (excludes menus and footer)."""
    hits = [s for s in soup.find_all(string=_ANCHOR_RAW)
            if not any(parent.name in _SKIP_TAGS for parent in s.parents)]
    if not hits:
        return None
    chains = [list(hit.parents) for hit in hits]
    if len(chains) == 1:
        return chains[0][min(3, len(chains[0]) - 1)]
    shared = set(map(id, chains[0])).intersection(*(set(map(id, c)) for c in chains[1:]))
    return next((p for p in chains[0] if id(p) in shared), None)


def parse_html(html: str | bytes, today: date | None = None) -> list[Program]:
    soup = BeautifulSoup(html, _HTML_PARSER)
    full = html_to_text(soup.body or soup, skip_chrome=True)
    text = full
    box = _content_box(soup)
    if box is not None:
        scoped = html_to_text(box)
        if len(ANCHOR.findall(clean(scoped))) >= len(ANCHOR.findall(clean(full))):
            text = scoped
    return parse_text(text, today)


# --------------------------------------------------------------------------- text

def parse_text(text: str, today: date | None = None) -> list[Program]:
    text = clean(text)
    anchors = list(ANCHOR.finditer(text))
    spans = [
        _title_span(text, anchors[i - 1].end() if i else 0, anchor.start(), first=(i == 0))
        for i, anchor in enumerate(anchors)
    ]
    programs = []
    for i, anchor in enumerate(anchors):
        end = spans[i + 1][0] if i + 1 < len(anchors) else len(text)
        title = tidy(text[spans[i][0]:spans[i][1]])
        programs.append(_parse_block(title, text[anchor.start():end], today))
    _assign_ids(programs)
    return programs


def _title_span(text: str, lo: int, hi: int, *, first: bool) -> tuple[int, int]:
    """A title sits after the previous block's last «شارك:», on the line before its anchor."""
    shares = list(SHARE.finditer(text, lo, hi))
    start = shares[-1].end() if shares else lo
    end = hi
    while end > start and text[end - 1].isspace():
        end -= 1
    newline = text.rfind("\n", start, end)
    if newline >= 0:
        start = newline + 1
    if first and end - start > 120:  # flattened page header: cut after the breadcrumb
        crumbs = list(_BREADCRUMB_END.finditer(text, start, end))
        start = crumbs[-1].end() if crumbs else max(start, end - 120)
    while start < end and text[start].isspace():
        start += 1
    return start, end


def _parse_block(title: str, block: str, today: date | None) -> Program:
    prog = Program(title=title, ended_flag=bool(ENDED.search(block)))
    cond = COND_LABEL.search(block)
    head = block[:cond.start()] if cond else block
    share = SHARE.search(head)
    if share:
        head = head[:share.start()]

    company = _COMPANY.search(squash(head[:800]))
    if company:
        prog.company = tidy(company.group("company")) or None

    fields: dict[str, str] = {}
    labels = list(_LABEL_RE.finditer(head))
    for j, match in enumerate(labels):
        name = _LABELS[int(match.lastgroup[1:])][0]
        stop = labels[j + 1].start() if j + 1 < len(labels) else len(head)
        value = tidy(ENDED.sub(" ", head[match.end():stop]))
        if value and name not in fields:
            fields[name] = value
    prog.program = fields.get("program")
    prog.duration = fields.get("duration")
    prog.institution = fields.get("institution")
    prog.country = fields.get("country")
    prog.start = fields.get("start")
    prog.period_raw = fields.get("period")
    prog.period_start, prog.period_end = parse_period(prog.period_raw, today)

    if cond:
        tail = block[cond.end():]
        shares = list(SHARE.finditer(tail))
        if shares:  # whatever follows the last share widget is not part of the block
            tail = tail[:shares[-1].start()]
        prog.conditions = split_conditions(tail)
    classify(prog)
    return prog


def split_conditions(text: str) -> list[str]:
    """Bullets, line breaks or run-on sentences («…الجنسية.أن يكون…») → a clean list."""
    text = SHARE.sub("\n", text)
    text = COND_LABEL.sub("\n", text)
    text = _BULLETS.sub("\n", text)
    items: list[str] = []
    seen: set[str] = set()
    for line in text.split("\n"):
        for piece in _SENTENCE_END.split(line):
            piece = tidy(piece)
            key = fold(piece)
            if len(piece) < 3 or key in seen:
                continue
            seen.add(key)
            items.append(piece)
    return items


def _assign_ids(programs: list[Program]) -> None:
    counts: dict[str, int] = {}
    for prog in programs:
        pid = prog.compute_pid()
        counts[pid] = counts.get(pid, 0) + 1
        prog.pid = pid if counts[pid] == 1 else f"{pid}-{counts[pid]}"
