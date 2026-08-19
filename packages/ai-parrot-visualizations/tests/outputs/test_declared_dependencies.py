"""Guard tests: the infographic renderer's third-party imports are declared.

``infographic_html.py`` imports ``markdown_it``, ``orjson`` and ``markupsafe``
at module scope, so they must be hard dependencies of this distribution rather
than accidental transitive installs (FEAT-301, TASK-2258).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
REQUIRED = ("markdown-it-py", "markupsafe", "orjson")


def _declared() -> list[str]:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["project"]["dependencies"]


@pytest.mark.parametrize("name", REQUIRED)
def test_dependency_declared(name: str) -> None:
    """Each import-time dependency is declared in [project] dependencies."""
    declared = " ".join(_declared()).lower()
    assert name in declared


def test_ai_parrot_dependency_preserved() -> None:
    assert any(dep.startswith("ai-parrot>=") for dep in _declared())


def test_imports_resolve() -> None:
    """The declared distributions provide the modules the renderer imports."""
    import markdown_it  # noqa: F401
    import markupsafe  # noqa: F401
    import orjson  # noqa: F401


def test_renderer_imports_cleanly() -> None:
    from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer

    assert InfographicHTMLRenderer is not None
