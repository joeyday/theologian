"""Local Bible data: STEPBible tagged Hebrew/Greek (lemma search) and the
public-domain Berean Standard Bible (English keyword search, fallback context).

Everything is keyed by (book, chapter, verse) in English versification, with
books as house abbreviations ("Ge", "1Co"), matching refs.Ref.

Sources (downloaded by `theo fetch-data` into data/):
  STEPBible TAHOT/TAGNT, CC BY 4.0, https://github.com/STEPBible/STEPBible-Data
  Berean Standard Bible, public domain, https://bereanbible.com/bsb.txt
"""

from __future__ import annotations

import pickle
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .refs import ALIASES, BOOK_INDEX, OSIS

DATA = Path(__file__).resolve().parent.parent / "data"
STEP_DIR = DATA / "stepbible"
BSB_PATH = DATA / "bsb.txt"
CACHE = DATA / "corpus.pickle"
CACHE_VERSION = 3  # bump when parsing changes

_STEP_BASE = "https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Translators%20Amalgamated%20OT%2BNT/"
STEP_FILES = [
    "TAHOT Gen-Deu - Translators Amalgamated Hebrew OT - STEPBible.org CC BY.txt",
    "TAHOT Jos-Est - Translators Amalgamated Hebrew OT - STEPBible.org CC BY.txt",
    "TAHOT Job-Sng - Translators Amalgamated Hebrew OT - STEPBible.org CC BY.txt",
    "TAHOT Isa-Mal - Translators Amalgamated Hebrew OT - STEPBible.org CC BY.txt",
    "TAGNT Mat-Jhn - Translators Amalgamated Greek NT - STEPBible.org CC-BY.txt",
    "TAGNT Act-Rev - Translators Amalgamated Greek NT - STEPBible.org CC-BY.txt",
]
BSB_URL = "https://bereanbible.com/bsb.txt"

# STEPBible book codes that differ from OSIS.
_STEP_TO_OSIS = {
    "Exo": "Exod", "Deu": "Deut", "Rut": "Ruth", "Ezr": "Ezra", "Amo": "Amos", "Zec": "Zech", "Act": "Acts", "Tit": "Titus",
    "Jos": "Josh", "Jdg": "Judg", "1Sa": "1Sam", "2Sa": "2Sam",
    "1Ki": "1Kgs", "2Ki": "2Kgs", "1Ch": "1Chr", "2Ch": "2Chr", "Est": "Esth", "Psa": "Ps",
    "Pro": "Prov", "Ecc": "Eccl", "Sng": "Song", "Ezk": "Ezek", "Jol": "Joel", "Oba": "Obad",
    "Jon": "Jonah", "Nam": "Nah", "Zep": "Zeph", "Mat": "Matt", "Mrk": "Mark", "Luk": "Luke",
    "Jhn": "John", "1Co": "1Cor", "2Co": "2Cor", "Php": "Phil", "1Th": "1Thess", "2Th": "2Thess",
    "1Ti": "1Tim", "2Ti": "2Tim", "Phm": "Phlm", "1Pe": "1Pet", "2Pe": "2Pet", "1Jn": "1John",
    "2Jn": "2John", "3Jn": "3John", "Jud": "Jude",
}
_OSIS_TO_ABBR = {osis: abbr for abbr, osis in OSIS.items()}

# "Gen.1.1#01=L", "Psa.3.1(3.2)#01=L", "Rom.16.25{14.24}#01=NKO",
# "2Co.13.12[13.13]#01=NKO": the English (ESV) ref comes first; alternative
# numberings follow in brackets -- except 2Co 13, where [ ] is the English one.
_WORD_ROW = re.compile(
    r"^([1-3]?[A-Z][a-z]+)\.(\d+)\.(\d+)(?:\((?:[^)]*)\)|\{(?:[^}]*)\}|\[\d+\.(\d+)\])?#\d+=(\S+)\t")
_STRONG = re.compile(r"([HG])(\d+)([A-Za-z]?)")

Verse = tuple[str, int, int]


@dataclass(frozen=True)
class Word:
    strong: str  # normalized, disambiguated: "H5769", "G0166", "H1254A"
    lemma: str  # dictionary form, e.g. "עוֹלָם" / "αἰώνιος"
    gloss: str  # short dictionary gloss
    english: str  # contextual English rendering of this word
    source: str  # manuscript/edition code, e.g. "L", "Q(K)", "NKO", "K"


