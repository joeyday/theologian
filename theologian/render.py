"""Produce a draft page: the existing page (if any) plus the model's additions.

Additions carry an Obsidian comment, %% new (medium): rationale %%, which shows
in the editor and is stripped by the site build — review, then delete the
comment to accept. Inline ~(…)~ notes follow house style (see notes.py), with
redundant cross-references removed. Existing entries and all other page
content are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from .audit import excluded, page_verses
from .corpus import Corpus, Verse
from .notes import Notes, notes_of
from .refs import BOOK_INDEX, Ref, parse_ref
from .sitemd import Annotation, Heading, Item, Page, Raw, RefLine
from .study import Study

RANK = {"high": 2, "medium": 1, "low": 0}


@dataclass
class Entry:
    """A new item for the page, before notes are tidied into annotations."""

    ref: Ref
    notes: Notes
    confidence: str
    why: str  # rationale(s), plus any free-form remark from the model
    merged: list[Ref] | None = None  # parallels folded into this entry

    def item(self) -> Item:
        why = self.why
        if self.merged:
            why += f" (parallels folded in: {'; '.join(map(str, self.merged))})"
        comment = Annotation("comment", f"%% new ({self.confidence}): {why.replace('%%', '%')} %%")
        return Item(self.ref, self.notes.annotations() + [comment])


def additions(study: Study, page: Page | None, corpus: Corpus, cls: dict[str, dict],
              min_confidence: str = "low") -> dict[str, list[Entry]]:
    """category name -> new entries (contiguous verses without notes merged into ranges)."""
    on_page: dict[Verse, list[str]] = page_verses(page, corpus) if page else {}
    skip = excluded(study, corpus)
    picked: dict[str, list[tuple[Verse, dict, Notes]]] = {}
    for ref, c in cls.items():
        if not c["relevant"] or RANK[c["confidence"]] < RANK[min_confidence]:
            continue
        r = parse_ref(ref)
        v = (r.book, r.chapter, r.verse)
        if v in skip:
            continue
        for cat in c["categories"] or [f"(proposed) {c['proposed_category']}"]:
            if cat not in on_page.get(v, []):
                picked.setdefault(cat, []).append((v, c, notes_of(c)))
    out: dict[str, list[Entry]] = {}
    for cat, rows in picked.items():
        rows.sort(key=lambda x: (BOOK_INDEX[x[0][0]], x[0][1], x[0][2]))
        runs: list[list[tuple[Verse, dict, Notes]]] = []
        for v, c, n in rows:
            last = runs[-1][-1] if runs else None
            if (last and last[0][:2] == v[:2] and last[0][2] + 1 == v[2]
                    and not last[2] and not n):
                runs[-1].append((v, c, n))
            else:
                runs.append([(v, c, n)])
        entries = []
        for run in runs:
            (b, ch, v1), (_, _, v2) = run[0][0], run[-1][0]
            whys = []
            for _, c, n in run:
                whys.append(c["rationale"] + (f" Remark: {n.leftover}" if n.leftover else ""))
            entries.append(Entry(
                Ref(b, ch, v1, end_verse=v2 if v2 != v1 else None),
                run[-1][2],
                min((c["confidence"] for _, c, _ in run), key=RANK.get),
                " / ".join(dict.fromkeys(whys)),
            ))
        out[cat] = entries
    return out


def tidy(existing: list[Item], entries: list[Entry], counts) -> list[Item]:
    """Merge a section's existing items with new entries, removing redundancy:
    a cf. pointing at a verse already listed in the section is dropped, and new
    entries that are parallels of each other fold into the canonically first,
    which lists the rest as cf. (the page's convention)."""
    entries = sorted(entries, key=lambda e: e.ref.sort_key())
    listed = {v for i in existing for v in i.ref.verses(counts)}
    owner: dict[Verse, int] = {}
    for k, e in enumerate(entries):
        for v in e.ref.verses(counts):
            owner.setdefault(v, k)
    parent = list(range(len(entries)))

    def find(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for k, e in enumerate(entries):
        own = set(e.ref.verses(counts))
        keep = []
        for r in e.notes.cf:
            vs = set(r.verses(counts))
            if vs & own or vs & listed:
                continue  # points at itself or at an entry already in this section
            linked = {owner[v] for v in vs if v in owner} - {k}
            for j in linked:
                parent[find(j)] = find(k)
            if not linked:
                keep.append(r)
        e.notes.cf = keep
    groups: dict[int, list[int]] = {}
    for k in range(len(entries)):
        groups.setdefault(find(k), []).append(k)
    kept: list[Entry] = []
    for members in groups.values():
        main, *rest = (entries[k] for k in sorted(members))
        if rest:
            main.merged = [e.ref for e in rest]
            extra = [e.ref for e in rest] + [r for e in rest for r in e.notes.cf]
            main.notes.cf = sorted(dict.fromkeys(main.notes.cf + extra), key=Ref.sort_key)
        kept.append(main)
    return sorted(existing + [e.item() for e in kept], key=lambda i: i.ref.sort_key())


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
                merged = RefLine(tidy(existing, adds[title], corpus.verse_counts))
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
            new_lines += [Heading(3, c.heading), RefLine(tidy([], adds[c.name], corpus.verse_counts))]
        out[at:at] = new_lines
    return Page(page.frontmatter_raw, out, page.trailing_newline, page.path)
