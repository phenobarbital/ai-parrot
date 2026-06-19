"""Conftest for graphindex tests.

When running pytest from inside a git worktree, the compiled Cython
extensions (.so files) are absent because they are build artefacts not
tracked by git.  This conftest inserts the main repo's ``src/`` directory
at the FRONT of ``sys.path`` so Python resolves the compiled modules from
there, while still picking up uncompiled Python modules from the worktree.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Main repo src: 7 parents up from this conftest.
# conftest.py:  packages/ai-parrot/tests/knowledge/graphindex/conftest.py
# WT root:      .claude/worktrees/feat-217-graph-expanded-retrieval/
# Main root:    /home/jesuslara/proyectos/ai-parrot/
_this = Path(__file__).resolve()
_wt_root = _this.parents[5]                          # feat-217-... dir
_main_root = _wt_root.parent.parent.parent           # ai-parrot/ main repo
_main_src = _main_root / "packages" / "ai-parrot" / "src"

if _main_src.exists() and str(_main_src) not in sys.path:
    sys.path.insert(0, str(_main_src))
