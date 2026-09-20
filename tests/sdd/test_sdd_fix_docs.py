"""Docs parity for /sdd-fix (FEAT-572): the three SDD command tables list it and the lane section names both lanes."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/sdd/ → repo root; never the CWD
_TABLES = ("docs/sdd/WORKFLOW.md", "docs/sdd/PLATFORM.md", "sdd/WORKFLOW.md")


@pytest.mark.parametrize("rel", _TABLES)
def test_command_table_lists_sdd_fix(rel: str) -> None:
    content = (_REPO_ROOT / rel).read_text(encoding="utf-8")
    assert "`/sdd-fix" in content, rel


def test_workflow_doc_has_fix_lane_section() -> None:
    content = (_REPO_ROOT / "docs/sdd/WORKFLOW.md").read_text(encoding="utf-8")
    assert "## Ledger-Driven Fix Lane" in content
    assert "Fast lane" in content
    assert "SDD lane" in content
    assert "plan-fix --json" in content
    assert "gh pr create --base dev" in content
