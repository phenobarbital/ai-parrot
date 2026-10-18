"""Policy docs match the FEAT-698 PR rule — TASK-4437."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DOCS = ("CLAUDE.md", "docs/sdd/WORKFLOW.md", "sdd/WORKFLOW.md", ".claude/rules/worktree-management.md")


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", _DOCS)
def test_old_rule_gone(rel: str) -> None:
    assert "opens a PR against `main`" not in _read(rel)


@pytest.mark.parametrize("rel", _DOCS)
def test_docs_state_never_merges_into_main(rel: str) -> None:
    assert "merges into `main`" in _read(rel) or "merge into `main`" in _read(rel)


def test_claude_md_lists_sdd_brief_in_auto_commit_table() -> None:
    rows = [line for line in _read("CLAUDE.md").splitlines() if line.startswith("| `/sdd-brief`")]
    assert len(rows) == 1
    assert "inside the worktree" in rows[0]


def test_workflow_commands_table_has_sdd_brief() -> None:
    rows = [line for line in _read("docs/sdd/WORKFLOW.md").splitlines() if line.startswith("| `/sdd-brief")]
    assert rows


def test_worktree_rule_documents_brief_key() -> None:
    text = _read(".claude/rules/worktree-management.md")
    assert "--brief-key" in text
    assert "clears the auto-set upstream" in text


@pytest.mark.parametrize("rel", _DOCS)
def test_no_sdd_spec_type_hotfix_instruction(rel: str) -> None:
    text = _read(rel)
    assert "/sdd-spec --type hotfix" not in text
    assert "type: hotfix" not in text or rel == "sdd/WORKFLOW.md"
