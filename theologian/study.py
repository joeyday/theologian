"""A study: one topic page's definition, kept in studies/<slug>/study.yaml.

    title: God the Father
    page: God the Father.md          # file under the vault's topic/ folder
    intro: Places in Scripture where …
    criteria: Include a verse when …     # what makes a verse belong (for the classifier)
    model: claude-opus-5-5               # optional overrides
    effort: low
    queries:                         # candidate search, see gather.py
      - name: pater
        strongs: [G3962]
      - name: son of God (OT)
        strongs: [H1121]
        with: {strongs: [H0430, H3068], window: 1}
      - name: English "Father"
        english: ['\\bFather\\b']
        case: true
    categories:
      - name: Of Jesus
        description: God is Father of Jesus, or Jesus is called God's Son.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STUDIES = ROOT / "studies"
VAULT_TOPICS = Path("/Users/joeyday/Documents/Obsidian/Tota Scriptura/topic")


@dataclass
class Category:
    name: str  # the page heading, e.g. "Of believers, the elect"
    description: str = ""
    subtitle: str | None = None  # rendered as "~(the true Israel)~" after the heading

    @property
    def heading(self) -> str:
        return f"{self.name} ~({self.subtitle})~" if self.subtitle else self.name


@dataclass
class Study:
    slug: str
    title: str
    page: str | None = None
    intro: str = ""
    criteria: str = ""
    model: str | None = None
    effort: str | None = None
    queries: list[dict] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)

    @property
    def dir(self) -> Path:
        return STUDIES / self.slug

    @property
    def page_path(self) -> Path | None:
        return VAULT_TOPICS / self.page if self.page else None

    def to_yaml(self) -> dict:
        d = {"title": self.title}
        if self.page:
            d["page"] = self.page
        d["intro"] = self.intro
        d["criteria"] = self.criteria
        for k in ("model", "effort"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        d["queries"] = self.queries
        d["categories"] = [
            {"name": c.name, **({"subtitle": c.subtitle} if c.subtitle else {}), "description": c.description}
            for c in self.categories
        ]
        return d

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "study.yaml").write_text(
            yaml.safe_dump(self.to_yaml(), sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")


def load_study(slug: str) -> Study:
    path = STUDIES / slug / "study.yaml"
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Study(
        slug=slug,
        title=d.get("title", slug),
        page=d.get("page"),
        intro=d.get("intro", ""),
        criteria=d.get("criteria", ""),
        model=d.get("model"),
        effort=d.get("effort"),
        queries=d.get("queries") or [],
        categories=[Category(c["name"], c.get("description", ""), c.get("subtitle"))
                    for c in d.get("categories") or []],
    )
