"""Twin parity: .agents/skills/sdd-brief mirrors .claude/commands/sdd-brief.md — FEAT-698 / TASK-4430."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CLAUDE = _ROOT / ".claude/commands/sdd-brief.md"
_CODEX = _ROOT / ".agents/skills/sdd-brief/SKILL.md"
_SHARED_TOKENS = (
    "--brief-key",
    "scripts.sdd.ensure_worktree",
    "Ledger-sourced briefs always base on dev; --base-branch main is refused.",
    "path:line",
)


def test_frontmatter_name_is_sdd_brief() -> None:
    lines = _CODEX.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    assert "name: sdd-brief" in lines[1:4]


def test_shared_tokens_in_both_twins() -> None:
    claude = _CLAUDE.read_text(encoding="utf-8")
    codex = _CODEX.read_text(encoding="utf-8")
    for token in _SHARED_TOKENS:
        assert token in claude, token
        assert token in codex, token


def test_twin_has_no_manual_worktree_or_id_reservation() -> None:
    codex = _CODEX.read_text(encoding="utf-8")
    assert "git worktree add" not in codex
    assert "reserve_ids" not in codex
