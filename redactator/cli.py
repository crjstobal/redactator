"""Command line.

    redactator FILE... [--hide names,emails,...] [--also "9256YT, Acme"] [--keep "my studio"] [-o OUT] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys

from . import brain, engine, ner
from .categories import CATEGORIES, DEFAULT_HIDE, Options, split_list


def main(argv=None) -> int:
    choices = ", ".join(f"{c.id} ({c.title})" for c in CATEGORIES.values())
    ap = argparse.ArgumentParser(prog="redactator", description="Hide personal data in photos, PDFs and videos, locally.")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--hide", default=",".join(DEFAULT_HIDE), help=f"comma-separated categories, or 'all'. Available: {choices}")
    ap.add_argument("--also", default="", help='exact text or short descriptions to hide too, e.g. "9256YT, my client\'s company"')
    ap.add_argument("--keep", default="", help="text that must stay visible, e.g. your own studio name")
    ap.add_argument("-o", "--output", help="output path (single file only)")
    ap.add_argument("--dry-run", action="store_true", help="list findings without writing anything")
    args = ap.parse_args(argv)

    hide = list(CATEGORIES) if args.hide.strip() == "all" else split_list(args.hide)
    unknown = [h for h in hide if h not in CATEGORIES]
    if unknown:
        ap.error(f"unknown categories: {', '.join(unknown)}. Available: {choices}")
    options = Options(hide=hide, also=split_list(args.also), keep=split_list(args.keep))

    if not brain.available():
        print(f"! {brain.MODEL} is not available in Ollama: Gemma will not read the text.", file=sys.stderr)
    log = lambda msg: print(f"  {msg}", file=sys.stderr)
    for path in args.files:
        print(f"> {path}")
        plan = engine.analyse(path, options, log)
        for f in plan.findings:
            print(f"  {f.label:24} x{f.count:<4} {f.text:40} [{f.source}]")
        if not plan.findings:
            print("  nothing to hide")
        if args.dry_run:
            continue
        out = engine.export(plan, args.output if len(args.files) == 1 else None, log)
        print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
