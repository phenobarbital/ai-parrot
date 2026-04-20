"""Root conftest.py for the feat-107 worktree.

Ensures the worktree's package sources take precedence over the main-repo
editable installs registered via .pth files in site-packages.  Without this,
pytest would silently import from the main-repo sources, making FEAT-107
changes invisible to tests.
"""
import sys
import os

# Worktree root — the directory that contains THIS file.
_WORKTREE_ROOT = os.path.dirname(os.path.abspath(__file__))

# Prepend the worktree package src directories so they shadow the main-repo
# editable-install .pth entries.
_EXTRA_PATHS = [
    # Only prepend ai-parrot-tools so the worktree's navigator/toolkit.py is used.
    # The parrot core package (ai-parrot) is loaded from the main-repo editable
    # install to avoid version-mismatch errors (the worktree parrot package may
    # have a different internal layout than the installed version).
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot-tools", "src"),
]
for _p in reversed(_EXTRA_PATHS):
    if _p not in sys.path:
        sys.path.insert(0, _p)
