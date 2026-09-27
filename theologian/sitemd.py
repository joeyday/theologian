"""Parse and render Tota Scripture topic pages (Obsidian Markdown).

A page is frontmatter plus a list of lines. Each body line is one of:
  Heading  -- '### Of Jesus'
  RefLine  -- 'Mt 3:17; 4:3, 6; 7:21 ~(note)~; Mk 1:1'  (a line made only of refs)
  Raw      -- anything else, kept verbatim (prose, includes, blank lines, See also...)

RefLines are parsed into Items (a Ref plus its annotations) and rendered back
canonically, so render(parse(text)) == text exactly when the source already
follows the house style. Differences are the round-trip test's findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .refs import CONT_REF_RE, NAMED_REF_RE, Ref, _ref_from_match

HEADING_RE = re.compile(r"^(#{1,6}) (.*)$")
STARTS_WITH_BOOK_RE = re.compile(rf"^(?:{NAMED_REF_RE.pattern})")
SUBTITLE_RE = re.compile(r"^(.*?)\s*~\((.*)\)~\s*$")


@dataclass
class Annotation:
    """Something attached after a ref.

    kind: "note"     ~(this one’s subtle)~  or  ~— *cf. Ps 50:4*~
          "include"  {{s|see also Da 3:25}}
          "comment"  %% probably more? %%
          "footnote" [^1]           (attached, no space before)
          "ff"       \u2060ff       (attached, no space before)
          "tail"     — *see also …*  (free text running to the end of the line)
    """

    kind: str
    raw: str  # full source text

    ATTACHED = ("footnote", "ff")

    def spacing(self, source_gap: str | None = None) -> str:
        """Whitespace before this annotation. Footnote markers and "ff" attach
        to the ref; notes follow a space. Comments attach too, so removing one
        (by hand, or by the site build) leaves no stray space before the next
        separator -- but a comment's spacing as written in the source is kept."""
        if self.kind in self.ATTACHED:
            return ""
        if self.kind == "comment":
            return source_gap if source_gap in ("", " ") else ""
        return " "

    @property
    def breaks_chain(self) -> bool:
        """Whether a following ref must repeat its book name. Comments are
        stripped by the site build before refs are linked, so they don't."""
        return self.kind != "comment"

    @property
    def text(self) -> str:
        """Note text without the ~( )~ wrapper."""
        if self.kind != "note":
            return self.raw
        inner = self.raw[1:-1]
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1]
        return inner

    @classmethod
    def note(cls, text: str) -> Annotation:
        return cls("note", f"~({text})~")


@dataclass
class Item:
    ref: Ref
    annotations: list[Annotation] = field(default_factory=list)
    translation: str | None = None  # e.g. "KJV" in "Rev 1:5 KJV"
    # Source details, kept for linting (None for items built in code):
    written_book: str | None = None  # book spelling, when a book name was written
    source_ref: str | None = None  # the ref as written, e.g. "Ge 1:1-3"
    sep_before: str | None = None  # separator as written, e.g. "; "
    gaps: list[str] = field(default_factory=list)  # whitespace before each annotation

    @property
    def notes(self) -> list[str]:
        return [a.text for a in self.annotations if a.kind == "note"]


@dataclass
class Heading:
    level: int
    text: str

    @property
    def title(self) -> str:
        m = SUBTITLE_RE.match(self.text)
        return m[1] if m else self.text

    @property
    def subtitle(self) -> str | None:
        m = SUBTITLE_RE.match(self.text)
        return m[2] if m else None

    def render(self) -> str:
        return f"{'#' * self.level} {self.text}"


@dataclass
class RefLine:
    items: list[Item]
    source: str | None = None  # original text, when parsed and not since modified

    def render(self) -> str:
        """The source as written if unmodified; canonical house style otherwise."""
        return self.source if self.source is not None else render_items(self.items)


@dataclass
class Raw:
    text: str

    def render(self) -> str:
        return self.text


Line = Heading | RefLine | Raw


@dataclass
class Section:
    heading: Heading | None
    items: list[Item]


@dataclass
class Page:
    frontmatter_raw: str | None  # text between the --- fences, verbatim
    lines: list[Line]
    trailing_newline: bool = True
    path: Path | None = None

    @property
    def frontmatter(self) -> dict:
        return (yaml.safe_load(self.frontmatter_raw) or {}) if self.frontmatter_raw else {}

    @property
    def title(self) -> str | None:
        return self.path.stem if self.path else None

    def sections(self) -> list[Section]:
        """Items grouped under the nearest preceding heading."""
        out = [Section(None, [])]
        for line in self.lines:
            if isinstance(line, Heading):
                out.append(Section(line, []))
            elif isinstance(line, RefLine):
                out[-1].items.extend(line.items)
        return [s for s in out if s.items or s.heading]

    def render(self) -> str:
        parts = []
        if self.frontmatter_raw is not None:
            parts.append(f"---\n{self.frontmatter_raw}---")
        parts.extend(line.render() for line in self.lines)
        return "\n".join(parts) + ("\n" if self.trailing_newline else "")


# ── RefLine parsing ──────────────────────────────────────────────────────────


class RefLineError(ValueError):
    pass


TRANSLATION_RE = re.compile(r" (ESV|KJV|NASB|NIV|NKJV|NLT|NRSV)\b")
FOOTNOTE_RE = re.compile(r"\[\^[^\]]+\]")
FF_RE = re.compile(r"\u2060?ff\b")
TAIL_RE = re.compile(r"\*?\s*—.*$")


