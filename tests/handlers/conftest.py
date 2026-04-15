"""Conftest for handlers tests — worktree sys.path fixup."""
from __future__ import annotations
import sys
from pathlib import Path

_WORKTREE_SRC = Path(__file__).parent.parent.parent / "packages" / "ai-parrot" / "src"
if str(_WORKTREE_SRC) not in sys.path:
    sys.path.insert(0, str(_WORKTREE_SRC))
