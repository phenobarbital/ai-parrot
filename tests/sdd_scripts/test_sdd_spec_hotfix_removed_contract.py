"""/sdd-spec no longer scaffolds hotfixes — FEAT-698 / TASK-4436."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_FILES = (".claude/commands/sdd-spec.md", ".agent/workflows/sdd-spec.md", ".agents/skills/sdd-spec/SKILL.md")
_REFUSAL = "⚠️  /sdd-spec no longer scaffolds hotfixes — use /sdd-brief <source> (FEAT-698)."


def _read(rel: str) -> str:
    """Read a repo-relative file as UTF-8 text."""
    return (_ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", _FILES)
def test_no_hotfix_type_flag(rel: str) -> None:
    """AC-1: the usage line no longer offers ``--type hotfix``."""
    assert "feature|hotfix" not in _read(rel)


@pytest.mark.parametrize("rel", _FILES)
def test_refusal_points_at_sdd_brief(rel: str) -> None:
    """AC-2: an explicit hotfix request aborts with the exact /sdd-brief pointer."""
    assert _REFUSAL in _read(rel)


@pytest.mark.parametrize("rel", _FILES)
def test_hotfix_output_block_removed(rel: str) -> None:
    """AC-1: no ``TYPE == "hotfix"`` branch survives in the command twins."""
    assert 'TYPE == "hotfix"' not in _read(rel)


def test_codex_doc_examples_use_sdd_brief() -> None:
    """AC-3: CODEX.md teaches ``$sdd-brief`` instead of ``--type hotfix``."""
    text = _read("docs/sdd/CODEX.md")
    assert "--type hotfix" not in text
    assert "$sdd-brief" in text
