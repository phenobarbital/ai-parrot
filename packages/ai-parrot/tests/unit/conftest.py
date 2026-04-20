"""Unit-test conftest: register worktree _crud module as importable stub.

When tests run in a worktree that shares the main-repo venv the installed
``parrot`` package resolves to the main-repo source tree, not the worktree.
Additionally, importing ``parrot.bots.database.toolkits._crud`` triggers the
full ``parrot.bots.__init__`` chain which requires compiled Cython extensions
that are only present in the installed package.

Solution: use ``importlib`` to load ``_crud.py`` and ``_crud_helpers.py``
from the worktree source file path directly, then register them under their
package names so test files can ``import`` them normally.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_TOOLKITS_SRC = (
    Path(__file__).resolve().parents[2]
    / "src" / "parrot" / "bots" / "database" / "toolkits"
)


def _load_module(module_name: str, file_path: Path) -> None:
    """Load *file_path* as *module_name* if not already in sys.modules."""
    if module_name in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]


# Pre-load the worktree version of _crud so that unit tests import it.
# NOTE: _crud.py imports DatabaseToolkit and TableMetadata from the installed
# package — that is fine; only _crud itself needs to be the worktree version.
_load_module(
    "parrot.bots.database.toolkits._crud",
    _TOOLKITS_SRC / "_crud.py",
)
