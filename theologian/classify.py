"""LLM classification of candidate verses against a study's categories.

One request per chapter (chunked for chapters with many candidates): the model
reads the whole chapter, then judges each candidate verse. It never sees an
existing page's categorization — audits compare afterwards, blind.
Results accumulate in studies/<slug>/classifications.json keyed by "Mt 5:9".
"""

from __future__ import annotations

import json
from collections import OrderedDict
from datetime import date

from . import llm
from .corpus import Corpus
from .gather import Candidate
from .refs import ABBREVS, FULL_NAME
from .study import Study

CHUNK = 30  # max candidate verses per request

SYSTEM = """\
You are helping a careful Bible student build an exhaustive topical study, "{title}".
The finished page lists every relevant passage, grouped by category. {intro}

What belongs in the study:
{criteria}

Categories:
{categories}

You will receive one chapter of Scripture and a list of candidate verses in it that a word search flagged. For each candidate verse:
- relevant: does the verse itself belong in the study? A word match alone is not enough; judge by what the text says, read in its context.
- category: the one heading that best fits the verse when it is relevant; "" when it is not relevant, or when no heading fits (then name one in proposed_category). When two headings are plausible, pick the better one, lower your confidence, and name the alternative in the rationale.
- also: usually empty. Add another heading only when the verse itself makes a second, separate statement that falls under it (two different subjects, each squarely under a different heading). Related themes, the surrounding context, or an alternative reading are not reasons to use it. The page should stay tight: each verse normally appears under one heading.
- proposed_category: a short name for a missing category, or "".
- confidence: high, medium, or low.
- rationale: one sentence, at most 30 words, naming what in the text or its context decides it.
- cites, cited_at, parallels, esv_footnote: the page's only inline notes. Leave them empty for most verses; never use them for general cross-references, similar wording, or commentary (put any remark in the rationale instead). Write references with these book abbreviations: {abbrevs}.
  - cites: for a New Testament verse, the Old Testament text(s) it quotes or clearly alludes to, e.g. "Ps 2:7; 2Sa 7:14".
  - cited_at: for an Old Testament verse, where the New Testament quotes or clearly alludes to it, e.g. "Ac 13:33; Heb 1:5".
  - parallels: only parallel accounts of the same event or saying: the same episode in other Gospels, Samuel–Kings and Chronicles, or a psalm reproduced elsewhere (Ps 18 and 2Sa 22, Ps 105 and 1Ch 16). E.g. "Mk 10:30; Lk 18:30".
  - esv_footnote: true only when the chapter text you were given has an ESV footnote on this verse that bears on whether or where it belongs (a textual variant or alternative rendering).

Read each text on its own terms and in its literary context. Do not import the conclusions of any particular theological tradition. Where careful readers genuinely disagree, choose the reading the text best supports, lower your confidence, and say why in the rationale. Report every candidate verse you were given, in order, using the reference exactly as given."""


def system_prompt(study: Study) -> str:
    cats = "\n".join(f"- {c.name}: {c.description}".rstrip(": ") for c in study.categories) or "(none yet)"
    return SYSTEM.format(title=study.title, intro=study.intro, criteria=study.criteria or "(see title)",
                         categories=cats, abbrevs=", ".join(ABBREVS))


def schema(study: Study) -> dict:
    names = [c.name for c in study.categories]
    cat = {"type": "string", "enum": names} if names else {"type": "string"}
    item = {
        "type": "object",
        "properties": {
            "ref": {"type": "string"},
            "relevant": {"type": "boolean"},
            "category": {"type": "string", "enum": names + [""]} if names else cat,
            "also": {"type": "array", "items": cat},
            "proposed_category": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "rationale": {"type": "string"},
            "cites": {"type": "string"},
            "cited_at": {"type": "string"},
            "parallels": {"type": "string"},
            "esv_footnote": {"type": "boolean"},
        },
        "required": ["ref", "relevant", "category", "also", "proposed_category", "confidence", "rationale",
                     "cites", "cited_at", "parallels", "esv_footnote"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"verses": {"type": "array", "items": item}},
        "required": ["verses"],
        "additionalProperties": False,
    }


def chapter_text(corpus: Corpus, book: str, chapter: int, esv=None) -> tuple[str, str]:
    """(translation label, numbered chapter text)."""
    if esv is not None:
        ch = esv.chapter(book, chapter)
        lines = [f"[{n}] {t}" for n, t in ch["verses"].items()]
        if ch["footnotes"]:
            lines.append(f"\nESV footnotes: {ch['footnotes']}")
        return "ESV", "\n".join(lines)
    verses = sorted(v for (b, c, v) in corpus.english if b == book and c == chapter)
    return "BSB", "\n".join(f"[{v}] {corpus.english[(book, chapter, v)]}" for v in verses)


def group_by_chapter(cands: list[Candidate]) -> "OrderedDict[tuple[str, int], list[Candidate]]":
    groups: OrderedDict[tuple[str, int], list[Candidate]] = OrderedDict()
    for c in cands:
        groups.setdefault(c.verse[:2], []).append(c)
    return groups


def build_requests(study: Study, corpus: Corpus, cands: list[Candidate], esv=None) -> dict[str, dict]:
    model = study.model or llm.DEFAULT_MODEL
    effort = study.effort or llm.DEFAULT_EFFORT
    system, sch = system_prompt(study), schema(study)
    requests: dict[str, dict] = {}
    for (book, ch), group in group_by_chapter(cands).items():
        label, text = chapter_text(corpus, book, ch, esv)
        for i in range(0, len(group), CHUNK):
            part = group[i : i + CHUNK]
            listing = "\n".join(f"- {c.ref} (matched: {'; '.join(h.split(': ', 1)[1] for h in c.hits[:4])})" for c in part)
            user = (f"{FULL_NAME[book]} {ch} ({label})\n\n{text}\n\n"
                    f"Candidate verses to classify:\n{listing}")
            cid = f"{book}-{ch}" + (f"-{i // CHUNK + 1}" if len(group) > CHUNK else "")
            requests[cid] = llm.params(model, effort, system, user, sch,
                                       max_tokens=min(32000, 8000 + 250 * len(part)))
    return requests


def merge_results(study: Study, results: list[llm.Result], model: str) -> tuple[dict, list[str]]:
    """Fold results into classifications.json; returns (all classifications, errors)."""
    path = study.dir / "classifications.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    errors = []
    today = date.today().isoformat()
    for r in results:
        if r.error or not r.data:
            errors.append(f"{r.custom_id}: {r.error}")
            continue
        for v in r.data.get("verses", []):
            ref = v.pop("ref")
            # Stored as one list, primary heading first (the format audit/draft read).
            primary, also = v.pop("category", ""), v.pop("also", [])
            cats = ([primary] if primary else []) + [c for c in also if c != primary]
            relevant = v.pop("relevant")
            data[ref] = {"relevant": relevant, "categories": cats if relevant else [],
                         **v, "model": model, "date": today}
    llm.save_json(path, data)
    return data, errors
