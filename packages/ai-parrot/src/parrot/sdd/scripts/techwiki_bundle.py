"""CLI shim for ``parrot sdd techwiki bundle`` and ``sidebar``."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def _commit(root: Path) -> str | None:
    """Return the current commit SHA when the root is a Git repository."""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def main(argv: Sequence[str] | None = None) -> int:
    """Assemble a publishable technical-wiki bundle.

    Args:
        argv: Optional command-line arguments.

    Returns:
        Zero on success, one for validation errors, two for config errors, or three when griffe is absent.
    """
    parser = argparse.ArgumentParser(description="Assemble a technical-wiki bundle")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--release", type=str, default=None, help="Release tag")
    parser.add_argument("--dry-run", action="store_true", help="Write only techwiki-report.json")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Print JSON report")
    parser.add_argument("--sidebar-only", action="store_true", help="Render Home.md and _Sidebar.md only")
    args = parser.parse_args(argv)

    from parrot.sdd.techwiki.api import GriffeUnavailable
    from parrot.sdd.techwiki.bundle import assemble, write_bundle, write_navigation
    from parrot.sdd.techwiki.config import load_techwiki_config

    try:
        cfg = load_techwiki_config(args.root)
        pages, report = assemble(
            cfg, args.root, release=args.release, commit=_commit(args.root), with_api=not args.sidebar_only
        )
    except GriffeUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "techwiki-report.json").write_text(
            json.dumps(report.__dict__, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    else:
        if args.sidebar_only:
            write_navigation(pages, report, cfg, args.out)
        else:
            write_bundle(pages, report, cfg, args.out)
    if args.as_json:
        print(json.dumps(report.__dict__, sort_keys=True))
    return 0 if report.ok() else 1


if __name__ == "__main__":
    raise SystemExit(main())
