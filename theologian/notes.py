"""The page's inline notes, from a classification.

House style uses notes only for:
  ~(cites Ps 2:7)~            a New Testament verse quoting/alluding to the Old
  ~(cited at Heb 1:5; 5:5)~   an Old Testament verse quoted/alluded to in the New
  ~(cf. Mk 7:27–28)~          parallel accounts (Gospels, Samuel–Kings/Chronicles, duplicated psalms)
  ~(see ESV footnote)~        a footnote that matters for the verse's placement
Classifications carry these as structured fields (cites, cited_at, parallels,
esv_footnote); references are re-rendered in house abbreviations here, whatever
spelling the model used. Older classifications have one free-text `note`: only
its unambiguous cites/cited at/footnote forms are used; the rest is for review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .refs import ALIASES, OSIS, Ref
from .sitemd import Annotation, Item, RefLineError, parse_refline, render_items

# Spellings the model tends to use in notes (SBL/OSIS style), beyond the site's own.
_EXTRA = {
    "Gen": "Ge", "Exod": "Ex", "Num": "Nu", "Deut": "Dt", "Josh": "Jos", "Judg": "Jdg",
    "1 Sam": "1Sa", "2 Sam": "2Sa", "1 Kgs": "1Ki", "2 Kgs": "2Ki", "1 Chr": "1Ch", "2 Chr": "2Ch",
    "1 Chron": "1Ch", "2 Chron": "2Ch", "Neh": "Ne", "Esth": "Est", "Pss": "Ps", "Prov": "Pr",
    "Eccl": "Ecc", "Song": "SS", "Lam": "La", "Ezek": "Eze", "Dan": "Da", "Obad": "Ob",
    "Jonah": "Jnh", "Nah": "Na", "Zeph": "Zep", "Zech": "Zec", "Matt": "Mt", "Mark": "Mk",
    "Luke": "Lk", "John": "Jn", "Acts": "Ac", "Rom": "Ro", "1 Cor": "1Co", "2 Cor": "2Co",
    "Phil": "Php", "1 Thess": "1Th", "2 Thess": "2Th", "1 Tim": "1Ti", "2 Tim": "2Ti",
    "Phlm": "Phm", "1 Pet": "1Pe", "2 Pet": "2Pe", "1 John": "1Jn", "2 John": "2Jn", "3 John": "3Jn",
}
for _abbr, _osis in OSIS.items():
    _EXTRA.setdefault(_osis, _abbr)
    if _osis[0] in "123":
        _EXTRA.setdefault(f"{_osis[0]} {_osis[1:]}", _abbr)
_NAMES = {k: v for k, v in _EXTRA.items() if k not in ALIASES}
_NAME_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _NAMES), key=len, reverse=True)) + r")\.?(?= \d)")


def parse_refs(text: str) -> list[Item] | None:
    """A reference list in any common spelling, or None if it isn't one."""
    text = _NAME_RE.sub(lambda m: _NAMES[m[1]], text.strip().rstrip("."))
    if not text:
        return None
    try:
        return parse_refline(text.replace(" and ", "; "))
    except RefLineError:
        return None


@dataclass
class Notes:
    cites: list[Item] = field(default_factory=list)
    cited_at: list[Item] = field(default_factory=list)
    cf: list[Ref] = field(default_factory=list)
    esv_footnote: bool = False
    leftover: str = ""  # free text that isn't a house-style note (review only)

    def annotations(self) -> list[Annotation]:
        out = []
        for label, items in (("cites", self.cites), ("cited at", self.cited_at)):
            if items:
                out.append(Annotation.note(f"{label} {render_items(_bare(items))}"))
        if self.cf:
            out.append(Annotation.note("cf. " + render_items([Item(r) for r in self.cf])))
        if self.esv_footnote:
            out.append(Annotation.note("see ESV footnote"))
        return out

    def __bool__(self) -> bool:
        return bool(self.cites or self.cited_at or self.cf or self.esv_footnote)


def _bare(items: list[Item]) -> list[Item]:
    return [Item(i.ref) for i in items]


def _refs_or_leftover(text: str, leftovers: list[str]) -> list[Item]:
    if not text.strip():
        return []
    items = parse_refs(text)
    if items is None:
        leftovers.append(text.strip())
        return []
    return items


def notes_of(c: dict) -> Notes:
    """House-style notes from a classification (new structured fields, or a legacy `note`)."""
    left: list[str] = []
    n = Notes()
    if any(k in c for k in ("cites", "cited_at", "parallels", "esv_footnote")):
        n.cites = _refs_or_leftover(c.get("cites", ""), left)
        n.cited_at = _refs_or_leftover(c.get("cited_at", ""), left)
        n.cf = [i.ref for i in _refs_or_leftover(c.get("parallels", ""), left)]
        n.esv_footnote = bool(c.get("esv_footnote"))
    elif legacy := (c.get("note") or "").strip():
        m = re.fullmatch(r"(cites|cited at)\s+(.*)", legacy, re.I)
        items = parse_refs(m[2]) if m else None
        if items is not None:
            if m[1].lower() == "cites":
                n.cites = items
            else:
                n.cited_at = items
        elif re.fullmatch(r"see ESV footnote\.?", legacy, re.I):
            n.esv_footnote = True
        else:
            left.append(legacy)  # includes old free-form "cf." cross-references
    n.leftover = "; ".join(left)
    return n


def note_text(c: dict) -> str:
    """Everything notable, as one line (for reports)."""
    n = notes_of(c)
    parts = [a.text for a in n.annotations()]
    if n.leftover:
        parts.append(f"remark: {n.leftover}")
    return "; ".join(parts)
