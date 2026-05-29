"""
Root conftest.py for ai-parrot-integrations tests.

Ensures the worktree's source directories are on sys.path so that
newly-created modules (hitl_adapter.py, graph.py, etc.) are importable
during development — even when the editable install still points to the
main-repo source directory.

The path is prepended (not appended) so worktree code always shadows
the installed copy.

Both the ai-parrot-integrations and ai-parrot core worktree sources are
prepended, so that the modified parrot/human/__init__.py (with the
TeamsHumanChannel lazy export) is used in tests rather than the
installed version.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Worktree root is four levels up from this conftest.py:
#   packages/ai-parrot-integrations/conftest.py → worktree root
_WORKTREE_ROOT = Path(__file__).parent.parent.parent

# ai-parrot-integrations source (new HITL modules)
_INTEGRATIONS_SRC = _WORKTREE_ROOT / "packages" / "ai-parrot-integrations" / "src"
# ai-parrot core source (modified parrot/human/__init__.py)
_CORE_SRC = _WORKTREE_ROOT / "packages" / "ai-parrot" / "src"

for _src in (_INTEGRATIONS_SRC, _CORE_SRC):
    _src_str = str(_src.resolve())
    if _src_str not in sys.path:
        sys.path.insert(0, _src_str)
