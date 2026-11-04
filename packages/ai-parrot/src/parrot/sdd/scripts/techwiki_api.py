"""CLI shim for ``parrot sdd techwiki api``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the Markdown API reference for configured packages.

    Args:
        argv: Optional command-line arguments.

    Returns:
        Zero on success, or the documented configuration/dependency/strict code.
    """
    parser = argparse.ArgumentParser(description="Generate techwiki API reference")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--release", type=str, default=None, help="Release tag for source links")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON report on stdout")
    parser.add_argument("--strict", action="store_true", help="Exit 4 when any module is skipped")
    args = parser.parse_args(argv)

    from parrot.sdd.techwiki.api import GriffeUnavailable, generate
    from parrot.sdd.techwiki.config import load_techwiki_config

    try:
        cfg = load_techwiki_config(args.root)
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    try:
        pages, skipped = generate(cfg, args.root, release=args.release)
    except GriffeUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 3

    args.out.mkdir(parents=True, exist_ok=True)
    for page in pages:
        (args.out / f"{page.module}.md").write_text(page.body, encoding="utf-8")
    report = {"generated": [page.module for page in pages], "skipped_modules": skipped}
    if args.as_json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"Generated {len(pages)} API reference pages")
        for skipped_module in skipped:
            print(f"Skipped {skipped_module['module']}: {skipped_module['reason']}", file=sys.stderr)
    return 4 if args.strict and skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
