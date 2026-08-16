"""Unit tests for parrot.flows.dev_loop.nodes.feedback_router (TASK-1923,
FEAT-377/A)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from parrot import conf
from parrot.flows.dev_loop.models import (
    AdversarialFinding,
    CodeReviewVerdict,
    CriterionResult,
    FeedbackDecision,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.feedback_router import FeedbackRouterNode
from parrot.flows.dev_loop.session_state import (
    FeedbackDecisionRecorded,
    SessionHost,
)


def _research_out(tmp_path) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-999",
        branch_name="feat-999-x",
        worktree_path=str(tmp_path),
        log_excerpts=[],
    )


def _qa_report(*, passed: bool, lint_passed: bool = True, criterion_passed: bool = True,
                code_review_passed: bool = True, findings=None, notes: str = "") -> QAReport:
    return QAReport(
        passed=passed,
        criterion_results=[
            CriterionResult(
                name="c1", kind="shell", exit_code=0 if criterion_passed else 1,
                duration_seconds=0.1, passed=criterion_passed,
            )
        ],
        lint_passed=lint_passed,
        code_review_passed=code_review_passed,
        code_review_findings=findings or [],
        notes=notes,
    )


def _node(dispatcher) -> FeedbackRouterNode:
    return FeedbackRouterNode(dispatcher=dispatcher)


def _shared(tmp_path, qa_report, *, review_verdict=None, session_host=None) -> dict:
    shared = {
        "qa_report": qa_report,
        "research_output": _research_out(tmp_path),
        "run_id": "r1",
    }
    if review_verdict is not None:
        shared["_code_review_verdict"] = review_verdict
    if session_host is not None:
        shared["session_host"] = session_host
    return shared


async def test_retry_with_dev_brief_allowed_when_attempts_remain(tmp_path, monkeypatch):
    """A retry proposal is honored while attempts remain under
    DEV_LOOP_QA_MAX_RETRIES (FEAT-377/A) — no session_host means
    _current_attempt() == 1, which is < any max_retries >= 2."""
    monkeypatch.setattr(conf, "DEV_LOOP_QA_MAX_RETRIES", 2)
    proposed = FeedbackDecision(decision="retry", dev_brief="fix the null check")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=proposed)
    node = _node(dispatcher)
    qa_report = _qa_report(passed=False, criterion_passed=False)
    shared = _shared(tmp_path, qa_report)

    result = await node.execute(shared)

    assert result.decision == "retry"
    assert result is proposed
    assert shared["feedback_decision"] is result


async def test_accept_with_notes_inside_envelope(tmp_path):
    proposed = FeedbackDecision(decision="accept_with_notes", notes="two nits found")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=proposed)
    node = _node(dispatcher)
    qa_report = _qa_report(passed=False, code_review_passed=False, findings=["nit: whitespace"])
    verdict = CodeReviewVerdict(
        passed=False,
        findings=[
            AdversarialFinding(message="whitespace", severity="nit", source="claude-code"),
        ],
    )
    shared = _shared(tmp_path, qa_report, review_verdict=verdict)

    result = await node.execute(shared)

    assert result.decision == "accept_with_notes"
    assert result.notes == "two nits found"


async def test_accept_outside_envelope_downgrades_to_retry_when_allowed(tmp_path, monkeypatch):
    """A major finding breaks the envelope -> accept_with_notes downgrades
    to retry while attempts remain (FEAT-377/A) rather than escalate."""
    monkeypatch.setattr(conf, "DEV_LOOP_QA_MAX_RETRIES", 2)
    proposed = FeedbackDecision(decision="accept_with_notes", notes="looks fine")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=proposed)
    node = _node(dispatcher)
    qa_report = _qa_report(passed=False, code_review_passed=False, findings=["major: bug"])
    verdict = CodeReviewVerdict(
        passed=False,
        findings=[
            AdversarialFinding(message="real bug", severity="major", source="claude-code"),
        ],
    )
    shared = _shared(tmp_path, qa_report, review_verdict=verdict)

    result = await node.execute(shared)

    assert result.decision == "retry"


async def test_accept_outside_envelope_escalates_when_exhausted(tmp_path, monkeypatch):
    """Same envelope-break as above, but attempts are already exhausted ->
    downgrades all the way to escalate, never retry."""
    monkeypatch.setattr(conf, "DEV_LOOP_QA_MAX_RETRIES", 1)
    proposed = FeedbackDecision(decision="accept_with_notes", notes="looks fine")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=proposed)
    node = _node(dispatcher)
    qa_report = _qa_report(passed=False, code_review_passed=False, findings=["major: bug"])
    verdict = CodeReviewVerdict(
        passed=False,
        findings=[
            AdversarialFinding(message="real bug", severity="major", source="claude-code"),
        ],
    )
    shared = _shared(tmp_path, qa_report, review_verdict=verdict)  # attempt 1 == max_retries 1

    result = await node.execute(shared)

    assert result.decision == "escalate"


async def test_accept_with_notes_no_review_verdict_fails_closed(tmp_path, monkeypatch):
    """No structured review verdict available -> envelope closed (fail-closed),
    downgrading to retry while attempts remain."""
    monkeypatch.setattr(conf, "DEV_LOOP_QA_MAX_RETRIES", 2)
    proposed = FeedbackDecision(decision="accept_with_notes", notes="looks fine")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=proposed)
    node = _node(dispatcher)
    qa_report = _qa_report(passed=True)
    shared = _shared(tmp_path, qa_report)  # no _code_review_verdict at all

    result = await node.execute(shared)

    assert result.decision == "retry"


async def test_retry_disallowed_after_max_retries_escalates(tmp_path, monkeypatch):
    """Once DEV_LOOP_QA_MAX_RETRIES attempts have already been recorded, a
    proposed retry downgrades to escalate (FEAT-377/A stop rule)."""
    monkeypatch.setattr(conf, "DEV_LOOP_QA_MAX_RETRIES", 2)
    proposed = FeedbackDecision(decision="retry", dev_brief="try again")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=proposed)
    node = _node(dispatcher)
    qa_report = _qa_report(passed=False, criterion_passed=False)
    host = SessionHost("run-1")
    # One prior feedback round already recorded -> _current_attempt() == 2,
    # equal to DEV_LOOP_QA_MAX_RETRIES -> retry no longer allowed.
    host.apply(FeedbackDecisionRecorded(decision="retry", qa_attempt=1))
    shared = _shared(tmp_path, qa_report, session_host=host)

    result = await node.execute(shared)

    assert result.decision == "escalate"


async def test_escalate_passthrough(tmp_path):
    proposed = FeedbackDecision(decision="escalate")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=proposed)
    node = _node(dispatcher)
    qa_report = _qa_report(passed=False, criterion_passed=False)
    shared = _shared(tmp_path, qa_report)

    result = await node.execute(shared)

    assert result.decision == "escalate"
    assert result is proposed  # unchanged — no downgrade needed


async def test_decision_recorded_action(tmp_path):
    proposed = FeedbackDecision(decision="escalate")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=proposed)
    node = _node(dispatcher)
    qa_report = _qa_report(passed=False, criterion_passed=False)
    host = SessionHost("run-1")
    shared = _shared(tmp_path, qa_report, session_host=host)

    await node.execute(shared)

    assert len(host.state.feedback_decisions) == 1
    record = host.state.feedback_decisions[0]
    assert record.decision == "escalate"
    assert record.qa_attempt == 1


async def test_dispatch_receives_read_only_profile(tmp_path):
    proposed = FeedbackDecision(decision="escalate")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=proposed)
    node = _node(dispatcher)
    qa_report = _qa_report(passed=False, criterion_passed=False)
    shared = _shared(tmp_path, qa_report)

    await node.execute(shared)

    _, kwargs = dispatcher.dispatch.call_args
    profile = kwargs["profile"]
    assert profile.subagent == "sdd-feedback"
    assert profile.permission_mode == "plan"
    assert profile.allowed_tools == ["Read"]
