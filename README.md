# theologian

A local pipeline for building and checking [Tota Scriptura](https://totascriptura.org) topic pages:
exhaustive, categorized lists of every passage on a theme.

Code does the searching, bookkeeping, and page formatting. Claude is used only to classify each
candidate verse, judged blind against the study's categories. **The vault page is the record of
your decisions.** The tool never writes to the vault; it produces a draft and an audit report for
you to act on.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/theo fetch-data            # STEPBible tagged Hebrew/Greek (CC BY) + Berean Standard Bible (public domain)
```

Create `.env` (git-ignored):

```
ANTHROPIC_API_KEY=sk-ant-...
ESV_API_KEY=...        # optional; without it the classifier reads the BSB
```

## Workflow

A study lives in `studies/<slug>/study.yaml`: title, intro, inclusion criteria, search queries
(Strong's numbers and/or English regexes), and categories. See `theologian/study.py` and
`theologian/gather.py` for the format.

```sh
theo gather eternal                  # candidate verses (no LLM) → candidates.json
theo propose eternal                 # new study: suggest categories (1 request), then edit study.yaml
theo classify eternal --dry-run      # see prompts and estimated cost
theo classify eternal --only 'Ps 90' --sync   # try a chapter or two first
theo classify eternal                # everything, via the Batches API (half price, can take up to an hour)
theo draft eternal                   # page + additions → out/draft.md
theo audit god-the-father            # compare with an existing page → out/audit.md
theo lint                            # check every topic page against house style
```

In `out/draft.md`, additions carry `%% new (confidence): rationale %%`. Obsidian shows these;
the site build strips them. Review them, then paste into the vault. Passages you reject go in
`studies/<slug>/decisions.yaml` so they stop being suggested:

```yaml
exclude:
  - ref: Mt 5:1
    reason: not about God's fatherhood
```

## Pieces

| module | does |
|---|---|
| `refs.py` | scripture references, house abbreviations, OSIS |
| `sitemd.py` | page ⇄ structure ("AST"): frontmatter, headings, ref lines, notes; renders back byte-for-byte |
| `lint.py` | house style and site-linking checks for every topic page |
| `corpus.py` | STEPBible + BSB loaded and indexed by verse (English/ESV versification) |
| `gather.py` | candidate search by Strong's number / English, with proximity conditions |
| `esv.py` | ESV API client within Crossway's limits (≤500 verses cached, ≤60 requests/min) |
| `classify.py`, `llm.py` | per-chapter classification requests, sync or batch |
| `audit.py`, `render.py`, `propose.py` | audit report, draft page, category proposal |
