"""Check topic pages against house style and the site's linking rules.

Every difference between a RefLine's source and its canonical rendering must
be explained by at least one finding; anything else is an "unexplained" error
(a parser/renderer bug), which is what the round-trip test guards against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .refs import SINGLE_CHAPTER
from .sitemd import (STARTS_WITH_BOOK_RE, Annotation, Item, Page, Raw, RefLine,
                     link_form, load_page, parse_refline, render_items)

# Findings where the published page is (probably) wrong, vs. cosmetic ones.
ERRORS = {"unparsed", "verse-order", "chapter-in-single-chapter-book", "duplicate", "unexplained"}


@dataclass
class Finding:
    path: Path
    line: int  # 1-based, counting from the top of the file
    kind: str
    message: str

    @property
    def severity(self) -> str:
        return "error" if self.kind in ERRORS else "style"

    def __str__(self) -> str:
        return f"{self.path.name}:{self.line}: {self.severity}: [{self.kind}] {self.message}"


def lint_items(items: list[Item]) -> list[tuple[str, str]]:
    """(kind, message) findings for one RefLine's items."""
    out: list[tuple[str, str]] = []
    prev: Item | None = None
    for item in items:
        r, src = item.ref, item.source_ref or str(item.ref)
        form = link_form(prev, item)
        if re.search(r"\d-\d", src):
            out.append(("dash", f"hyphen in range {src!r}; use an en dash"))
        if item.written_book and item.written_book != r.book:
            out.append(("book-spelling", f"{item.written_book!r} → {r.book!r} in {src!r}"))
        if item.written_book and form != "full":
            out.append(("redundant-book", f"book name can be omitted in {src!r}"))
        if not item.written_book and form == "verses" and ":" in src:
            out.append(("redundant-chapter", f"chapter can be omitted in {src!r}"))
        if prev is not None:
            want = ", " if form == "verses" else "; "
            if item.sep_before.strip() != want.strip():
                out.append(("separator", f"{item.sep_before.strip()!r} before {src!r}; expected {want.strip()!r}"))
            elif item.sep_before != want:
                out.append(("spacing", f"irregular spacing before {src!r}"))
            p = prev.ref
            if (p.book == r.book and p.chapter == r.chapter and not p.is_chapter_only
                    and not r.is_chapter_only and r.verse <= (p.end_verse or p.verse)
                    and not prev.annotations and not prev.translation):
                out.append(("verse-order", f"{r} follows {p} (verse goes backwards; missing book name?)"))
        if r.book in SINGLE_CHAPTER and (r.chapter > 1 and r.is_chapter_only):
            out.append(("chapter-in-single-chapter-book",
                        f"{src!r} links to chapter {r.chapter}; write {r.book} 1:{r.chapter}"))
        for ann, gap in zip(item.annotations, item.gaps):
            want = "" if ann.kind in Annotation.ATTACHED else " "
            if gap != want:
                out.append(("spacing", f"irregular spacing before {ann.raw[:20]!r}"))
        prev = item
    return out


def lint_page(page: Page) -> list[Finding]:
    path = page.path or Path("<page>")
    offset = 1 + (page.frontmatter_raw.count("\n") + 2 if page.frontmatter_raw is not None else 0)
    findings: list[Finding] = []
    seen: dict = {}
    section = None
    for i, line in enumerate(page.lines):
        n = i + offset
        if isinstance(line, RefLine):
            kinds = []
            for kind, msg in lint_items(line.items):
                findings.append(Finding(path, n, kind, msg))
                kinds.append(kind)
            for item in line.items:
                key = (section, item.ref)
                if key in seen:
                    findings.append(Finding(path, n, "duplicate", f"{item.ref} already listed on line {seen[key]}"))
                seen.setdefault(key, n)
            src = line.source or ""
            if src != src.rstrip() or src.rstrip().endswith((";", ",")):
                findings.append(Finding(path, n, "trailing", "trailing separator or whitespace"))
                kinds.append("trailing")
            rendered = render_items(line.items)
            if rendered != src and not kinds:
                findings.append(Finding(path, n, "unexplained", f"renders as {rendered!r}"))
            if _strip_source(parse_refline(rendered)) != _strip_source(line.items):
                findings.append(Finding(path, n, "unexplained", "re-parsing the rendering changes the meaning"))
        elif hasattr(line, "level"):
            section = line.text
        elif isinstance(line, Raw) and STARTS_WITH_BOOK_RE.match(line.text):
            findings.append(Finding(path, n, "unparsed", f"looks like a ref list but doesn't parse: {line.text[:70]!r}"))
    return findings


def _strip_source(items: list[Item]) -> list[Item]:
    """Items without source-only fields, for comparing meaning."""
    return [Item(i.ref, i.annotations, i.translation) for i in items]


def lint_paths(paths: list[Path]) -> list[Finding]:
    out = []
    for p in paths:
        out.extend(lint_page(load_page(p)))
    return out
