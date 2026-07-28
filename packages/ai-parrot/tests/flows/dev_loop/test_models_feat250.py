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
    CodeReviewVerdict,
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


def test_qareport_codereview_findings_coerces_dicts():
    """Dicts (CodeReviewFinding-shaped) are coerced to their message string."""
    r = QAReport(
        passed=True,
        criterion_results=[],
        lint_passed=True,
        code_review_findings=[
            {"file": "foo.py", "message": "missing null check", "severity": "minor"},
            "plain string finding",
            {"file": "bar.py", "severity": "major"},
        ],
    )
    assert r.code_review_findings[0] == "missing null check"
    assert r.code_review_findings[1] == "plain string finding"
    # no message key -> fallback to str(dict)
    assert "bar.py" in r.code_review_findings[2]
    assert "major" in r.code_review_findings[2]


# ── CodeReviewVerdict findings coercion ────────────────────────────────


def test_verdict_coerces_plain_strings():
    v = CodeReviewVerdict(findings=["missing null check"])
    assert v.findings[0].message == "missing null check"
    assert v.findings[0].severity == "minor"


def test_verdict_coerces_dict_missing_message_and_severity():
    """Subagent returns file+verdict but no message/severity."""
    v = CodeReviewVerdict(
        passed=False,
        findings=[
            {"file": "parrot/loaders/msword.py", "verdict": "CONFIRMED"},
            {"file": "tests/test_x.py", "summary": "test gap", "verdict": "PLAUSIBLE"},
        ],
    )
    assert len(v.findings) == 2
    assert v.findings[0].file == "parrot/loaders/msword.py"
    assert v.findings[0].severity == "minor"
    assert v.findings[0].message == "(no message)"
    assert v.findings[1].message == "test gap"


def test_verdict_passes_well_formed_dicts_through():
    v = CodeReviewVerdict(
        findings=[{"message": "actual issue", "severity": "major", "file": "x.py"}]
    )
    assert v.findings[0].message == "actual issue"
    assert v.findings[0].severity == "major"


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
