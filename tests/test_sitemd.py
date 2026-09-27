from theologian.refs import Ref, parse_ref
from theologian.sitemd import parse_page, parse_refline, render_items

GTF_LINE = ("Lk 3:22, 23 ~(this one’s subtle)~; Lk 4:3, 9, 41; 8:28; Ps 82; 89:5–7 "
            "~(see ESV footnote)~ {{s|see also Da 3:25}}")


def test_parse_ref_forms():
    assert parse_ref("Ge 1:1–2:3") == Ref("Ge", 1, 1, 2, 3)
    assert parse_ref("Ro 1–2") == Ref("Ro", 1, end_chapter=2)
    assert parse_ref("Ps 82") == Ref("Ps", 82)
    assert parse_ref("1 Corinthians 15:12-26") == Ref("1Co", 15, 12, end_verse=26)


def test_continuations_follow_build_js():
    items = parse_refline("Mt 3:17; 4:3, 6; 7:21")
    assert [i.ref for i in items] == [Ref("Mt", 3, 17), Ref("Mt", 4, 3), Ref("Mt", 4, 6), Ref("Mt", 7, 21)]


def test_annotations_and_round_trip():
    items = parse_refline(GTF_LINE)
    assert items[1].notes == ["this one’s subtle"]
    assert items[-1].ref == Ref("Ps", 89, 5, end_verse=7)
    assert [a.kind for a in items[-1].annotations] == ["note", "include"]
    assert render_items(items) == GTF_LINE


def test_book_repeated_after_note():
    items = parse_refline("Heb 1:5–6 ~(cites Ps 2:7)~; Heb 1:8; 3:6")
    assert render_items(items) == "Heb 1:5–6 ~(cites Ps 2:7)~; Heb 1:8; 3:6"


def test_nested_notes_translation_footnote():
    line = "Hab 1:12 KJV; Jn 8:58[^1] ~— *cf. Hab 1:12 ~(see NIV)~; Ro 1:23*~; 2Jn 1:7⁠ff"
    items = parse_refline(line)
    assert items[0].translation == "KJV"
    assert [a.kind for a in items[1].annotations] == ["footnote", "note"]
    assert items[2].annotations[0].kind == "ff"
    assert render_items(items) == line


def test_canonical_rendering_normalizes():
    assert render_items(parse_refline("Isa 51:17; 51:22; Isa 62:4-5")) == "Isa 51:17, 22; 62:4–5"


def test_page_structure():
    text = "---\ncategories:\n- \"[[Paterology]]\"\n---\nIntro.\n### Of Adam\nLk 3:38\n### Of Israel ~(the nation)~\nEx 4:22–23\n"
    page = parse_page(text)
    assert page.frontmatter == {"categories": ["[[Paterology]]"]}
    secs = page.sections()
    assert [(s.heading.title, s.heading.subtitle) for s in secs] == [("Of Adam", None), ("Of Israel", "the nation")]
    assert page.render() == text


def test_unmodified_lines_keep_source():
    page = parse_page("Isa 51:17; 51:22\n")
    assert page.render() == "Isa 51:17; 51:22\n"
    page.lines[0].source = None  # modified → canonical
    assert page.render() == "Isa 51:17, 22\n"
