"""Contract guards for .claude/commands/sdd-brief.md — FEAT-698 / TASK-4429."""

from __future__ import annotations

from pathlib import Path

_DOC = Path(__file__).resolve().parents[2] / ".claude/commands/sdd-brief.md"


def _text() -> str:
    """Return the command procedure under test."""
    return _DOC.read_text(encoding="utf-8")


def test_provisions_through_ensure_worktree_brief_key() -> None:
    """The brief lane provisions through the shared brief-key CLI."""
    text = _text()
    assert "parrot sdd run ensure_worktree" in text
    assert "--brief-key <KEY>" in text


def test_ledger_main_refusal_text_present() -> None:
    """Ledger briefs must retain their non-main base refusal."""
    assert "⚠️  Ledger-sourced briefs always base on the configured base_branch; --base-branch <hotfix_base> is refused." in _text()


def test_research_floor_stated() -> None:
    """Research evidence is required before provisioning a worktree."""
    text = _text()
    floor_index = text.index("### 6. Enforce the Research Floor")
    provision_index = text.index("### 9. Provision the Worktree")
    floor = text[floor_index:provision_index]
    assert "path:line" in floor
    assert "refuse to create the worktree" in floor


def test_never_reserves_ids() -> None:
    """The only reserve_ids reference is the explicit guardrail prohibition."""
    lines = [line.strip() for line in _text().splitlines() if "reserve_ids" in line]
    assert lines == ["- Never call `reserve_ids.py`; brief task IDs are local `HOTFIX-<KEY>-<N>` IDs."]


def test_never_hand_rolls_worktree() -> None:
    """The procedure delegates worktree creation to the shared CLI."""
    assert "git worktree add" not in _text()
