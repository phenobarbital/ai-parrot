"""Conftest for helpers tests — ensures worktree src takes precedence."""
from __future__ import annotations

import sys
from pathlib import Path

# The shared venv's editable install points to the main repo's src directory.
# For tests that exercise code created in this worktree, we must prepend the
# worktree's src directory so new modules are found first.
_WORKTREE_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_WORKTREE_SRC) not in sys.path:
    sys.path.insert(0, str(_WORKTREE_SRC))
