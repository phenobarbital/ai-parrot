"""Tests for semantic parity across SDD workflow twins (Claude, Codex, Antigravity).

Verifies equivalent fields and procedures for ledger integration across the
Module 12 workflow touchpoints. This file is jointly owned/appended-to by
TASK-3240 (codereview twins), TASK-3241 (start/next/promotion twins), and
TASK-3242 (done twins) — each owns its own test class below; none replaces
another's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Resolved from this file's own location, NOT process CWD: importing certain
# parrot modules (navconfig-based settings init, pulled in transitively
# during test collection) chdir()s the process to the MAIN checkout as a
# side effect (see mcp_server.py's `_INVOCATION_CWD` comment for the same
# gotcha). A bare relative path like ".claude/commands/sdd-done.md" would
# then silently resolve against the main checkout instead of this worktree,
# reading stale content without ever failing loudly.
_WORKTREE_ROOT = Path(__file__).resolve().parents[2]


def read_workflow_file(path: str) -> str:
    """Read a workflow file (path relative to the worktree root) and return its content."""
    file_path = _WORKTREE_ROOT / path
    if not file_path.exists():
        pytest.fail(f"Workflow file not found: {file_path}")
    return file_path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# TASK-3240 — Deferred findings in codereview twins
# --------------------------------------------------------------------------


class TestCodereviewTwins:
    CLAUDE = ".claude/commands/sdd-codereview.md"
    ANTIGRAVITY = ".agent/workflows/sdd-codereview.md"
    CODEX = ".agents/skills/sdd-codereview/SKILL.md"

    def test_workflow_files_exist(self):
        for file_path in (self.CLAUDE, self.ANTIGRAVITY, self.CODEX):
            assert (_WORKTREE_ROOT / file_path).exists(), f"Missing workflow file: {file_path}"

    def test_basic_content_verification(self):
        claude_content = read_workflow_file(self.CLAUDE)
        antigravity_content = read_workflow_file(self.ANTIGRAVITY)
        codex_content = read_workflow_file(self.CODEX)

        assert len(claude_content) > 1000, "Claude file appears too short"
        assert len(antigravity_content) > 1000, "Antigravity file appears too short"
        assert len(codex_content) > 100, "Codex file appears too short"

        assert "# /sdd-codereview" in claude_content
        assert "# /sdd-codereview" in antigravity_content
        assert "# SDD Code Review" in codex_content

    def test_deferred_findings_table_and_ledger_open_mandated_on_every_twin(self):
        """Every twin mandates durable filing of out-of-scope major/critical findings."""
        for path in (self.CLAUDE, self.ANTIGRAVITY, self.CODEX):
            content = read_workflow_file(path)
            assert "Deferred" in content and "findings" in content.lower(), path
            assert "ledger open" in content, path

    def test_no_findings_outcome_is_explicit(self):
        """A clean review (no deferred findings) has an explicit row/outcome, not silence."""
        for path in (self.CLAUDE, self.ANTIGRAVITY):
            content = read_workflow_file(path)
            assert "Deferred findings table" in content


# --------------------------------------------------------------------------
# TASK-3242 — Done merge gate and base-branch ledger snapshot twins
# --------------------------------------------------------------------------


class TestDoneTwins:
    CLAUDE = ".claude/commands/sdd-done.md"
    ANTIGRAVITY = ".agent/workflows/sdd-done.md"
    CODEX = ".agents/skills/sdd-done/SKILL.md"

    def test_workflow_files_exist(self):
        for file_path in (self.CLAUDE, self.ANTIGRAVITY, self.CODEX):
            assert (_WORKTREE_ROOT / file_path).exists(), f"Missing workflow file: {file_path}"

    def test_basic_content_verification(self):
        claude_content = read_workflow_file(self.CLAUDE)
        antigravity_content = read_workflow_file(self.ANTIGRAVITY)
        codex_content = read_workflow_file(self.CODEX)

        assert len(claude_content) > 1000, "Claude file appears too short"
        assert len(antigravity_content) > 1000, "Antigravity file appears too short"
        assert len(codex_content) > 100, "Codex file appears too short"

        assert "# /sdd-done" in claude_content or "Verify, Check Blockers, Snapshot, Push" in claude_content
        assert "# /sdd-done" in antigravity_content or "Verify, Check Blockers, Snapshot, Push" in antigravity_content
        assert (
            "# SDD Done" in codex_content
            or "Verify a completed SDD feature worktree, check for merge blockers" in codex_content
        )

    def test_merge_gate_scopes_blockers_to_current_feature(self):
        """`wikitoolkit ledger blockers <FEAT-ID>` gates --merge, scoped to this feature."""
        for path in (self.CLAUDE, self.ANTIGRAVITY, self.CODEX):
            content = read_workflow_file(path)
            assert "ledger blockers" in content, path

    def test_snapshot_uses_throwaway_worktree_and_excludes_hotfix(self):
        """Snapshot runs from a throwaway base-branch worktree; hotfixes skip it."""
        for path in (self.CLAUDE, self.ANTIGRAVITY, self.CODEX):
            content = read_workflow_file(path)
            assert "ledger export" in content, path
            assert "hotfix" in content.lower(), path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
