#!/usr/bin/env python
"""Reconcile dev-loop git worktrees against their PR state.

Webhook-less fallback for dev-loop worktree cleanup. The flow defers worktree
removal to GitHub's ``pull_request.closed`` webhook (see
``parrot.flows.dev_loop.webhook``); when no public endpoint receives that event
(local runs), finished worktrees accumulate. This script does the same job on
demand: it removes worktrees whose PR is already merged or closed, keeps those
with an open PR (the revision loop may still reuse them), and — with
``--remove-orphans`` — also drops abandoned worktrees that never opened a PR.

Usage::

    source .venv/bin/activate
    python scripts/sweep_worktrees.py --dry-run        # preview
    python scripts/sweep_worktrees.py                  # remove merged/closed
    python scripts/sweep_worktrees.py --remove-orphans # also drop no-PR worktrees

Requires the ``gh`` CLI (authenticated) to resolve PR state.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from parrot.flows.dev_loop import sweep_finished_worktrees


async def _amain(args: argparse.Namespace) -> int:
    report = await sweep_finished_worktrees(
        remove_orphans=args.remove_orphans,
        dry_run=args.dry_run,
        cwd=args.cwd,
    )
    verb = "Would remove" if args.dry_run else "Removed"
    for item in report["removed"]:
        print(f"  {verb}: {item['branch']} ({item['reason']})")
    for item in report["kept"]:
        print(f"  Kept:    {item['branch']} ({item['reason']})")
    for item in report["errors"]:
        print(f"  ERROR:   {item['branch']} — {item['error']}", file=sys.stderr)
    print(
        f"\n{verb.lower()} {len(report['removed'])}, "
        f"kept {len(report['kept'])}, errors {len(report['errors'])}."
    )
    return 1 if report["errors"] else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remove-orphans", action="store_true",
        help="Also remove dev-loop worktrees that have no PR.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be removed without touching anything.",
    )
    parser.add_argument(
        "--cwd", default=None,
        help="Repo root for git/gh subprocesses (default: current dir).",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
