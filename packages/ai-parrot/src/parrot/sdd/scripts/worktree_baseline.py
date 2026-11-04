"""Runnable baseline checkout of a base ref, with the compiled extensions in place.

Agents that need to know whether a failure "already happened on dev" used to
improvise a baseline (``git archive``, ``git worktree add --detach``, ``git show``).
Such a tree carries no gitignored ``.so`` files, so ``import parrot`` fails on
``parrot.utils.types`` and the agent ends up hand-copying artifacts — possibly
built for another interpreter. This command is the one sanctioned way to get a
baseline tree: it wraps the FEAT-699 ``prepare_baseline_checkout`` (detached
worktree + ``sync_native_artifacts``) and its cleanup.

Usage::

    parrot sdd worktree baseline create --base origin/dev   # prints the checkout path
    parrot sdd worktree baseline remove <path>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence

_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "flows" / "dev_loop"


def _load_baseline() -> ModuleType:
    """Import the stdlib ``test_scope.baseline`` kernel by path (never ``import parrot``).

    Loaded the same way as ``select_tests`` so the command works even when the
    Cython ``parrot.utils.types`` artifact it exists to provide is missing.
    """
    if str(_KERNEL_PARENT) not in sys.path:
        sys.path.insert(0, str(_KERNEL_PARENT))
    import test_scope.baseline as baseline_mod  # noqa: PLC0415 — path-dependent import

    return baseline_mod


def _repo_root(cwd: Path) -> Path:
    """Return the top level of the git checkout containing ``cwd``."""
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=str(cwd), capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(f"error: {cwd} is not inside a git checkout: {proc.stderr.strip()}")
    return Path(proc.stdout.strip())


def _default_scratch(worktree: Path, baseline_mod: ModuleType) -> Path:
    """``<main checkout>/.claude/worktrees`` — writable from inside the SDD sandbox and persistent.

    ``/tmp`` is private per command under Bubblewrap, so a baseline created there
    would vanish while its git worktree registration stayed behind.
    """
    main_root = baseline_mod._native_artifacts().main_checkout_root(worktree) or worktree
    return main_root / ".claude" / "worktrees"


def _create(args: argparse.Namespace) -> int:
    baseline_mod = _load_baseline()
    worktree = _repo_root(Path(args.worktree).resolve())
    scratch = Path(args.scratch).resolve() if args.scratch else _default_scratch(worktree, baseline_mod)
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        path = baseline_mod.prepare_baseline_checkout(worktree=worktree, base_ref=args.base, scratch=scratch)
    except baseline_mod.BaselineUnavailable as exc:
        print(f"error: baseline unavailable: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"path": str(path), "base": args.base}))
    else:
        print(path)
    return 0


def _remove(args: argparse.Namespace) -> int:
    baseline_mod = _load_baseline()
    worktree = _repo_root(Path(args.worktree).resolve())
    path = Path(args.path).resolve()
    if not path.name.startswith("baseline-"):
        print(f"error: {path} is not a baseline checkout (expected a 'baseline-<sha>' directory)", file=sys.stderr)
        return 2
    baseline_mod.remove_baseline_checkout(worktree, path)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or remove a runnable baseline checkout of a base ref (compiled extensions included)."
    )
    sub = parser.add_subparsers(dest="action", required=True)

    create = sub.add_parser("create", help="Detached checkout of --base with native artifacts synced; prints its path.")
    create.add_argument("--base", required=True, help="Base ref, e.g. origin/dev.")
    create.add_argument("--worktree", default=".", help="Any checkout of the repository (default: cwd).")
    create.add_argument(
        "--scratch", default=None, help="Parent directory for the checkout (default: <main>/.claude/worktrees)."
    )
    create.add_argument("--json", action="store_true", help="Machine-readable output.")
    create.set_defaults(func=_create)

    remove = sub.add_parser("remove", help="Remove a checkout created by 'create'.")
    remove.add_argument("path", help="Path printed by 'create'.")
    remove.add_argument("--worktree", default=".", help="Any checkout of the repository (default: cwd).")
    remove.set_defaults(func=_remove)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
