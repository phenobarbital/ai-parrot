"""
Root conftest.py for ai-parrot-integrations tests.

Ensures the worktree's source directories are on sys.path so that
newly-created modules (hitl_adapter.py, graph.py, etc.) are importable
during development — even when the editable install still points to the
main-repo source directory.

The path is prepended (not appended) so worktree code always shadows
the installed copy.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Path to this file's package root (…/ai-parrot-integrations/src)
_PKG_SRC = Path(__file__).parent / "src"
_SRC_STR = str(_PKG_SRC.resolve())

if _SRC_STR not in sys.path:
    sys.path.insert(0, _SRC_STR)
