"""Load scope grids from workspace and package-bundled YAML files (FEAT-890 M5)."""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import Final

import yaml

from parrot.experts.grid.models import ScopeGrid, ScopeGridError, ScopeGridErrorCode

BUNDLED_SCOPES_DIR: Final[Path] = Path(str(importlib.resources.files("parrot.experts.bundled"))) / "scopes"


def _load_directory(directory: Path) -> dict[str, ScopeGrid]:
    """Load every YAML scope grid directly below a directory."""
    scopes: dict[str, ScopeGrid] = {}
    if not directory.is_dir():
        return scopes
    for path in sorted((*directory.glob("*.yaml"), *directory.glob("*.yml"))):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            grid = ScopeGrid.model_validate(data)
        except Exception as exc:
            raise ScopeGridError(ScopeGridErrorCode.INVALID, f"{path}: {exc}") from exc
        if grid.scope in scopes:
            raise ScopeGridError(ScopeGridErrorCode.INVALID, f"duplicate scope {grid.scope!r} in {directory}")
        scopes[grid.scope] = grid
    return scopes


def load_scopes(agents_dir: Path | None, *, bundled_dir: Path = BUNDLED_SCOPES_DIR) -> dict[str, ScopeGrid]:
    """Load bundled scopes overlaid by workspace scopes with the same name.

    Args:
        agents_dir: Workspace agents directory or ``None``.
        bundled_dir: Package directory containing bundled scope YAML files.

    Returns:
        Scope grids keyed by scope name, with workspace definitions taking precedence.
    """
    scopes = _load_directory(bundled_dir)
    if agents_dir is not None:
        scopes.update(_load_directory(Path(agents_dir) / "experts" / "scopes"))
    return scopes
