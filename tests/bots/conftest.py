"""Conftest for bots tests.

Ensures the worktree's source files are imported ahead of the editable-install
pointing to the main repo.  This is necessary because the shared .venv uses
an editable install that resolves to the main-repo source, but we need to test
the changes made in this worktree.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path fixup: worktree source must precede the editable install
# ---------------------------------------------------------------------------
_WORKTREE_SRC = Path(__file__).parent.parent.parent / "packages" / "ai-parrot" / "src"
if str(_WORKTREE_SRC) not in sys.path:
    sys.path.insert(0, str(_WORKTREE_SRC))
