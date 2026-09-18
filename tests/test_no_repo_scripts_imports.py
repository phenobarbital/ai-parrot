"""Guard: shipped distribution code must never import the repo-local ``scripts`` package.

``scripts/`` (and ``packages/<dist>/scripts/``) only exist in a git checkout —
wheels ship ``src/`` alone. An import of ``scripts.*`` from ``src/`` works in
the repository and raises ``ModuleNotFoundError`` in every installed copy
(ai-parrot 1.0.3: ``wikitoolkit`` crashed at startup on
``scripts.sdd.sdd_meta``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _scripts_imports(path: Path) -> list[str]:
    """Return ``line: module`` entries for every ``scripts`` import in ``path``.

    Args:
        path: Python source file to scan.

    Returns:
        Offending imports, empty when the file is clean.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        found.extend(f"{node.lineno}: {name}" for name in names if name == "scripts" or name.startswith("scripts."))
    return found


def test_distribution_sources_do_not_import_repo_scripts() -> None:
    """No ``packages/*/src`` module imports ``scripts`` (absent from wheels)."""
    sources = sorted(REPO_ROOT.glob("packages/*/src/**/*.py"))
    if not sources:
        pytest.skip("no workspace package sources found")
    offenders = {str(path.relative_to(REPO_ROOT)): hits for path in sources if (hits := _scripts_imports(path))}
    assert not offenders, f"distribution code imports the repo-local scripts package: {offenders}"
