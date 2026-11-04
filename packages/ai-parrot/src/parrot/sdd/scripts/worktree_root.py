"""Print the resolved SDD worktree root for a primary checkout (FEAT-802).

Read-only: never creates directories, never changes the working directory, never loads
``parrot.conf``. Shell workflows capture its stdout:
``WORKTREES_DIR=$(parrot sdd worktree root --root "$MAIN_ROOT") || exit $?``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from parrot.sdd.config import worktree_root


def main(argv: Sequence[str] | None = None) -> int:
    """Print ``worktree_root(--root)`` and exit 0; argparse usage errors exit 2."""
    parser = argparse.ArgumentParser(prog="parrot sdd worktree root", description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, type=Path, help="The primary checkout of the repository.")
    args = parser.parse_args(argv)
    sys.stdout.write(f"{worktree_root(args.root)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
