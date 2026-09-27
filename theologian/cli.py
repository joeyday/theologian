"""Command line entry point: `theo <command> ...`."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

VAULT = Path("/Users/joeyday/Documents/Obsidian/Tota Scriptura")


def _topic_paths(targets: list[str]) -> list[Path]:
    paths: list[Path] = []
    for t in targets or [str(VAULT / "topic")]:
        p = Path(t)
        paths.extend(sorted(p.glob("*.md")) if p.is_dir() else [p])
    return paths


def cmd_lint(args) -> int:
    from .lint import lint_paths

    findings = lint_paths(_topic_paths(args.paths))
    if not args.style:
        shown = [f for f in findings if f.severity == "error"]
    else:
        shown = findings
    for f in shown:
        print(f)
    counts = Counter(f.kind for f in findings)
    print("\n" + ", ".join(f"{k}: {v}" for k, v in counts.most_common()) or "no findings")
    return 1 if any(f.kind == "unexplained" for f in findings) else 0


def _load_candidates(study):
    import json

    path = study.dir / "candidates.json"
    if not path.exists():
        raise SystemExit(f"no candidates yet; run `theo gather {study.slug}`")
    from .gather import Candidate

    return [Candidate(tuple(c["verse"]), c["hits"]) for c in json.loads(path.read_text(encoding="utf-8"))]


def _load_classifications(study) -> dict:
    import json

    path = study.dir / "classifications.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _page(study):
    from .sitemd import load_page

    return load_page(study.page_path) if study.page_path and study.page_path.exists() else None


def cmd_fetch_data(args) -> int:
    from .corpus import fetch_data

    fetch_data(force=args.force)
    return 0


def cmd_gather(args) -> int:
    from collections import Counter

    from . import llm
    from .corpus import load
    from .gather import gather
    from .study import load_study

    study = load_study(args.study)
    cands = gather(load(), study.queries)
    llm.save_json(study.dir / "candidates.json", [{"verse": c.verse, "hits": c.hits} for c in cands])
    per_query = Counter(h.split(": ", 1)[0] for c in cands for h in dict.fromkeys(x.split(": ", 1)[0] + ": " for x in c.hits))
    print(f"{len(cands)} candidate verses → {study.dir / 'candidates.json'}")
    for name, n in per_query.most_common():
        print(f"  {n:5}  {name.rstrip(': ')}")
    return 0


def cmd_classify(args) -> int:
    from . import llm
    from .classify import build_requests, merge_results
    from .corpus import load
    from .esv import ESV, api_key
    from .refs import parse_ref
    from .study import load_study

    study = load_study(args.study)
    cands = _load_candidates(study)
    if args.only:
        wanted = set()
        for r in args.only:
            ref = parse_ref(r)
            wanted |= set(ref.verses(load().verse_counts))
        cands = [c for c in cands if c.verse in wanted]
    if not args.redo:
        done = _load_classifications(study)
        cands = [c for c in cands if c.ref not in done]
    key = api_key()
    esv = ESV(key) if key and not args.bsb and not args.dry_run else None
    reqs = build_requests(study, load(), cands, esv)
    if args.limit:
        reqs = dict(list(reqs.items())[: args.limit])
    model = study.model or llm.DEFAULT_MODEL
    n_verses = sum(r["messages"][0]["content"].count("\n- ") for r in reqs.values())
    tokens, cached = llm.estimate_tokens(reqs)
    out_guess = 900 * len(reqs) + 80 * n_verses  # thinking + JSON, rough
    batch = not args.sync
    est = llm.cost(model, tokens - cached + cached // max(len(reqs), 1), out_guess, cached - cached // max(len(reqs), 1), batch)
    print(f"{len(reqs)} requests covering {len(cands)} candidate verses; model {model}, "
          f"effort {study.effort or llm.DEFAULT_EFFORT}, text {'ESV' if esv else 'BSB'}")
    print(f"estimated ~{tokens:,} input tokens (~{cached:,} cacheable), ~{out_guess:,} output → "
          f"~${est:.2f} {'(batch price)' if batch else ''}")
    if args.dry_run:
        if reqs:
            first = next(iter(reqs.values()))
            print("\n--- system prompt ---\n" + first["system"][0]["text"])
            print("\n--- first request ---\n" + first["messages"][0]["content"][:3000])
        return 0
    if not reqs:
        print("nothing to classify")
        return 0
    if batch:
        batch_id = llm.submit_batch(reqs)
        print(f"submitted batch {batch_id}; waiting (Ctrl-C is safe: resume with `theo collect {study.slug} {batch_id}`)")
        llm.save_json(study.dir / "runs" / f"{batch_id}.json", {"batch": batch_id, "model": model, "requests": list(reqs)})
        results = llm.wait_batch(batch_id)
    else:
        results = llm.run_sync(reqs)
    return _finish(study, results, model)


def _finish(study, results, model) -> int:
    from . import llm
    from .classify import merge_results

    data, errors = merge_results(study, results, model)
    tin = sum(r.input_tokens for r in results)
    tout = sum(r.output_tokens for r in results)
    tcache = sum(r.cache_read_tokens for r in results)
    print(f"done: {len(results) - len(errors)} requests ok, {len(errors)} failed; "
          f"{tin:,} input + {tcache:,} cached + {tout:,} output tokens")
    for e in errors:
        print("  error:", e)
    print(f"{len(data)} verses classified in total → {study.dir / 'classifications.json'}")
    return 1 if errors else 0


def cmd_collect(args) -> int:
    import json

    from . import llm
    from .study import load_study

    study = load_study(args.study)
    run = json.loads((study.dir / "runs" / f"{args.batch}.json").read_text())
    return _finish(study, llm.wait_batch(args.batch), run["model"])


def cmd_audit(args) -> int:
    from .audit import audit, report
    from .corpus import load
    from .study import load_study

    study = load_study(args.study)
    page = _page(study)
    if page is None:
        raise SystemExit(f"{study.slug} has no page to audit")
    cands = {c.verse for c in _load_candidates(study)}
    text = report(study, audit(study, page, load(), cands, _load_classifications(study)))
    out = study.dir / "out" / "audit.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text.split("\n\n")[1])
    print(f"\n→ {out}")
    return 0


def cmd_draft(args) -> int:
    from .corpus import load
    from .render import draft
    from .study import load_study

    study = load_study(args.study)
    page = draft(study, _page(study), load(), _load_classifications(study), args.min_confidence)
    out = study.dir / "out" / "draft.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page.render(), encoding="utf-8")
    print(f"→ {out}")
    return 0


def cmd_propose(args) -> int:
    import yaml

    from . import llm
    from .corpus import load
    from .propose import build_request, run
    from .study import Category, load_study

    study = load_study(args.study)
    cands = _load_candidates(study)
    if args.dry_run:
        p = build_request(study, load(), cands, _page(study))
        tokens, _ = llm.estimate_tokens({"p": p})
        print(f"1 request, ~{tokens:,} input tokens → ~${llm.cost(p['model'], tokens, 8000):.2f}")
        print(p["messages"][0]["content"][:1500])
        return 0
    data = run(study, load(), cands, _page(study))
    out = study.dir / "out" / "proposed-categories.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
    for c in data["categories"]:
        print(f"- {c['name']}: {c['description']}  e.g. {', '.join(c['examples'][:3])}")
    print(f"\n{data['comments']}\n→ {out}")
    if not study.categories or args.apply:
        study.categories = [Category(c["name"], c["description"]) for c in data["categories"]]
        study.save()
        print(f"written into {study.dir / 'study.yaml'}; edit before classifying")
    return 0


def _load_dotenv() -> None:
    """ANTHROPIC_API_KEY / ESV_API_KEY from ./.env, without overriding the environment."""
    import os

    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    ap = argparse.ArgumentParser(prog="theo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lint", help="check topic pages against house style")
    p.add_argument("paths", nargs="*", help="files or folders (default: the vault's topic/ folder)")
    p.add_argument("--style", action="store_true", help="also show cosmetic findings")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("fetch-data", help="download STEPBible and BSB data into data/")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_fetch_data)

    p = sub.add_parser("gather", help="search for candidate verses (no LLM)")
    p.add_argument("study")
    p.set_defaults(func=cmd_gather)

    p = sub.add_parser("propose", help="suggest categories for a new study (one LLM request)")
    p.add_argument("study")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true", help="replace study.yaml categories even if some exist")
    p.set_defaults(func=cmd_propose)

    p = sub.add_parser("classify", help="classify candidates with Claude")
    p.add_argument("study")
    p.add_argument("--dry-run", action="store_true", help="show requests and estimated cost; call nothing")
    p.add_argument("--sync", action="store_true", help="run requests one at a time (default: Batches API, half price)")
    p.add_argument("--limit", type=int, help="only the first N requests (chapters)")
    p.add_argument("--only", nargs="+", metavar="REF", help="only candidates within these refs, e.g. 'Ps 2' 'Mt 5:9'")
    p.add_argument("--redo", action="store_true", help="re-classify verses already classified")
    p.add_argument("--bsb", action="store_true", help="use the BSB text even if an ESV key is set")
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("collect", help="collect results of a batch submitted earlier")
    p.add_argument("study")
    p.add_argument("batch")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("audit", help="compare classifications with the existing page → out/audit.md")
    p.add_argument("study")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("draft", help="existing page + model additions → out/draft.md")
    p.add_argument("study")
    p.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    p.set_defaults(func=cmd_draft)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
