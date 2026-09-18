"""Guard tests for FEAT-573 TASK-3399: Textual is a declared core dependency and FEAT-519 is superseded."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest  # verified: packages/ai-parrot/tests/cli/test_integration.py:14

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PYPROJECT = _REPO_ROOT / "packages" / "ai-parrot" / "pyproject.toml"
_FEAT519 = _REPO_ROOT / "sdd" / "specs" / "new-cli-infra.spec.md"


def test_textual_is_declared_in_core_dependencies() -> None:
    """The exact bound from spec §7 is present in the core dependency list."""
    text = _PYPROJECT.read_text(encoding="utf-8")
    assert '"textual>=8.2,<9",' in text
    # Assert the declaration sits BEFORE the first `[project.optional-dependencies]`
    # header (i.e. in core, not in an extra) — bounded by spec §7 "core, not an extra".
    dependency_index = text.index('"textual>=8.2,<9",')
    optional_dependencies_index = text.index("[project.optional-dependencies]")
    assert dependency_index < optional_dependencies_index


def test_textual_is_importable() -> None:
    """After `uv lock` + install, the module resolves in the active environment."""
    assert importlib.util.find_spec("textual") is not None


@pytest.mark.parametrize("marker", ["superseded by FEAT-573", "sdd/specs/new-ui-cli-agents.spec.md"])
def test_feat519_status_is_superseded(marker: str) -> None:
    """AC24: the FEAT-519 status line points at FEAT-573."""
    status_lines = [ln for ln in _FEAT519.read_text(encoding="utf-8").splitlines() if ln.startswith("**Status**:")]
    assert status_lines, "FEAT-519 spec has no **Status** line"
    assert marker in status_lines[0]
    assert "draft" not in status_lines[0]
