"""The Obsidian vault the site is built from (read-only)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from .sitemd import Page, expand_embeds, load_page

VAULT = Path("/Users/joeyday/Documents/Obsidian/Tota Scriptura")


@cache
def _index(root: Path) -> dict[str, list[Path]]:
    """Lower-cased file name -> paths, like build.js's embed lookup."""
    out: dict[str, list[Path]] = {}
    for p in root.rglob("*.md"):
        if not any(part.startswith(".") for part in p.relative_to(root).parts):
            out.setdefault(p.stem.lower(), []).append(p)
    return out


def resolver(root: Path = VAULT):
    def resolve(name: str) -> str | None:
        paths = _index(root).get(name.lower().strip(), [])
        return paths[0].read_text(encoding="utf-8") if len(paths) == 1 else None
    return resolve


def load_expanded(path: Path, root: Path = VAULT) -> Page:
    """A vault page with its embeds (partials) expanded for reading."""
    return expand_embeds(load_page(path), resolver(root))
