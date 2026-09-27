"""Audit and draft logic on a tiny in-memory corpus and fake classifications."""

from theologian.audit import audit
from theologian.corpus import Corpus
from theologian.render import draft
from theologian.sitemd import parse_page
from theologian.study import Category, Study

PAGE = """---
draft: true
---
Intro.
### Of Israel
Hos 11:1; Mal 1:6
### Allegories
Ps 103:13
## See also
- [[x]]
"""


def corpus():
    english = {("Hos", 11, v): "x" for v in range(1, 13)}
    english |= {("Mal", 1, v): "x" for v in range(1, 15)}
    english |= {("Ps", 103, v): "x" for v in range(1, 23)}
    english |= {("Isa", 63, v): "x" for v in range(1, 20)}
    return Corpus({}, english)


def study(tmp_path):
    s = Study("t", "Test", categories=[Category("Of Israel"), Category("Allegories"), Category("Of Jesus")])
    import theologian.study as st
    st.STUDIES = tmp_path
    return s


def c(relevant, cats, conf="high", note=""):
    return {"relevant": relevant, "categories": cats, "proposed_category": "", "confidence": conf,
            "rationale": "because", "note": note}


CLS = {
    "Hos 11:1": c(True, ["Of Israel"]),
    "Mal 1:6": c(True, ["Allegories"]),
    "Ps 103:13": c(False, [], "medium"),
    "Isa 63:16": c(True, ["Of Israel"], "medium"),
    "Isa 63:17": c(True, ["Of Israel"], "low"),
    "Mal 1:7": c(False, []),
}


def test_audit_buckets(tmp_path):
    s = study(tmp_path)
    page = parse_page(PAGE)
    cands = {("Hos", 11, 1), ("Mal", 1, 6), ("Ps", 103, 13), ("Isa", 63, 16), ("Isa", 63, 17), ("Mal", 1, 7)}
    a = audit(s, page, corpus(), cands, CLS)
    assert a.agreed == 1
    assert [str(i.ref) for _, i, _, _ in a.other_category] == ["Mal 1:6"]
    assert [str(i.ref) for _, i, _ in a.not_relevant] == ["Ps 103:13"]
    assert sorted(r for r, _ in a.missing) == ["Isa 63:16", "Isa 63:17"]


def test_audit_not_found(tmp_path):
    a = audit(study(tmp_path), parse_page(PAGE), corpus(), {("Hos", 11, 1)}, CLS)
    assert [str(i.ref) for _, i in a.not_found] == ["Mal 1:6", "Ps 103:13"]


def test_draft_adds_flagged_ranges_and_new_sections(tmp_path):
    s = study(tmp_path)
    cls = CLS | {"Hos 11:3": c(True, ["Of Jesus"], note="cf. Mt 2:15")}
    out = draft(s, parse_page(PAGE), corpus(), cls).render()
    assert "### Of Israel\nIsa 63:16–17 %% new (low): because %%; Hos 11:1; Mal 1:6\n" in out
    assert "### Allegories\nPs 103:13; Mal 1:6 %% new (high): because %%\n" in out
    assert "### Of Jesus\nHos 11:3 ~(cf. Mt 2:15)~ %% new (high): because %%\n## See also" in out
    # everything else untouched
    assert out.startswith("---\ndraft: true\n---\nIntro.\n### Of Israel\n")


def test_draft_respects_exclusions(tmp_path):
    s = study(tmp_path)
    s.dir.mkdir(parents=True)
    (s.dir / "decisions.yaml").write_text("exclude:\n  - ref: Isa 63:16–17\n")
    out = draft(s, parse_page(PAGE), corpus(), CLS).render()
    assert "Isa 63" not in out
