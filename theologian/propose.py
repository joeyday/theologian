"""Propose a category scheme for a new study from its candidate verses.

One request: the model skims every candidate verse (BSB text) and suggests
categories, keeping any headings the page already has. Joey edits the result
in study.yaml before classifying.
"""

from __future__ import annotations

from . import llm
from .corpus import Corpus
from .gather import Candidate
from .sitemd import Page
from .study import Study

SYSTEM = """\
You are helping a careful Bible student plan an exhaustive topical study, "{title}". {intro}

The finished page groups passages under headings by who or what the topic applies to, in the author's terse style. For example, a study of God as Father uses headings like "Of Jesus", "Of Israel", "Of believers, the elect", "Of all men?", "Parables", "Allegories". Headings are short; a question mark marks a doubtful category.

You will get every verse a word search flagged (many will turn out irrelevant) and the headings the author has already drafted, if any. Propose a category scheme that:
- keeps the author's existing headings, in wording and order, unless one is clearly malformed;
- covers the subjects the relevant verses actually speak of, at a useful granularity (typically 6-15 categories);
- orders categories from most to least theologically central, following the author's order where it exists.
For each category give a one-sentence description precise enough for a careful reader to sort verses consistently, and up to five example references drawn from the verses provided. Read the texts on their own terms; do not import any tradition's conclusions."""

SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "examples": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "description", "examples"],
                "additionalProperties": False,
            },
        },
        "comments": {"type": "string"},
    },
    "required": ["categories", "comments"],
    "additionalProperties": False,
}


def build_request(study: Study, corpus: Corpus, cands: list[Candidate], page: Page | None) -> dict:
    existing = [s.heading.text for s in page.sections() if s.heading] if page else []
    verses = "\n".join(f"{c.ref} {corpus.english.get(c.verse, '')}" for c in cands)
    user = ("Existing headings: " + ("; ".join(existing) if existing else "(none)") +
            f"\n\nCandidate verses ({len(cands)}, BSB):\n{verses}")
    system = SYSTEM.format(title=study.title, intro=study.intro)
    # A single long request: give the model room and a higher effort.
    p = llm.params(study.model or llm.DEFAULT_MODEL, "high", system, user, SCHEMA, max_tokens=32000)
    return p


def run(study: Study, corpus: Corpus, cands: list[Candidate], page: Page | None) -> dict:
    p = build_request(study, corpus, cands, page)
    c = llm.client()
    with c.beta.messages.stream(**p, betas=[llm.FALLBACK_BETA], fallbacks="default") as stream:
        msg = stream.get_final_message()
    r = llm._parse_message("propose", msg)
    if r.error:
        raise RuntimeError(r.error)
    return r.data
