"""Brief contract parity across Claude, Codex, and Antigravity."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CLAUDE = _ROOT / ".claude/commands/sdd-brief.md"
_CODEX = _ROOT / ".agents/skills/sdd-brief/SKILL.md"
_AGY = _ROOT / ".agent/workflows/sdd-brief.md"
_SHARED_TOKENS = (
    "--brief-key",
    "parrot sdd run ensure_worktree",
    "Ledger-sourced briefs always base on the configured base_branch; --base-branch <hotfix_base> is refused.",
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


def test_agy_preserves_full_procedure_with_native_handoff() -> None:
    """Only metadata and the two Claude launch examples differ for agy."""
    original = _CLAUDE.read_text(encoding="utf-8")
    expected = original.replace(
        "```bash\ncd <wt> && claude --agent sdd-worker --model sonnet --verbose\n```",
        "```text\nOpen <wt> in agy and ask: Use the sdd-worker subagent to implement <KEY>.\n```",
    ).replace(
        "`cd <wt> && claude --agent sdd-worker --model sonnet --verbose`,",
        "open `<wt>` in agy and ask the `sdd-worker` subagent to implement `<KEY>`,",
    )
    agy = _AGY.read_text(encoding="utf-8")
    assert agy.startswith("---\ndescription:")
    assert agy.split("---\n", 2)[2].lstrip("\n") == expected
    assert "claude --agent" not in agy


def test_codex_handoff_stays_in_codex() -> None:
    """The skill must override the canonical procedure's Claude launch."""
    codex = _CODEX.read_text(encoding="utf-8")
    assert "claude --agent" not in codex
    assert "Use the sdd-worker agent to implement <KEY>." in codex
    assert "$sdd-done <KEY>" in codex
