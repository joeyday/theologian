"""Round-trip every topic page in the real vault (skipped if it's absent)."""

from pathlib import Path

import pytest

from theologian.lint import lint_page
from theologian.sitemd import load_page

TOPICS = Path("/Users/joeyday/Documents/Obsidian/Tota Scriptura/topic")
PATHS = sorted(TOPICS.glob("*.md")) if TOPICS.is_dir() else []


@pytest.mark.skipif(not PATHS, reason="vault not available")
@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.name)
def test_topic_page_round_trips(path):
    page = load_page(path)
    assert page.render() == path.read_text(encoding="utf-8")
    # Every ref-list rewrite is explained by a lint finding.
    assert not [f for f in load_and_lint(path) if f.kind == "unexplained"]


def load_and_lint(path):
    return lint_page(load_page(path))
