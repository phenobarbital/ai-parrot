"""CLI shim for ``parrot sdd techwiki check``."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Report a spec's declared documentation pages (never blocking).

    Exit codes:
        0: ok, warning, or skipped
        2: invalid or usage error
    By construction there is no blocking exit code.

    Args:
        argv: Optional command-line arguments.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description="Check spec documentation pages")
    parser.add_argument("--spec", type=Path, required=True, help="Path to spec file")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
    # No --force argument (AC-7)
    args = parser.parse_args(argv)

    if not args.spec.exists():
        print(f"Spec not found: {args.spec}", file=sys.stderr)
        return 2

    from parrot.sdd.techwiki.check import evaluate_docs, resolve_docs_policy

    policy, pages, api_modules = resolve_docs_policy(args.spec)
    decision = evaluate_docs(policy, pages, api_modules, args.root)

    if args.as_json:
        print(json.dumps(asdict(decision)))
    else:
        print(f"Docs: {decision.policy} — {decision.status}")
        if decision.missing:
            print(f"  missing: {', '.join(decision.missing)}")
        if decision.reason_codes:
            print(f"  reasons: {', '.join(decision.reason_codes)}")

    return 2 if decision.status == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
