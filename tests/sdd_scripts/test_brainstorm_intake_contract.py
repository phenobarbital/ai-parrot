"""Contract: /sdd-brainstorm accepts the /sdd-spec intake hand-off (FEAT-577, spec §4 Module 10)."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FILES = (
    ".claude/commands/sdd-brainstorm.md",
    ".agent/workflows/sdd-brainstorm.md",
    ".agents/skills/sdd-brainstorm/SKILL.md",
)


@pytest.mark.parametrize("rel", _FILES)
def test_brainstorm_accepts_intake_pointer(rel: str) -> None:
    path = _REPO_ROOT / rel
    if not path.is_file():
        pytest.skip(f"{rel} missing at this checkout")
    text = path.read_text(encoding="utf-8")
    assert "intake: <staging-dir>" in text
    assert "intake.json" in text


def test_brainstorm_twins_differ_only_by_worktree_line() -> None:
    """Verify the two command bodies differ only by the worktree-policy line."""
    claude_path = _REPO_ROOT / ".claude/commands/sdd-brainstorm.md"
    agent_path = _REPO_ROOT / ".agent/workflows/sdd-brainstorm.md"

    claude_text = claude_path.read_text(encoding="utf-8")
    agent_text = agent_path.read_text(encoding="utf-8")

    # Normalize the worktree-policy line
    claude_normalized = claude_text.replace(
        'Worktree policy: `CLAUDE.md` (section "Worktree Policy")', "Worktree policy: PLACEHOLDER"
    )
    agent_normalized = agent_text.replace(
        "Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md`", "Worktree policy: PLACEHOLDER"
    )

    # The files should be identical after normalizing the worktree-policy line
    assert claude_normalized == agent_normalized, "Command bodies differ beyond the worktree-policy line"
