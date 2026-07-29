"""QANode advisory-finding triage loop (FEAT-375 Module 5).

Harness: a stub advisory reviewer (`.advisory = True`, `.review()` returns a
fixed `CodeReviewVerdict`) plus the shared `MagicMock()` dev dispatcher whose
`.dispatch()` side-effects step through: deterministic QA → (rerun QA if
`files_modified`), and separately a canned `TriageReport` for the triage
dispatch. Mirrors the fixture style of `test_qa_codereview.py`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import BugBrief, FlowtaskCriterion, QAReport, ResearchOutput
from parrot.flows.dev_loop.models import AdversarialFinding, CodeReviewVerdict, TriageReport
from parrot.flows.dev_loop.nodes.qa import QANode


@pytest.fixture
def ctx() -> dict:
    return {
        "run_id": "r1",
        "research_output": ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="x",
            feat_id="FEAT-130",
            branch_name="feat-130-fix",
            worktree_path="/abs/.claude/worktrees/feat-130-fix",
        ),
        "bug_brief": BugBrief(
            summary="x" * 20,
            affected_component="y",
            log_sources=[],
            acceptance_criteria=[FlowtaskCriterion(name="run", task_path="a.yaml")],
            escalation_assignee="a",
            reporter="b",
        ),
    }


def _advisory_reviewer(verdict: CodeReviewVerdict) -> MagicMock:
    reviewer = MagicMock()
    reviewer.advisory = True
    reviewer.review = AsyncMock(return_value=verdict)
    return reviewer


def _finding(message: str, file: str = "a.py") -> AdversarialFinding:
    return AdversarialFinding(message=message, severity="major", file=file, source="codex-adversarial")


@pytest.mark.asyncio
async def test_triage_confirm_triggers_rerun(ctx):
    """CONFIRM finding with files_modified → _run_deterministic_qa called twice."""
    finding = _finding("Off by one")
    verdict = CodeReviewVerdict(passed=False, findings=[finding])
    reviewer = _advisory_reviewer(verdict)

    confirmed = finding.model_copy(
        update={"disposition": "confirm", "triage_reason": "valid, fixed", "finding_id": "finding-0"}
    )
    triage_report = TriageReport(findings=[confirmed], files_modified=["a.py"])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    rerun_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa_report, triage_report, rerun_report])

    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(ctx)

    assert report.passed is True
    # deterministic (1) + triage (2) + rerun (3) == 3 dispatch calls.
    assert dispatcher.dispatch.await_count == 3


@pytest.mark.asyncio
async def test_confirm_without_fix_evidence_fails_closed_to_escalate(ctx):
    """FEAT-375 code-review fix: CONFIRM with no corresponding files_modified
    entry must NOT silently pass QA — it escalates instead of disappearing."""
    finding = _finding("Off by one")
    verdict = CodeReviewVerdict(passed=False, findings=[finding])
    reviewer = _advisory_reviewer(verdict)

    # The worker claims "confirm" but reports NO files_modified at all —
    # no evidence the fix was actually applied.
    unevidenced_confirm = finding.model_copy(
        update={"disposition": "confirm", "triage_reason": "fixed it", "finding_id": "finding-0"}
    )
    triage_report = TriageReport(findings=[unevidenced_confirm], files_modified=[])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa_report, triage_report])

    session_host = MagicMock()
    session_host.open_gate = MagicMock(return_value=("gate-1", MagicMock()))

    async def _wait_gate(gate_id):
        resolved = MagicMock()
        resolved.status = "rejected"
        return resolved

    session_host.wait_gate = AsyncMock(side_effect=_wait_gate)
    ctx["session_host"] = session_host

    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(ctx)

    # No rerun happened (no files_modified) — only 2 dispatch calls.
    assert dispatcher.dispatch.await_count == 2
    session_host.open_gate.assert_called_once()
    assert session_host.open_gate.call_args.kwargs["kind"] == "review_escalation"
    assert "Escalated for human review" in report.notes
    assert "Off by one" in report.notes
    # Fail-closed all the way: the gate resolved "rejected", so the run does
    # NOT get to silently pass over the unevidenced "fix".
    assert report.code_review_passed is False
    assert report.passed is False


@pytest.mark.asyncio
async def test_confirm_with_fix_evidence_stays_confirmed(ctx):
    """Sanity check: a CONFIRM backed by a real files_modified entry is NOT escalated."""
    finding = _finding("Off by one")
    verdict = CodeReviewVerdict(passed=False, findings=[finding])
    reviewer = _advisory_reviewer(verdict)

    confirmed = finding.model_copy(
        update={"disposition": "confirm", "triage_reason": "valid, fixed", "finding_id": "finding-0"}
    )
    triage_report = TriageReport(findings=[confirmed], files_modified=["a.py"])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    rerun_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa_report, triage_report, rerun_report])

    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(ctx)

    # Rerun triggered (evidence present) and no escalation note.
    assert dispatcher.dispatch.await_count == 3
    assert report.passed is True
    assert "Escalated for human review" not in (report.notes or "")


@pytest.mark.asyncio
async def test_triage_reject_recorded_in_notes(ctx):
    """REJECT disposition → triage_reason lands in QAReport.notes."""
    finding = _finding("Not actually an issue")
    verdict = CodeReviewVerdict(passed=False, findings=[finding])
    reviewer = _advisory_reviewer(verdict)

    rejected = finding.model_copy(
        update={
            "disposition": "reject",
            "triage_reason": "false positive — see AC 3",
            "finding_id": "finding-0",
        }
    )
    triage_report = TriageReport(findings=[rejected], files_modified=[])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa_report, triage_report])

    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(ctx)

    assert report.passed is True
    assert "rejected:" in report.notes
    assert "false positive — see AC 3" in report.notes


@pytest.mark.asyncio
async def test_triage_escalate_opens_gate_and_note(ctx):
    """ESCALATE → open_gate(kind='review_escalation') + note in QAReport.notes."""
    finding = _finding("Possible security issue")
    verdict = CodeReviewVerdict(passed=False, findings=[finding])
    reviewer = _advisory_reviewer(verdict)

    escalated = finding.model_copy(
        update={
            "disposition": "escalate",
            "triage_reason": "needs a human call",
            "finding_id": "finding-0",
        }
    )
    triage_report = TriageReport(findings=[escalated], files_modified=[])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa_report, triage_report])

    session_host = MagicMock()
    session_host.open_gate = MagicMock(return_value=("gate-1", MagicMock()))

    async def _wait_gate(gate_id):
        resolved = MagicMock()
        resolved.status = "approved"
        return resolved

    session_host.wait_gate = AsyncMock(side_effect=_wait_gate)

    ctx["session_host"] = session_host
    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(ctx)

    session_host.open_gate.assert_called_once()
    assert session_host.open_gate.call_args.kwargs["kind"] == "review_escalation"
    assert "Escalated for human review" in report.notes
    assert "Possible security issue" in report.notes


@pytest.mark.asyncio
async def test_escalate_rejected_gate_fails_code_review(ctx):
    """ESCALATE gate resolved as rejected → code_review_passed is False."""
    finding = _finding("Possible security issue")
    verdict = CodeReviewVerdict(passed=False, findings=[finding])
    reviewer = _advisory_reviewer(verdict)

    escalated = finding.model_copy(
        update={
            "disposition": "escalate",
            "triage_reason": "needs a human call",
            "finding_id": "finding-0",
        }
    )
    triage_report = TriageReport(findings=[escalated], files_modified=[])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa_report, triage_report])

    session_host = MagicMock()
    session_host.open_gate = MagicMock(return_value=("gate-1", MagicMock()))

    async def _wait_gate(gate_id):
        resolved = MagicMock()
        resolved.status = "rejected"
        return resolved

    session_host.wait_gate = AsyncMock(side_effect=_wait_gate)

    ctx["session_host"] = session_host
    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(ctx)

    assert report.code_review_passed is False
    assert report.passed is False


@pytest.mark.asyncio
async def test_missing_disposition_fails_closed(ctx):
    """Report omits one finding → one retry → treated as ESCALATE."""
    finding = _finding("Some finding")
    verdict = CodeReviewVerdict(passed=False, findings=[finding])
    reviewer = _advisory_reviewer(verdict)

    # Both dispatch attempts return a report with NO dispositions set.
    undispositioned_report = TriageReport(findings=[finding], files_modified=[])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        side_effect=[qa_report, undispositioned_report, undispositioned_report]
    )

    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(ctx)

    # deterministic (1) + triage attempt (2) + retry (3) == 3 calls.
    assert dispatcher.dispatch.await_count == 3
    assert "Escalated for human review" in report.notes


@pytest.mark.asyncio
async def test_non_advisory_path_unchanged(ctx):
    """advisory=False reviewer → no triage dispatch, legacy flow intact."""
    verdict = CodeReviewVerdict(passed=False, findings=[_finding("Some finding")])
    reviewer = MagicMock()
    reviewer.advisory = False
    reviewer.review = AsyncMock(return_value=verdict)

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa_report])

    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(ctx)

    # Only the deterministic pass touches the dev dispatcher — no triage dispatch.
    dispatcher.dispatch.assert_awaited_once()
    assert report.code_review_passed is False


@pytest.mark.asyncio
async def test_skip_prefixed_findings_bypass_triage(ctx):
    """'code-review could not run:' findings never enter triage."""
    reviewer = MagicMock()
    reviewer.advisory = True
    reviewer.review = AsyncMock(side_effect=RuntimeError("infra down"))

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa_report])

    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(ctx)

    # Only the deterministic pass — the review degraded before any findings
    # existed, so no triage dispatch happens.
    dispatcher.dispatch.assert_awaited_once()
    assert report.passed is True
    assert any("could not run" in f for f in report.code_review_findings)
