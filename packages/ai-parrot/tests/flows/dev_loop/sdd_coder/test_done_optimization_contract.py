"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

from __future__ import annotations

from pathlib import Path

import pytest

_BOUNDARY_HEADING = "## Durable review boundary (FEAT-584)"

_REVIEW_TWINS = (
    ".claude/commands/sdd-codereview.md",
    ".agent/workflows/sdd-codereview.md",
    ".agents/skills/sdd-codereview/SKILL.md",
)

_DONE_TWINS = (
    ".claude/commands/sdd-done.md",
    ".agent/workflows/sdd-done.md",
    ".agents/skills/sdd-done/SKILL.md",
)

_ALL_TWINS = _REVIEW_TWINS + _DONE_TWINS

_ANCHOR_MARKER = {
    ".claude/commands/sdd-codereview.md": "### 1. Resolve the Task File",
    ".agent/workflows/sdd-codereview.md": "### 1. Resolve the Task File",
    ".agents/skills/sdd-codereview/SKILL.md": "1. Resolve task:",
    ".claude/commands/sdd-done.md": "### 1. Verify We're on the Base Branch (FEAT-145)",
    ".agent/workflows/sdd-done.md": "### 1. Verify We're on the Base Branch (FEAT-145)",
    ".agents/skills/sdd-done/SKILL.md": "1. Resolve feature:",
}


def _repo_root() -> Path:
    """Walk up from this test file to the repo root that owns `.claude/agents/`."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".claude" / "agents").is_dir():
            return parent
    raise AssertionError("repo root (containing .claude/agents/) not found relative to this test file")


def test_review_variants_validate_checkpoint(tmp_path: Path) -> None:
    """Review twins require valid neutral evidence and fresh independent reviewer."""
    repo_root = _repo_root()

    for rel_path in _REVIEW_TWINS:
        body = (repo_root / rel_path).read_text(encoding="utf-8")
        assert _BOUNDARY_HEADING in body, f"{rel_path} is missing the durable review boundary block"

        section = body.split(_BOUNDARY_HEADING, 1)[1]
        for marker in (
            "settle owned attempts and supervised validations and close execution",
            "Unknown activity is a blocker",
            "Persist the checkpoint",
            "revalidate and start\na fresh reviewer",
            "Unsupported contexts continue from checkpoint with an explicit reason",
            "Changes after checkpoint require new hashes/evidence and invalidate old review coverage",
        ):
            assert marker in section, f"{rel_path} boundary block is missing {marker!r}"

        # AC9/AC17: the boundary block augments the existing steps/workflow -- it must
        # land right after the section heading and never displace the first real step.
        anchor = _ANCHOR_MARKER[rel_path]
        assert body.index(_BOUNDARY_HEADING) < body.index(
            anchor
        ), f"{rel_path}: durable review boundary block must precede {anchor!r}"

    # Existing review criteria, adversarial cross-check and ledger gates are preserved,
    # not relaxed, by the new boundary block (task title: "sin relajar gates").
    codereview_command = (repo_root / ".claude/commands/sdd-codereview.md").read_text(encoding="utf-8")
    assert "Run Adversarial Cross-Check" in codereview_command
    assert "codex" in codereview_command
    assert "Deferred Findings" in codereview_command
    assert "wikitoolkit ledger open" in codereview_command

    codereview_workflow = (repo_root / ".agent/workflows/sdd-codereview.md").read_text(encoding="utf-8")
    assert "Adversarial cross-check" in codereview_workflow or "Adversarial Cross-Check" in codereview_workflow

    codereview_skill = (repo_root / ".agents/skills/sdd-codereview/SKILL.md").read_text(encoding="utf-8")
    assert "Adversarial cross-check" in codereview_skill


def test_done_variants_keep_release_gates(tmp_path: Path) -> None:
    """Done twins preserve verification/ledger/release gates and prohibit cleanup of unknown work."""
    repo_root = _repo_root()

    for rel_path in _DONE_TWINS:
        body = (repo_root / rel_path).read_text(encoding="utf-8")
        assert _BOUNDARY_HEADING in body, f"{rel_path} is missing the durable review boundary block"

        section = body.split(_BOUNDARY_HEADING, 1)[1]
        for marker in (
            "For sdd-done, preserve existing verification stamping, approval and push/merge policy",
            "do not run task closure again on base_branch",
            "do not clean worktrees with unknown activity",
        ):
            assert marker in section, f"{rel_path} boundary block is missing {marker!r}"

        anchor = _ANCHOR_MARKER[rel_path]
        assert body.index(_BOUNDARY_HEADING) < body.index(
            anchor
        ), f"{rel_path}: durable review boundary block must precede {anchor!r}"

    # Existing verification stamping, blocker checks and push/merge/hotfix policy stay
    # intact -- the boundary block is a preface, never a rewrite of these steps.
    done_command = (repo_root / ".claude/commands/sdd-done.md").read_text(encoding="utf-8")
    assert "Stamp Verification" in done_command or "stamp verification" in done_command.lower()
    assert "NEVER pushes to `main`" in done_command
    assert "wikitoolkit ledger blockers" in done_command

    done_workflow = (repo_root / ".agent/workflows/sdd-done.md").read_text(encoding="utf-8")
    assert "wikitoolkit ledger blockers" in done_workflow

    done_skill = (repo_root / ".agents/skills/sdd-done/SKILL.md").read_text(encoding="utf-8")
    assert "Stamp verification" in done_skill
    assert "remove the worktree only after successful push/PR or merge path" in done_skill