def _note_end(s: str, pos: int) -> int:
    """Index just past the note starting at s[pos] == '~'. Notes nest:
    '~— *cf. Hab 1:12 ~(see NIV)~; Ro 1:23*~' is one note."""
    paren = s.startswith("~(", pos)
    depth, i = (1, pos + 2) if paren else (0, pos + 1)
    while i < len(s):
        if s.startswith("~(", i):
            depth, i = depth + 1, i + 2
        elif s.startswith(")~", i) and depth > 0:
            depth, i = depth - 1, i + 2
            if paren and depth == 0:
                return i
        elif s[i] == "~" and depth == 0 and not paren:
            return i + 1
        else:
            i += 1
    raise RefLineError(f"unclosed ~ at {pos}")


def _scan_annotation(s: str, pos: int) -> tuple[Annotation, str, int] | None:
    """Annotation starting at pos (after optional spaces): (annotation, the
    whitespace gap before it, end index)."""
    if m := FOOTNOTE_RE.match(s, pos):
        return Annotation("footnote", m[0]), "", m.end()
    if m := FF_RE.match(s, pos):
        return Annotation("ff", m[0]), "", m.end()
    j = pos
    while j < len(s) and s[j] == " ":
        j += 1
    gap = s[pos:j]
    if s.startswith("~", j):
        end = _note_end(s, j)
        return Annotation("note", s[j:end]), gap, end
    if s.startswith("{{", j):
        end = s.find("}}", j + 2)
        if end == -1:
            raise RefLineError(f"unclosed {{{{ at {j}")
        return Annotation("include", s[j : end + 2]), gap, end + 2
    if s.startswith("%%", j):
        end = s.find("%%", j + 2)
        if end == -1:
            raise RefLineError(f"unclosed %% at {j}")
        return Annotation("comment", s[j : end + 2]), gap, end + 2
    if m := TAIL_RE.match(s, j):
        return Annotation("tail", m[0].rstrip()), gap, len(s.rstrip())
    return None


def parse_refline(s: str) -> list[Item]:
    """Parse a line consisting only of refs, separators and annotations."""
    items: list[Item] = []
    book = chapter = None
    chain = False  # may the next ref omit its book name?
    pos, sep = 0, None
    while True:
        m = NAMED_REF_RE.match(s, pos)
        if m:
            ref = _ref_from_match(m["book"], m["ch"], m["v"], m["r1"], m["r2"], m["ech"])
        elif chain and (m := CONT_REF_RE.match(s, pos)):
            if m["v"] is not None:
                ref = _ref_from_match(book, m["n"], m["v"], m["r1"], m["r2"], None)
            else:
                end = int(m["bre"]) if m["bre"] else None
                ref = Ref(book, chapter, int(m["n"]), end_verse=end)
        else:
            raise RefLineError(f"expected a reference at {pos}: {s[pos:pos + 20]!r}")
        book, chapter, chain = ref.book, ref.chapter, True
        item = Item(ref, written_book=m.groupdict().get("book"), source_ref=m[0], sep_before=sep)
        items.append(item)
        pos = m.end()
        if t := TRANSLATION_RE.match(s, pos):
            item.translation, pos = t[1], t.end()
        while found := _scan_annotation(s, pos):
            ann, gap, pos = found
            item.annotations.append(ann)
            item.gaps.append(gap)
            if ann.breaks_chain:
                chain = False
        # separator or end
        rest = s[pos:]
        if not rest.strip(" ;,"):
            return items  # end of line (tolerates a trailing '; ')
        sm = re.match(r"\s*[;,]\s*", rest)
        if not sm:
            raise RefLineError(f"expected ';' or ',' at {pos}: {rest[:20]!r}")
        sep = sm[0]
        pos += sm.end()


def link_form(prev: Item | None, item: Item) -> str:
    """How house style writes `item` after `prev`:
    "full" (book and all), "numeric" ('; 4:3'), or "verses" (', 6').

    The book is omitted only when it continues the previous ref's book with
    no translation or annotation in between (build.js breaks the chain on any
    intervening text). %% comments don't count: build.js strips them before
    linking. Whole-chapter refs always carry their book name, since a bare
    number would read as a verse."""
    if prev is None:
        return "full"
    p, r = prev.ref, item.ref
    breaks = any(a.breaks_chain for a in prev.annotations)
    if p.book != r.book or breaks or prev.translation or r.is_chapter_only:
        return "full"
    if not p.is_chapter_only and not r.end_chapter and p.chapter == r.chapter:
        return "verses"
    return "numeric"


def render_items(items: list[Item]) -> str:
    out = ""
    prev: Item | None = None
    for item in items:
        r = item.ref
        form = link_form(prev, item)
        if prev is None:
            out += str(r)
        elif form == "verses":
            out += ", " + r.verses_part()
        elif form == "numeric":
            out += "; " + r.numeric()
        else:
            out += "; " + str(r)
        if item.translation:
            out += " " + item.translation
        for k, a in enumerate(item.annotations):
            out += a.spacing(item.gaps[k] if k < len(item.gaps) else None) + a.raw
        prev = item
    return out


# ── Page parsing ─────────────────────────────────────────────────────────────


def parse_line(line: str) -> Line:
    if m := HEADING_RE.match(line):
        return Heading(len(m[1]), m[2])
    if STARTS_WITH_BOOK_RE.match(line):
        try:
            return RefLine(parse_refline(line), source=line)
        except RefLineError:
            pass
    return Raw(line)


def parse_page(text: str, path: Path | None = None) -> Page:
    fm = None
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            fm = text[4 : end + 1]
            body = text[end + 4 :].removeprefix("\n")
    lines = body.removesuffix("\n").split("\n") if body else []
    return Page(fm, [parse_line(l) for l in lines], text.endswith("\n"), path)


def load_page(path: str | Path) -> Page:
    path = Path(path)
    return parse_page(path.read_text(encoding="utf-8"), path)
