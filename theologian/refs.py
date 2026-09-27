"""Scripture references in Tota Scriptura style.

Book abbreviations and continuation semantics mirror the site's build.js:
a ref without a book name continues the previous book, and a bare number
(no colon) is a verse in the previous chapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (site abbreviation, full name, OSIS id) in canonical order.
BOOKS: list[tuple[str, str, str]] = [
    ("Ge", "Genesis", "Gen"), ("Ex", "Exodus", "Exod"), ("Lev", "Leviticus", "Lev"),
    ("Nu", "Numbers", "Num"), ("Dt", "Deuteronomy", "Deut"), ("Jos", "Joshua", "Josh"),
    ("Jdg", "Judges", "Judg"), ("Ru", "Ruth", "Ruth"), ("1Sa", "1 Samuel", "1Sam"),
    ("2Sa", "2 Samuel", "2Sam"), ("1Ki", "1 Kings", "1Kgs"), ("2Ki", "2 Kings", "2Kgs"),
    ("1Ch", "1 Chronicles", "1Chr"), ("2Ch", "2 Chronicles", "2Chr"), ("Ezr", "Ezra", "Ezra"),
    ("Ne", "Nehemiah", "Neh"), ("Est", "Esther", "Esth"), ("Job", "Job", "Job"),
    ("Ps", "Psalms", "Ps"), ("Pr", "Proverbs", "Prov"), ("Ecc", "Ecclesiastes", "Eccl"),
    ("SS", "Song of Solomon", "Song"), ("Isa", "Isaiah", "Isa"), ("Jer", "Jeremiah", "Jer"),
    ("La", "Lamentations", "Lam"), ("Eze", "Ezekiel", "Ezek"), ("Da", "Daniel", "Dan"),
    ("Hos", "Hosea", "Hos"), ("Joel", "Joel", "Joel"), ("Am", "Amos", "Amos"),
    ("Ob", "Obadiah", "Obad"), ("Jnh", "Jonah", "Jonah"), ("Mic", "Micah", "Mic"),
    ("Na", "Nahum", "Nah"), ("Hab", "Habakkuk", "Hab"), ("Zep", "Zephaniah", "Zeph"),
    ("Hag", "Haggai", "Hag"), ("Zec", "Zechariah", "Zech"), ("Mal", "Malachi", "Mal"),
    ("Mt", "Matthew", "Matt"), ("Mk", "Mark", "Mark"), ("Lk", "Luke", "Luke"),
    ("Jn", "John", "John"), ("Ac", "Acts", "Acts"), ("Ro", "Romans", "Rom"),
    ("1Co", "1 Corinthians", "1Cor"), ("2Co", "2 Corinthians", "2Cor"),
    ("Gal", "Galatians", "Gal"), ("Eph", "Ephesians", "Eph"), ("Php", "Philippians", "Phil"),
    ("Col", "Colossians", "Col"), ("1Th", "1 Thessalonians", "1Thess"),
    ("2Th", "2 Thessalonians", "2Thess"), ("1Ti", "1 Timothy", "1Tim"),
    ("2Ti", "2 Timothy", "2Tim"), ("Tit", "Titus", "Titus"), ("Phm", "Philemon", "Phlm"),
    ("Heb", "Hebrews", "Heb"), ("Jas", "James", "Jas"), ("1Pe", "1 Peter", "1Pet"),
    ("2Pe", "2 Peter", "2Pet"), ("1Jn", "1 John", "1John"), ("2Jn", "2 John", "2John"),
    ("3Jn", "3 John", "3John"), ("Jude", "Jude", "Jude"), ("Rev", "Revelation", "Rev"),
]

ABBREVS = [b[0] for b in BOOKS]
BOOK_INDEX = {abbr: i for i, abbr in enumerate(ABBREVS)}
OSIS = {abbr: osis for abbr, _, osis in BOOKS}
FROM_OSIS = {osis: abbr for abbr, _, osis in BOOKS}
FULL_NAME = {abbr: name for abbr, name, _ in BOOKS}
SINGLE_CHAPTER = {"Ob", "Phm", "2Jn", "3Jn", "Jude"}

DASH = "–"  # en dash, the site's canonical range separator
_DASHES = "-–—"

# Every spelling the site's build.js links, mapped to the house abbreviation.
ALIASES: dict[str, str] = {}
for _abbr, _name, _ in BOOKS:
    for _n in (_abbr, _name, _name.replace(" ", "")):
        ALIASES[_n] = _abbr
        if _n[0] in "123":
            ALIASES[f"{_n[0]} {_n[1:].lstrip()}"] = _abbr  # "1 Co", "1 John"
ALIASES.update({"Psalm": "Ps", "Song of Songs": "SS"})

# Longest first so "Jude" is not read as a prefix match of something shorter.
_BOOK_RE = "|".join(sorted((re.escape(a) for a in ALIASES), key=len, reverse=True))

# Book-qualified ref: "Ge 1:1", "Ps 82", "Ro 1–2", "Ge 1:1–2:3"
NAMED_REF_RE = re.compile(
    rf"(?P<book>{_BOOK_RE}) (?P<ch>\d+)"
    rf"(?::(?P<v>\d+)(?:\s*[{_DASHES}]\s*(?P<r1>\d+)(?::(?P<r2>\d+))?)?"
    rf"|\s*[{_DASHES}]\s*(?P<ech>\d+))?(?![\w:])"
)
# Continuation ref: "4:3", "4:3–5", "4:3–5:2", or bare verse "6", "6–8"
CONT_REF_RE = re.compile(
    rf"(?P<n>\d+)(?::(?P<v>\d+)(?:\s*[{_DASHES}]\s*(?P<r1>\d+)(?::(?P<r2>\d+))?)?"
    rf"|\s*[{_DASHES}]\s*(?P<bre>\d+))?(?![\w:])"
)


@dataclass(frozen=True, order=False)
class Ref:
    """A contiguous span: a whole chapter (range) or a verse (range)."""

    book: str
    chapter: int
    verse: int | None = None
    end_chapter: int | None = None  # set only when the span crosses chapters
    end_verse: int | None = None

    def __post_init__(self):
        if self.book not in BOOK_INDEX:
            raise ValueError(f"unknown book {self.book!r}")

    @property
    def is_chapter_only(self) -> bool:
        return self.verse is None

    @property
    def last_chapter(self) -> int:
        return self.end_chapter or self.chapter

    def sort_key(self):
        return (BOOK_INDEX[self.book], self.chapter, self.verse or 0,
                self.last_chapter, self.end_verse or self.verse or 0)

    def numeric(self) -> str:
        """Everything after the book name, e.g. '1:1–2:3'."""
        if self.verse is None:
            return f"{self.chapter}{DASH}{self.end_chapter}" if self.end_chapter else str(self.chapter)
        s = f"{self.chapter}:{self.verse}"
        if self.end_chapter:
            s += f"{DASH}{self.end_chapter}:{self.end_verse}"
        elif self.end_verse:
            s += f"{DASH}{self.end_verse}"
        return s

    def __str__(self) -> str:
        return f"{self.book} {self.numeric()}"

    def verses_part(self) -> str:
        """The verse part only, for same-chapter continuation: '6' or '6–8'."""
        assert self.verse is not None and not self.end_chapter
        return f"{self.verse}{DASH}{self.end_verse}" if self.end_verse else str(self.verse)

    @property
    def osis(self) -> str:
        """OSIS range, e.g. 'Gen.1.1-Gen.2.3' (ref.ly / API friendly)."""
        b = OSIS[self.book]
        start = f"{b}.{self.chapter}" + (f".{self.verse}" if self.verse else "")
        if self.verse is None:
            return start if not self.end_chapter else f"{start}-{b}.{self.end_chapter}"
        if self.end_chapter:
            return f"{start}-{b}.{self.end_chapter}.{self.end_verse}"
        if self.end_verse:
            return f"{start}-{b}.{self.chapter}.{self.end_verse}"
        return start

    def verses(self, verse_counts: dict[tuple[str, int], int] | None = None):
        """Expand to (book, chapter, verse) triples. Whole chapters and
        cross-chapter spans need verse_counts[(book, chapter)]."""
        if self.verse is not None and not self.end_chapter:
            for v in range(self.verse, (self.end_verse or self.verse) + 1):
                yield (self.book, self.chapter, v)
            return
        if verse_counts is None:
            raise ValueError(f"verse counts needed to expand {self}")
        for ch in range(self.chapter, self.last_chapter + 1):
            first = self.verse if (ch == self.chapter and self.verse) else 1
            last = self.end_verse if (ch == self.last_chapter and self.end_verse) else verse_counts[(self.book, ch)]
            for v in range(first, last + 1):
                yield (self.book, ch, v)


def _ref_from_match(book: str, ch: str, v, r1, r2, ech) -> Ref:
    book = ALIASES[book]
    ch_i = int(ch)
    if v is None:
        return Ref(book, ch_i, end_chapter=int(ech) if ech else None)
    if r2 is not None:  # cross-chapter: r1 is the end chapter
        return Ref(book, ch_i, int(v), int(r1), int(r2))
    return Ref(book, ch_i, int(v), end_verse=int(r1) if r1 else None)


def parse_ref(text: str) -> Ref:
    """Parse one fully qualified reference like 'Ge 1:1–2:3'."""
    m = NAMED_REF_RE.fullmatch(text.strip())
    if not m:
        raise ValueError(f"not a reference: {text!r}")
    return _ref_from_match(m["book"], m["ch"], m["v"], m["r1"], m["r2"], m["ech"])
