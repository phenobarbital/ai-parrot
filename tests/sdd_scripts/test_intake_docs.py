"""Contract: sdd/WORKFLOW.md documents /sdd-spec intake mode (FEAT-577)."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_workflow_documents_intake_mode() -> None:
    text = (_REPO_ROOT / "sdd" / "WORKFLOW.md").read_text(encoding="utf-8")
    assert "intake mode" in text
    assert "sdd/templates/intake.procedure.md" in text
    for flag in ("--interview", "--no-interview", "--research"):
        assert flag in text

    # Assert the section precedes "## Commands Reference"
    intake_idx = text.index("## Starting from an interview: `/sdd-spec` intake mode (FEAT-577)")
    commands_idx = text.index("## Commands Reference")
    assert intake_idx < commands_idx
