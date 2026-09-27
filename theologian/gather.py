"""Candidate search (no LLM). Each query in study.yaml finds verses; the
candidate list is their union, with a record of which queries hit each verse.

Query keys:
  name:     label shown in reports
  strongs:  [H5769, G166, …]  any of these words in the verse ('H5769' also
            matches disambiguated H5769A…; 'H5769A' matches only itself)
  english:  [regex, …]        any of these matches the BSB text
  case:     true              make english regexes case-sensitive
  testament: OT | NT          restrict the query
  with:     {strongs|english|case, window: N}
            also require this within N verses (same chapter), e.g. a word for
            God near a word for "son"
The aim is recall: the classifier discards irrelevant candidates later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .corpus import Corpus, Verse, strong_matches
from .refs import BOOK_INDEX

NT_START = BOOK_INDEX["Mt"]


@dataclass
class Candidate:
    verse: Verse
    hits: list[str] = field(default_factory=list)  # "pater: G3962 πατήρ “Father”"

    @property
    def ref(self) -> str:
        b, c, v = self.verse
        return f"{b} {c}:{v}"


def _matches(corpus: Corpus, verse: Verse, spec: dict) -> list[str]:
    """Descriptions of what in `verse` satisfies spec's strongs/english."""
    out = []
    for q in spec.get("strongs") or []:
        for w in corpus.words.get(verse, []):
            if strong_matches(str(q), w.strong):
                out.append(f"{w.strong} {w.lemma} “{w.english}”")
    flags = 0 if spec.get("case") else re.IGNORECASE
    text = corpus.english.get(verse, "")
    for pat in spec.get("english") or []:
        for m in re.finditer(pat, text, flags):
            out.append(f"“{m[0]}”")
    return out


def run_query(corpus: Corpus, q: dict, verses: list[Verse]) -> dict[Verse, list[str]]:
    testament = q.get("testament")
    found: dict[Verse, list[str]] = {}
    for verse in verses:
        is_nt = BOOK_INDEX[verse[0]] >= NT_START
        if testament and (testament == "NT") != is_nt:
            continue
        if hits := _matches(corpus, verse, q):
            found[verse] = hits
    if with_ := q.get("with"):
        window = int(with_.get("window", 0))
        kept = {}
        for (b, c, v), hits in found.items():
            near = [(b, c, v + d) for d in range(-window, window + 1)]
            if any(_matches(corpus, n, with_) for n in near if n in corpus.english or n in corpus.words):
                kept[(b, c, v)] = hits
        found = kept
    return found


def gather(corpus: Corpus, queries: list[dict]) -> list[Candidate]:
    verses = corpus.verses_in_order()
    by_verse: dict[Verse, Candidate] = {}
    for q in queries:
        name = q.get("name") or "query"
        for verse, hits in run_query(corpus, q, verses).items():
            cand = by_verse.setdefault(verse, Candidate(verse))
            # one line per query per verse, de-duplicated
            for h in dict.fromkeys(hits):
                cand.hits.append(f"{name}: {h}")
    order = {v: i for i, v in enumerate(verses)}
    return sorted(by_verse.values(), key=lambda c: order.get(c.verse, 0))
