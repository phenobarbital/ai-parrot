"""Conftest for helpers tests.

Registers new parrot subpackages created in this worktree and patches the
ThemeRegistry class to add list_themes_detailed, which is also added in
the worktree's infographic.py. Avoids overriding the editable install so
that compiled Cython extensions remain importable.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List

_WORKTREE_SRC = Path(__file__).resolve().parents[2] / "src"


def _register_module(dotted_name: str, file_path: Path) -> None:
    """Register a module from file_path under dotted_name in sys.modules."""
    if dotted_name in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(dotted_name, file_path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = module
    spec.loader.exec_module(module)


def _register_package(dotted_name: str, pkg_dir: Path) -> None:
    """Register a package from pkg_dir under dotted_name in sys.modules."""
    if dotted_name in sys.modules:
        return
    init = pkg_dir / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        dotted_name,
        init,
        submodule_search_locations=[str(pkg_dir)],
    )
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    module.__path__ = [str(pkg_dir)]  # type: ignore[attr-defined]
    module.__package__ = dotted_name
    sys.modules[dotted_name] = module
    spec.loader.exec_module(module)


# --- Bootstrap ---------------------------------------------------------------

# Ensure parrot is already loaded from the editable install.
import parrot  # noqa: E402

# Patch ThemeRegistry to add list_themes_detailed (added in worktree's infographic.py)
from parrot.models.infographic import ThemeRegistry  # noqa: E402

if not hasattr(ThemeRegistry, "list_themes_detailed"):
    def list_themes_detailed(self) -> List[Dict[str, str]]:
        """Return theme summaries with key colour tokens.

        Returns:
            List of dicts containing name, primary, neutral_bg, body_bg,
            sorted by name.
        """
        return [
            {
                "name": t.name,
                "primary": t.primary,
                "neutral_bg": t.neutral_bg,
                "body_bg": t.body_bg,
            }
            for t in sorted(self._themes.values(), key=lambda x: x.name)
        ]

    ThemeRegistry.list_themes_detailed = list_themes_detailed  # type: ignore[attr-defined]

# Register parrot.helpers package from worktree src
_helpers_dir = _WORKTREE_SRC / "parrot" / "helpers"
_register_package("parrot.helpers", _helpers_dir)
_register_module("parrot.helpers.infographics", _helpers_dir / "infographics.py")

# Attach to parent package
if not hasattr(parrot, "helpers"):
    parrot.helpers = sys.modules["parrot.helpers"]  # type: ignore[attr-defined]