def norm_strong(s: str) -> str:
    """'G166' → 'G0166', 'h5769a' → 'H5769A'."""
    m = _STRONG.fullmatch(s.strip())
    if not m:
        raise ValueError(f"not a Strong's number: {s!r}")
    return f"{m[1].upper()}{int(m[2]):04d}{m[3].upper()}"


def strong_matches(query: str, strong: str) -> bool:
    """'H5769' matches H5769 and H5769A/B…; 'H5769A' matches only itself."""
    q = norm_strong(query)
    return strong == q or (not q[-1].isalpha() and strong[:-1] == q and strong[-1].isalpha())


@dataclass
class Corpus:
    words: dict[Verse, list[Word]]
    english: dict[Verse, str]  # BSB text

    @property
    def verse_counts(self) -> dict[tuple[str, int], int]:
        out: dict[tuple[str, int], int] = {}
        for b, c, v in self.english:
            out[(b, c)] = max(out.get((b, c), 0), v)
        return out

    def verses_in_order(self) -> list[Verse]:
        return sorted(self.english, key=lambda k: (BOOK_INDEX[k[0]], k[1], k[2]))


def _parse_step_file(path: Path, words: dict[Verse, list[Word]]) -> None:
    is_nt = "TAGNT" in path.name
    with path.open(encoding="utf-8") as f:
        for line in f:
            m = _WORD_ROW.match(line)
            if not m:
                continue
            osis = _STEP_TO_OSIS.get(m[1], m[1])
            book = _OSIS_TO_ABBR[osis]
            cols = line.rstrip("\n").split("\t")
            if is_nt:
                # Word&Type | Greek | English | dStrongs=Grammar | Dict form=Gloss | ...
                strongs = [cols[3].split("=")[0]]
                lemma, _, gloss = cols[4].partition("=")
                english = cols[2]
            else:
                # Ref&Type | Hebrew | Translit | Translation | dStrongs | Grammar | ... | Expanded
                # dStrongs like "H9003/{H7225G}": braces mark the content word.
                strongs = re.findall(r"\{([^}]+)\}", cols[4]) or cols[4].split("/")
                expanded = cols[11] if len(cols) > 11 else ""
                em = re.search(r"\{[^=}]+=([^=}]+)=([^}]*)\}", expanded)
                lemma, gloss = (em[1], em[2]) if em else ("", "")
                english = cols[3]
            for s in strongs:
                sm = _STRONG.search(s)
                if not sm:
                    continue
                strong = norm_strong(sm[0])
                if strong[1:5] >= "9000":  # prefixes/suffixes (articles, prepositions…)
                    continue
                # Psalm superscriptions are verse 0 here; English Bibles fold them into verse 1.
                verse = int(m[3]) or 1
                if book == "2Co" and m[4]:
                    verse = int(m[4])
                words.setdefault((book, int(m[2]), verse), []).append(
                    Word(strong, lemma.strip(), gloss.strip(), english.strip(), m[5]))


def _parse_bsb(path: Path) -> dict[Verse, str]:
    out: dict[Verse, str] = {}
    ref_re = re.compile(r"^(.+?) (\d+):(\d+)\t(.*)$")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m = ref_re.match(line)
        if m and m[1] in ALIASES:
            out[(ALIASES[m[1]], int(m[2]), int(m[3]))] = m[4].strip()
    return out


def fetch_data(force: bool = False) -> None:
    STEP_DIR.mkdir(parents=True, exist_ok=True)
    for name in STEP_FILES:
        dest = STEP_DIR / name
        if force or not dest.exists():
            print(f"downloading {name}")
            urllib.request.urlretrieve(_STEP_BASE + urllib.parse.quote(name), dest)
    if force or not BSB_PATH.exists():
        print("downloading bsb.txt")
        urllib.request.urlretrieve(BSB_URL, BSB_PATH)


@cache
def load() -> Corpus:
    sources = [STEP_DIR / n for n in STEP_FILES] + [BSB_PATH]
    missing = [p.name for p in sources if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing Bible data ({', '.join(missing)}); run `theo fetch-data`")
    newest = max(p.stat().st_mtime for p in sources)
    if CACHE.exists() and CACHE.stat().st_mtime > newest:
        with CACHE.open("rb") as f:
            version, corpus = pickle.load(f)
        if version == CACHE_VERSION:
            return corpus
    words: dict[Verse, list[Word]] = {}
    for p in sources[:-1]:
        _parse_step_file(p, words)
    corpus = Corpus(words, _parse_bsb(BSB_PATH))
    with CACHE.open("wb") as f:
        pickle.dump((CACHE_VERSION, corpus), f)
    return corpus
