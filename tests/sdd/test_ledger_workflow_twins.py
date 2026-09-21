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

    def test_read_only_ledger_is_retained_as_an_unfiled_finding(self):
        """Sandboxes may not write the shared ledger, but must preserve the review finding."""
        for path in (self.CLAUDE, self.ANTIGRAVITY, self.CODEX):
            content = read_workflow_file(path)
            assert "shared ledger is read-only" in content, path
            assert "worktree-local ledger" in content, path

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


# --------------------------------------------------------------------------
# TASK-3241 — Start, next, and issue-promotion workflow twins
# --------------------------------------------------------------------------


class TestStartNextTwins:
    START = {
        "claude": ".claude/commands/sdd-start.md",
        "antigravity": ".agent/workflows/sdd-start.md",
        "codex": ".agents/skills/sdd-start/SKILL.md",
    }
    NEXT = {
        "claude": ".claude/commands/sdd-next.md",
        "antigravity": ".agent/workflows/sdd-next.md",
        "codex": ".agents/skills/sdd-next/SKILL.md",
    }
    TASK = {
        "claude": ".claude/commands/sdd-task.md",
        "antigravity": ".agent/workflows/sdd-task.md",
        "codex": ".agents/skills/sdd-task/SKILL.md",
    }

    def test_all_nine_workflow_files_exist(self):
        for group in (self.START, self.NEXT, self.TASK):
            for path in group.values():
                assert (_WORKTREE_ROOT / path).exists(), f"Missing workflow file: {path}"

    def test_start_primes_ledger_context_and_records_task_started(self):
        """Start primes before implementation and records task.started best-effort."""
        for platform, path in self.START.items():
            content = read_workflow_file(path)
            assert "ledger context" in content, (platform, path)
            assert "task.started" in content, (platform, path)

    def test_next_displays_ready_tasks_and_ledger_issues(self):
        """Next displays ready tasks and ledger issues."""
        for platform, path in self.NEXT.items():
            content = read_workflow_file(path)
            assert "ledger ready" in content, (platform, path)
            assert "Ready ledger issues" in content or "ready ledger issues" in content, (platform, path)

    def test_task_promotion_preserves_id_discipline_and_links_source_issue(self):
        """Promotion preserves ID/dependency discipline and links source issue."""
        for platform, path in self.TASK.items():
            content = read_workflow_file(path)
            assert "--from-issue" in content, (platform, path)
            assert "reserve_ids" in content, (platform, path)
            assert "discovered_from" in content, (platform, path)


# --------------------------------------------------------------------------
# FEAT-572 — /sdd-fix twins and /sdd-next retargeting
# --------------------------------------------------------------------------


class TestFixTwins:
    """Mirrors TestCodereviewTwins; asserts the TASK-3394 twin token contract."""

    CLAUDE = ".claude/commands/sdd-fix.md"
    ANTIGRAVITY = ".agent/workflows/sdd-fix.md"
    CODEX = ".agents/skills/sdd-fix/SKILL.md"
    ALL = (CLAUDE, ANTIGRAVITY, CODEX)

    def test_complete_procedure_is_identical_across_hosts(self) -> None:
        """Prevent loss of execution rules when adapting the fix skill for a host."""
        bodies = []
        for path in self.ALL:
            content = read_workflow_file(path)
            if content.startswith("---\n"):
                content = content.split("---\n", 2)[2].lstrip()
            # Host adaptations are limited to the title and skill invocation prefix.
            body = content.split("\n", 1)[1].replace("$sdd-", "/sdd-").strip()
            bodies.append(body)
        assert bodies[0] == bodies[1] == bodies[2]

    def test_workflow_files_exist(self):
        for file_path in self.ALL:
            assert (_WORKTREE_ROOT / file_path).exists(), f"Missing workflow file: {file_path}"

    def test_basic_content_verification(self):
        assert len(read_workflow_file(self.CLAUDE)) > 1000 and "# /sdd-fix" in read_workflow_file(self.CLAUDE)
        assert len(read_workflow_file(self.ANTIGRAVITY)) > 1000 and "# /sdd-fix" in read_workflow_file(self.ANTIGRAVITY)
        assert len(read_workflow_file(self.CODEX)) > 100 and "# SDD Fix" in read_workflow_file(self.CODEX)

    def test_all_twins_call_plan_fix_json(self):
        """Twins INVOKE the plan; they never parse `ledger ready` text (S9)."""
        for path in self.ALL:
            assert "wikitoolkit ledger plan-fix --json" in read_workflow_file(path), path

    def test_all_twins_document_both_lanes(self):
        for path in self.ALL:
            content = read_workflow_file(path)
            assert "Fast lane" in content, path
            assert "SDD lane" in content, path
            assert "--lane" in content, path

    def test_all_twins_require_resolved_by_on_close(self):
        for path in self.ALL:
            content = read_workflow_file(path)
            assert "ledger close" in content, path
            assert "--resolved-by" in content, path
            assert "two keys" in content, path

    def test_all_twins_release_unfixed_issues(self):
        for path in self.ALL:
            content = read_workflow_file(path)
            assert "ledger unclaim" in content, path
            assert "ledger claim" in content, path

    def test_all_twins_require_a_pr_on_the_fast_lane(self):
        for path in self.ALL:
            content = read_workflow_file(path)
            assert "gh pr create --base dev" in content, path
            assert "git push origin dev" not in content, path
            assert "--no-pr" not in content, path

    def test_no_twin_calls_acknowledge(self):
        for path in self.ALL:
            assert "ledger acknowledge" not in read_workflow_file(path), path

    def test_all_twins_reuse_open_parent_or_mint(self):
        for path in self.ALL:
            content = read_workflow_file(path)
            assert "parents" in content, path
            assert "reserve_ids" in content, path
            assert "ensure_worktree" in content, path

    def test_read_only_ledger_exits_without_claiming(self):
        for path in self.ALL:
            content = read_workflow_file(path)
            assert "shared ledger is read-only" in content, path
            assert "ledger context" in content, path
            assert "--max-tokens 3000" in content, path


class TestSddNextRetarget:
    """S9: /sdd-fix replaces --from-issue as the ledger entry point (TASK-3395)."""

    NEXT = TestStartNextTwins.NEXT
    TASK = TestStartNextTwins.TASK

    def test_all_sdd_next_twins_point_at_sdd_fix(self):
        for platform, path in self.NEXT.items():
            content = read_workflow_file(path)
            assert "sdd-fix" in content, (platform, path)
            assert "sdd-task --from-issue" not in content, (platform, path)

    def test_all_sdd_task_twins_carry_from_issue_deprecation(self):
        for platform, path in self.TASK.items():
            content = read_workflow_file(path)
            assert "Deprecated" in content, (platform, path)
            assert "sdd-fix" in content, (platform, path)
            assert "--from-issue" in content, (platform, path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
