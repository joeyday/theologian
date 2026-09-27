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


def c(relevant, cats, conf="high", note="", **fields):
    d = {"relevant": relevant, "categories": cats, "proposed_category": "", "confidence": conf,
         "rationale": "because", "note": note}
    if fields:
        del d["note"]
        d |= {"cites": "", "cited_at": "", "parallels": "", "esv_footnote": False} | fields
    return d


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
    # a legacy free-form "cf." note is not a house-style note: it goes into the comment
    assert "### Of Jesus\nHos 11:3 %% new (high): because Remark: cf. Mt 2:15 %%\n## See also" in out
    # everything else untouched
    assert out.startswith("---\ndraft: true\n---\nIntro.\n### Of Israel\n")


def test_draft_respects_exclusions(tmp_path):
    s = study(tmp_path)
    s.dir.mkdir(parents=True)
    (s.dir / "decisions.yaml").write_text("exclude:\n  - ref: Isa 63:16–17\n")
    out = draft(s, parse_page(PAGE), corpus(), CLS).render()
    assert "Isa 63" not in out


def test_audit_surfaces_extra_categories(tmp_path):
    s = study(tmp_path)
    page = parse_page(PAGE.replace("### Allegories\nPs 103:13", "### Allegories\nPs 103:13; Hos 11:1"))
    cls = CLS | {"Hos 11:1": c(True, ["Of Israel", "Allegories", "Of Jesus"])}
    a = audit(s, page, corpus(), {("Hos", 11, 1), ("Mal", 1, 6), ("Ps", 103, 13)}, cls)
    # Hos 11:1 is listed under Israel and Allegories, so only "Of Jesus" is extra, reported once
    extras = [(title, str(i.ref), e) for title, i, e, _ in a.also]
    assert extras == [("Of Israel", "Hos 11:1", {"Of Jesus": ["Hos 11:1"]})]


def test_classify_stores_primary_first(tmp_path):
    from theologian import llm
    from theologian.classify import merge_results, schema

    s = study(tmp_path)
    sch = schema(s)["properties"]["verses"]["items"]["properties"]
    assert sch["category"]["enum"] == ["Of Israel", "Allegories", "Of Jesus", ""]
    base = {"proposed_category": "", "confidence": "high", "rationale": "r", "note": ""}
    out = {"verses": [
        {"ref": "Hos 11:1", "relevant": True, "category": "Of Israel", "also": ["Of Jesus", "Of Israel"], **base},
        {"ref": "Hos 11:2", "relevant": False, "category": "", "also": [], **base},
        {"ref": "Hos 11:3", "relevant": True, "category": "", "also": [], **{**base, "proposed_category": "X"}},
    ]}
    data, errors = merge_results(s, [llm.Result("Hos-11", out)], "m")
    assert not errors
    assert data["Hos 11:1"]["categories"] == ["Of Israel", "Of Jesus"]
    assert data["Hos 11:2"]["categories"] == []
    assert data["Hos 11:3"]["categories"] == [] and data["Hos 11:3"]["proposed_category"] == "X"


def test_audit_quotes_category_names():
    from theologian.audit import q

    assert q(["Of believers, the elect", "Of Jesus"]) == '"Of believers, the elect", "Of Jesus"'


def _section(tmp_path, cls, page_text="### Of Israel\n"):
    from theologian.render import draft

    out = draft(study(tmp_path), parse_page(page_text), corpus(), cls).render()
    return out.split("### Of Israel\n", 1)[1].split("\n", 1)[0]


def test_structured_notes_in_house_style(tmp_path):
    cls = {"Hos 11:1": c(True, ["Of Israel"], cited_at="Matt. 2:15"),
           "Mal 1:6": c(True, ["Of Israel"], parallels="1 Chr 16:15", esv_footnote=True)}
    line = _section(tmp_path, cls)
    assert line == ("Hos 11:1 ~(cited at Mt 2:15)~ %% new (high): because %%; "
                    "Mal 1:6 ~(cf. 1Ch 16:15)~ ~(see ESV footnote)~ %% new (high): because %%")


def test_cf_to_a_listed_verse_is_dropped(tmp_path):
    # Joey's example: "Ge 13:15 (cf. Ge 17:8); Ge 17:8" -- here Hos 11:1 is already on the page
    cls = {"Mal 1:6": c(True, ["Of Israel"], parallels="Hos 11:1")}
    line = _section(tmp_path, cls, "### Of Israel\nHos 11:1\n")
    assert line == "Hos 11:1; Mal 1:6 %% new (high): because %%"


def test_new_parallels_fold_into_the_first(tmp_path):
    cls = {"Hos 11:1": c(True, ["Of Israel"], parallels="Mal 1:6"),
           "Mal 1:6": c(True, ["Of Israel"], parallels="Hos 11:1; Isa 63:16"),
           "Isa 63:16": c(True, ["Of Israel"])}
    line = _section(tmp_path, cls)
    assert line == ("Isa 63:16 ~(cf. Hos 11:1; Mal 1:6)~ %% new (high): because "
                    "(parallels folded in: Hos 11:1; Mal 1:6) %%")


def test_note_ref_parsing():
    from theologian.notes import parse_refs
    from theologian.sitemd import render_items

    assert render_items(parse_refs("2 Sam 22:51 and Deut. 13:16")) == "2Sa 22:51; Dt 13:16"
    assert parse_refs("the land promise in v. 11") is None
