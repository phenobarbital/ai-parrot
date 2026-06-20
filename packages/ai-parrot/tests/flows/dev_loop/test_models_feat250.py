"""Unit tests for FEAT-250 dev-loop model additions (TASK-003).

Covers ``RepoSpec``, ``RevisionBrief``, the new ``QAReport`` code-review
fields, ``ResearchOutput.repo_path``, and the widened
``ClaudeCodeDispatchProfile.subagent`` Literal — all backward-compatible.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    QAReport,
    RepoSpec,
    ResearchOutput,
    RevisionBrief,
)


# ── RepoSpec ───────────────────────────────────────────────────────────


def test_repospec_defaults():
    s = RepoSpec(alias="nav", url="org/nav")
    assert s.branch == "main"
    assert s.private is False
    assert s.alias == "nav"


def test_repospec_roundtrip():
    s = RepoSpec(alias="nav", url="org/nav", branch="dev", private=True)
    assert RepoSpec.model_validate(s.model_dump()) == s


def test_repospec_requires_alias_and_url():
    with pytest.raises(ValidationError):
        RepoSpec(url="org/nav")  # type: ignore[call-arg]


# ── RevisionBrief ──────────────────────────────────────────────────────


def test_revisionbrief_roundtrip():
    b = RevisionBrief(
        repo_path="/abs/.claude/worktrees/repos/run-x/navigator",
        branch="feat-251-fix-x",
        pr_number=42,
        repository="navigator-org/navigator",
        jira_issue_key="OPS-1",
        feedback="Please also handle the null case.",
        head_sha="deadbeef",
    )
    assert b.pr_number == 42
    assert RevisionBrief.model_validate(b.model_dump()) == b


def test_revisionbrief_requires_all_fields():
    with pytest.raises(ValidationError):
        RevisionBrief(repo_path="/x", branch="b", pr_number=1)  # type: ignore[call-arg]


# ── QAReport code-review fields ────────────────────────────────────────


def test_qareport_codereview_defaults():
    r = QAReport(passed=True, criterion_results=[], lint_passed=True)
    assert r.code_review_passed is True
    assert r.code_review_findings == []


def test_qareport_codereview_explicit():
    r = QAReport(
        passed=False,
        criterion_results=[],
        lint_passed=True,
        code_review_passed=False,
        code_review_findings=["missing null check"],
    )
    assert r.code_review_passed is False
    assert r.code_review_findings == ["missing null check"]


# ── ResearchOutput.repo_path ───────────────────────────────────────────


def test_research_output_repo_path_optional():
    r = ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-x",
        worktree_path="/abs/worktree",
    )
    assert r.repo_path == ""
    assert r.worktree_path == "/abs/worktree"


def test_research_output_repo_path_set():
    r = ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-x",
        worktree_path="/abs/worktree",
        repo_path="/abs/clone",
    )
    assert r.repo_path == "/abs/clone"


# ── ClaudeCodeDispatchProfile.subagent widening ────────────────────────


def test_profile_accepts_codereview():
    assert (
        ClaudeCodeDispatchProfile(subagent="sdd-codereview").subagent
        == "sdd-codereview"
    )


def test_profile_rejects_unknown_subagent():
    with pytest.raises(ValidationError):
        ClaudeCodeDispatchProfile(subagent="sdd-bogus")  # type: ignore[arg-type]
