"""Produce a draft page: the existing page (if any) plus the model's additions.

Additions carry an Obsidian comment, %% new (medium): rationale %%, which shows
in the editor and is stripped by the site build — review, then delete the
comment to accept. Existing entries and all other page content are unchanged.
"""

from __future__ import annotations

from .audit import excluded, page_verses
from .corpus import Corpus, Verse
from .refs import BOOK_INDEX, Ref, parse_ref
from .sitemd import Annotation, Heading, Item, Page, Raw, RefLine
from .study import Study

RANK = {"high": 2, "medium": 1, "low": 0}


def additions(study: Study, page: Page | None, corpus: Corpus, cls: dict[str, dict],
              min_confidence: str = "low") -> dict[str, list[Item]]:
    """category name -> new Items (contiguous verses merged into ranges)."""
    on_page: dict[Verse, list[str]] = page_verses(page, corpus) if page else {}
    skip = excluded(study, corpus)
    picked: dict[str, list[tuple[Verse, dict]]] = {}
    for ref, c in cls.items():
        if not c["relevant"] or RANK[c["confidence"]] < RANK[min_confidence]:
            continue
        r = parse_ref(ref)
        v = (r.book, r.chapter, r.verse)
        if v in skip:
            continue
        for cat in c["categories"] or [f"(proposed) {c['proposed_category']}"]:
            if cat not in on_page.get(v, []):
                picked.setdefault(cat, []).append((v, c))
    out: dict[str, list[Item]] = {}
    for cat, rows in picked.items():
        rows.sort(key=lambda x: (BOOK_INDEX[x[0][0]], x[0][1], x[0][2]))
        runs: list[list[tuple[Verse, dict]]] = []
        for v, c in rows:
            last = runs[-1][-1][0] if runs else None
            if last and last[:2] == v[:2] and last[2] + 1 == v[2] and not runs[-1][-1][1].get("note"):
                runs[-1].append((v, c))
            else:
                runs.append([(v, c)])
        items = []
        for run in runs:
            (b, ch, v1), (_, _, v2) = run[0][0], run[-1][0]
            ref = Ref(b, ch, v1, end_verse=v2 if v2 != v1 else None)
            conf = min((c["confidence"] for _, c in run), key=RANK.get)
            anns = []
            if note := run[-1][1].get("note"):
                anns.append(Annotation.note(note))
            why = " / ".join(dict.fromkeys(c["rationale"] for _, c in run))
            anns.append(Annotation("comment", f"%% new ({conf}): {why.replace('%%', '%')} %%"))
            items.append(Item(ref, anns))
        out[cat] = items
    return out


def _merge(existing: list[Item], new: list[Item]) -> list[Item]:
    return sorted(existing + new, key=lambda i: i.ref.sort_key())


def draft(study: Study, page: Page | None, corpus: Corpus, cls: dict[str, dict],
          min_confidence: str = "low") -> Page:
    adds = additions(study, page, corpus, cls, min_confidence)
    if page is None:
        fm = "draft: true\n"
        page = Page(fm, [Raw(study.intro)] if study.intro else [])
    lines = list(page.lines)
    # Insert additions into existing sections; a section's ref lines become one line.
    seen: set[str] = set()
    out: list = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        if isinstance(line, Heading):
            title = line.title
            seen.add(title)
            if title in adds:
                j = i
                existing: list[Item] = []
                while j < len(lines) and not isinstance(lines[j], Heading):
                    if isinstance(lines[j], RefLine):
                        existing.extend(lines[j].items)
                    j += 1
                block = lines[i:j]
                ref_idx = [k for k, l in enumerate(block) if isinstance(l, RefLine)]
                merged = RefLine(_merge(existing, adds[title]))
                if ref_idx:
                    block = [l for k, l in enumerate(block) if not isinstance(l, RefLine) or k == ref_idx[0]]
                    block[ref_idx[0]] = merged
                else:
                    block = [merged] + block
                out.extend(block)
                i = j
    # Categories with additions but no section yet: add before "See also" (or at the end).
    missing = [c for c in study.categories if c.name in adds and c.name not in seen]
    missing += [type("C", (), {"name": k, "heading": k})() for k in adds if k.startswith("(proposed)")]
    if missing:
        at = next((k for k, l in enumerate(out) if isinstance(l, Heading) and l.title == "See also"), len(out))
        new_lines = []
        for c in missing:
            new_lines += [Heading(3, c.heading), RefLine(adds[c.name])]
        out[at:at] = new_lines
    return Page(page.frontmatter_raw, out, page.trailing_newline, page.path)
