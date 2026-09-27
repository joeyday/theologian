"""Compare a study's search results and blind classifications with the page.

The page (in the vault) is the record of confirmed decisions. decisions.yaml
records passages Joey has rejected, so they stop being suggested:

    exclude:
      - ref: Mt 5:1
        reason: not about God's fatherhood
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from .corpus import Corpus, Verse
from .refs import parse_ref
from .sitemd import Item, Page
from .study import Study


def vref(v: Verse) -> str:
    return f"{v[0]} {v[1]}:{v[2]}"


def page_verses(page: Page, corpus: Corpus) -> dict[Verse, list[str]]:
    """Every verse the page lists, with the section title(s) it's under."""
    counts = corpus.verse_counts
    out: dict[Verse, list[str]] = {}
    for sec in page.sections():
        title = sec.heading.title if sec.heading else ""
        for item in sec.items:
            for v in item.ref.verses(counts):
                if title not in out.setdefault(v, []):
                    out[v].append(title)
    return out


def excluded(study: Study, corpus: Corpus) -> dict[Verse, str]:
    path = study.dir / "decisions.yaml"
    if not path.exists():
        return {}
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = {}
    for e in d.get("exclude") or []:
        for v in parse_ref(e["ref"]).verses(corpus.verse_counts):
            out[v] = e.get("reason", "")
    return out


@dataclass
class Audit:
    missing: list[tuple[str, dict]] = field(default_factory=list)  # (ref, classification) relevant, not on page
    not_relevant: list[tuple[str, Item, list[dict]]] = field(default_factory=list)  # (section, item, results)
    other_category: list[tuple[str, Item, set[str], list[dict]]] = field(default_factory=list)
    not_found: list[tuple[str, Item]] = field(default_factory=list)  # search never reached it
    unclassified: list[tuple[str, Item]] = field(default_factory=list)  # found but not yet classified
    agreed: int = 0


def audit(study: Study, page: Page, corpus: Corpus, candidates: set[Verse], cls: dict[str, dict]) -> Audit:
    a = Audit()
    on_page = page_verses(page, corpus)
    skip = excluded(study, corpus)
    for ref, c in cls.items():
        r = parse_ref(ref)
        v = (r.book, r.chapter, r.verse)
        if c["relevant"] and v not in on_page and v not in skip:
            a.missing.append((ref, c))
    names = {c.name for c in study.categories}
    for sec in page.sections():
        title = sec.heading.title if sec.heading else ""
        if title not in names:
            continue  # "See also" etc.
        for item in sec.items:
            verses = list(item.ref.verses(corpus.verse_counts))
            if not any(v in candidates for v in verses):
                a.not_found.append((title, item))
                continue
            results = [cls[vref(v)] for v in verses if vref(v) in cls]
            if not results:
                a.unclassified.append((title, item))
                continue
            relevant = [r for r in results if r["relevant"]]
            if not relevant:
                a.not_relevant.append((title, item, results))
                continue
            cats = {c for r in relevant for c in r["categories"]}
            if title in cats:
                a.agreed += 1
            else:
                a.other_category.append((title, item, cats, relevant))
    return a


def _why(results: list[dict]) -> str:
    best = max(results, key=lambda r: {"high": 2, "medium": 1, "low": 0}[r["confidence"]])
    return f"({best['confidence']}) {best['rationale']}"


def report(study: Study, a: Audit) -> str:
    n_items = a.agreed + len(a.not_relevant) + len(a.other_category)
    lines = [f"# Audit: {study.title}", ""]
    lines.append(f"Of {n_items} classified page entries, the model agrees with {a.agreed}, "
                 f"puts {len(a.other_category)} in a different category, and judges "
                 f"{len(a.not_relevant)} not relevant. It suggests {len(a.missing)} verses not on the page. "
                 f"{len(a.not_found)} page entries were never reached by the search; "
                 f"{len(a.unclassified)} were found but not yet classified.")
    lines += ["", "Judgments were made blind: the model never saw the page's categories.", ""]

    lines += [f"## Possibly missing from the page ({len(a.missing)})", "",
              "Relevant by the model's reading, not on the page. Add to the page, or add to "
              "`decisions.yaml` under `exclude` to stop seeing them.", ""]
    by_cat: dict[str, list] = {}
    for ref, c in a.missing:
        key = ", ".join(c["categories"]) or f"(proposed: {c['proposed_category']})"
        by_cat.setdefault(key, []).append((ref, c))
    for cat, rows in sorted(by_cat.items()):
        lines.append(f"### {cat}")
        for ref, c in rows:
            note = f" — note: {c['note']}" if c.get("note") else ""
            lines.append(f"- **{ref}** ({c['confidence']}) {c['rationale']}{note}")
        lines.append("")

    lines += [f"## Different category ({len(a.other_category)})", ""]
    for title, item, cats, results in a.other_category:
        lines.append(f"- **{item.ref}** — page: {title}; model: {', '.join(sorted(cats))}. {_why(results)}")
    lines += ["", f"## Judged not relevant ({len(a.not_relevant)})", "",
              "Includes entries whose verses the model read as context rather than the point itself.", ""]
    for title, item, results in a.not_relevant:
        lines.append(f"- **{item.ref}** — page: {title}. {_why(results)}")
    lines += ["", f"## Never reached by the search ({len(a.not_found)})", "",
              "These entries were found by your reading, not by any query in study.yaml.", ""]
    for title, item in a.not_found:
        lines.append(f"- **{item.ref}** — {title}")
    if a.unclassified:
        lines += ["", f"## Found but not yet classified ({len(a.unclassified)})", ""]
        lines += [f"- {item.ref} — {title}" for title, item in a.unclassified]
    return "\n".join(lines) + "\n"
