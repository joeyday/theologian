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


def test_comments_do_not_break_book_continuation():
    # build.js strips %% comments before linking, so the book carries across them
    from theologian.sitemd import Annotation, Item

    refs = ["Ps 9:7", "Ps 90:2", "Ps 93:2", "Ps 102:24", "Ps 102:27"]
    items = [Item(parse_ref(r), [Annotation("comment", "%% new (high): x %%")]) for r in refs]
    line = render_items(items)
    assert line == ("Ps 9:7%% new (high): x %%; 90:2%% new (high): x %%; 93:2%% new (high): x %%; "
                    "102:24%% new (high): x %%, 27%% new (high): x %%")
    assert [i.ref for i in parse_refline(line)] == [parse_ref(r) for r in refs]
    # ...and deleting the comments leaves the tight form
    assert render_items([Item(i.ref) for i in items]) == "Ps 9:7; 90:2; 93:2; 102:24, 27"


def test_notes_still_break_continuation():
    items = parse_refline("Ps 2:7 ~(cited at Ac 13:33)~; Ps 2:12")
    assert render_items(items) == "Ps 2:7 ~(cited at Ac 13:33)~; Ps 2:12"


def test_comment_spacing():
    import re

    from theologian.sitemd import Annotation, Item

    # new comments attach, so stripping them (as build.js does) leaves clean text
    line = render_items([Item(parse_ref("Ps 9:7"), [Annotation("comment", "%% new: x %%")]), Item(parse_ref("Ps 90:2"))])
    assert re.sub(r"%%[\s\S]*?%%", "", line) == "Ps 9:7; 90:2"
    # a comment written with a space before it keeps it
    src = "Ge 22:17–18 %% probably more? %%; Ex 1:1"
    assert render_items(parse_refline(src)) == src
