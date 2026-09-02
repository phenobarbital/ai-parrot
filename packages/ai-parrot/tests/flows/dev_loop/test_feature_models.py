"""Unit tests for FEAT-378 feature-mode models (TASK-1918).

Covers ``FeatureBrief``, the discriminated ``Brief`` union / ``parse_brief``
loader shim, ``JudgePanelConfig`` / ``default_judge_panel``, and the
planner/synthesis/feedback output contracts.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.models import (
    FeatureBrief,
    FeedbackDecision,
    JudgePanelConfig,
    JudgeSpec,
    PlannerOutput,
    SynthesisReport,
    WorkBrief,
    default_judge_panel,
    parse_brief,
)


def test_feature_brief_valid(tmp_path):
    doc = tmp_path / "x.proposal.md"
    doc.write_text("# p")
    fb = FeatureBrief(document_path=str(doc), document_kind="proposal")
    assert fb.kind == "feature"
    assert fb.jira_issue_key is None
    assert fb.dev_agents is None
    assert fb.judge_panel is None


def test_feature_brief_missing_document():
    with pytest.raises(ValidationError):
        FeatureBrief(document_path="/nope/missing.md", document_kind="spec")


def test_feature_brief_document_is_directory_not_file(tmp_path):
    with pytest.raises(ValidationError):
        FeatureBrief(document_path=str(tmp_path), document_kind="spec")


def test_feature_brief_no_acceptance_criteria_required(tmp_path):
    """FeatureBrief must NOT require acceptance_criteria/log_sources (spec §7)."""
    doc = tmp_path / "x.spec.md"
    doc.write_text("# s")
    fb = FeatureBrief(document_path=str(doc), document_kind="spec")
    assert not hasattr(fb, "acceptance_criteria")
    assert not hasattr(fb, "log_sources")


def test_union_routes_by_kind(tmp_path):
    doc = tmp_path / "x.spec.md"
    doc.write_text("# s")
    result = parse_brief(
        {"kind": "feature", "document_path": str(doc), "document_kind": "spec"}
    )
    assert isinstance(result, FeatureBrief)

    wb = parse_brief(
        {
            "kind": "bug",
            "summary": "something broke badly",
            "affected_component": "billing",
            "acceptance_criteria": [
                {"kind": "manual", "name": "check", "text": "verify manually"}
            ],
            "escalation_assignee": "owner@example.com",
            "reporter": "reporter@example.com",
        }
    )
    assert isinstance(wb, WorkBrief)
    assert wb.kind == "bug"


def test_union_default_kind_is_workbrief():
    """Dict without kind still parses as WorkBrief (zero behavior change)."""
    wb = parse_brief(
        {
            "summary": "something broke badly",
            "affected_component": "billing",
            "acceptance_criteria": [
                {"kind": "manual", "name": "check", "text": "verify manually"}
            ],
            "escalation_assignee": "owner@example.com",
            "reporter": "reporter@example.com",
        }
    )
    assert isinstance(wb, WorkBrief)
    assert wb.kind == "bug"


def test_judge_panel_defaults():
    panel = default_judge_panel()
    assert len(panel.judges) == 3
    assert panel.decision == "majority"
    backends = [j.agent for j in panel.judges]
    # The third seat was "gemini" until it was barred from every reviewer
    # role; the panel deliberately stays at THREE rather than dropping to
    # two, because review() is fail-closed on a single judge erroring when
    # panel_size == 2.
    assert backends == ["claude-code", "codex", "mantle"]


def test_judge_panel_config_requires_at_least_one_judge():
    with pytest.raises(ValidationError):
        JudgePanelConfig(judges=[])


def test_judge_spec_defaults_empty_model():
    spec = JudgeSpec(agent="mantle")
    assert spec.model == ""


def test_planner_output_roundtrip():
    out = PlannerOutput(
        spec_path="sdd/specs/x.spec.md",
        task_index_path="sdd/tasks/index/x.json",
        feat_id="FEAT-999",
        branch_name="feat-999-x",
        worktree_path="/tmp/worktree",
    )
    assert out.repo_path == ""
    assert out.jira_issue_key is None
    assert out.suggested_pool is None


@pytest.mark.parametrize("bad_pool", [1, 3, "3", ["claude-code"], True])
def test_planner_output_drops_scalar_suggested_pool(bad_pool):
    """A non-object ``suggested_pool`` is dropped, not fatal.

    Regression: sdd-planner is told not to emit this field, but agents
    emit a bare size (``"suggested_pool": 1``) anyway. That used to raise
    a pydantic ``model_type`` error, failing the whole planner dispatch
    over a value ``PlannerNode._resolve_pool`` overwrites moments later.
    """
    out = PlannerOutput(
        spec_path="sdd/specs/x.spec.md",
        task_index_path="sdd/tasks/index/x.json",
        feat_id="FEAT-999",
        branch_name="feat-999-x",
        worktree_path="/tmp/worktree",
        suggested_pool=bad_pool,
    )
    assert out.suggested_pool is None


def test_planner_output_keeps_object_suggested_pool():
    """Object-shaped input still validates strictly."""
    out = PlannerOutput(
        spec_path="sdd/specs/x.spec.md",
        task_index_path="sdd/tasks/index/x.json",
        feat_id="FEAT-999",
        branch_name="feat-999-x",
        worktree_path="/tmp/worktree",
        suggested_pool={"agents": [{"agent": "claude-code", "count": 2}]},
    )
    assert out.suggested_pool is not None
    assert out.suggested_pool.agents[0].count == 2

    with pytest.raises(ValidationError):
        PlannerOutput(
            spec_path="sdd/specs/x.spec.md",
            task_index_path="sdd/tasks/index/x.json",
            feat_id="FEAT-999",
            branch_name="feat-999-x",
            worktree_path="/tmp/worktree",
            suggested_pool={"agents": []},  # min_length=1
        )


def test_synthesis_report_defaults():
    report = SynthesisReport(consistent=True)
    assert report.adjustments == []
    assert report.summary == ""


def test_feedback_decision_literal_values():
    for decision in ("retry", "escalate", "accept_with_notes"):
        fd = FeedbackDecision(decision=decision)
        assert fd.decision == decision
    with pytest.raises(ValidationError):
        FeedbackDecision(decision="not-a-real-decision")


def test_claude_code_dispatch_profile_accepts_new_subagents():
    from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile

    profile = ClaudeCodeDispatchProfile(subagent="sdd-planner")
    assert profile.subagent == "sdd-planner"
    profile2 = ClaudeCodeDispatchProfile(subagent="sdd-feedback")
    assert profile2.subagent == "sdd-feedback"
