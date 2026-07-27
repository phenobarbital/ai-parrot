"""FeedbackRouterNode — bounded retry / escalate / accept routing on QA failure.

Implements **Module 5** of the FEAT-378 spec. On QA failure, a short
read-only ``sdd-feedback`` dispatch proposes one of ``retry`` / ``escalate``
/ ``accept_with_notes`` over the ``QAReport`` + the judge panel's verdicts.

**The LLM only proposes — every hard rule is enforced here in Python,
post-parse (spec §2 item 6, §7 "Known Risks"):**

* ``accept_with_notes`` is only honored inside a deterministic envelope —
  computed FIRST, before the dispatch even runs — never trusted from the
  proposal alone: deterministic QA (acceptance criteria + lint) passed,
  every pending code-review/judge finding is ``minor``/``nit``, and no
  blocking manual criterion failed. Outside that envelope, a proposed
  ``accept_with_notes`` downgrades to ``retry`` (if attempts remain) or
  ``escalate``.
* ``retry`` is bounded by the FEAT-377/A repair-loop stop rule
  (``DEV_LOOP_QA_MAX_RETRIES``, shared with the bug-mode ``qa ->
  development`` back-edge): a proposed ``retry`` is honored while
  ``current_attempt < DEV_LOOP_QA_MAX_RETRIES``, else it downgrades to
  ``escalate`` with a warning log. :meth:`FeedbackRouterNode._retry_allowed`
  is the single seam this comparison lives in — see its docstring.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from parrot import conf
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    FeedbackDecision,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node
from parrot.flows.dev_loop.session_state import FeedbackDecisionRecorded, SessionHost

# Finding severities that never block ``accept_with_notes`` (mirrors
# ``CodeReviewFinding.severity``'s Literal, models.py:757-763).
_MINOR_SEVERITIES = frozenset({"minor", "nit"})


class _FeedbackBrief(BaseModel):
    """Local dispatch payload for the ``sdd-feedback`` subagent.

    A per-dispatch summary of the ``QAReport`` + judge-panel verdicts —
    not a canonical dev-loop model, mirroring the locally-scoped brief
    pattern already used by ``code_review.py``, ``planner.py``, and
    ``synthesis.py`` for one-off dispatch payloads.
    """

    deterministic_passed: bool
    lint_passed: bool
    code_review_passed: bool
    code_review_findings: List[str] = Field(default_factory=list)
    judge_verdicts_summary: List[str] = Field(default_factory=list)
    envelope_ok: bool
    attempt: int
    retry_allowed: bool
    notes: str = ""


@register_dev_loop_node("dev_loop.feedback_router")
class FeedbackRouterNode(DevLoopNode):
    """QA-failure feedback router — Python enforces, the LLM only proposes.

    Args:
        dispatcher: A :class:`ClaudeCodeDispatcher` instance shared by
            every node in the flow.
        name: Node id, default ``"feedback_router"``.
    """

    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        name: str = "feedback_router",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> FeedbackDecision:
        """Dispatch ``sdd-feedback``, enforce the hard rules, return the decision.

        Reads ``qa_report`` and ``research_output`` (worktree path) from
        shared state; also reads the judge panel's ``session_host.state
        .judge_verdicts`` when a ``SessionHost`` is present. Writes
        ``feedback_decision`` to shared state and records a
        ``FeedbackDecisionRecorded`` action.
        """
        shared = self.shared_state(ctx)
        qa_report: QAReport = shared["qa_report"]
        research: ResearchOutput = shared["research_output"]
        session_host: Optional[SessionHost] = shared.get("session_host")
        review_verdict = shared.get("_code_review_verdict")

        envelope_ok = self._envelope_ok(qa_report, review_verdict)
        attempt = self._current_attempt(session_host)
        retry_allowed = self._retry_allowed(session_host)

        brief = _FeedbackBrief(
            deterministic_passed=self._deterministic_passed(qa_report),
            lint_passed=qa_report.lint_passed,
            code_review_passed=qa_report.code_review_passed,
            code_review_findings=list(qa_report.code_review_findings),
            judge_verdicts_summary=self._judge_verdict_summaries(session_host),
            envelope_ok=envelope_ok,
            attempt=attempt,
            retry_allowed=retry_allowed,
            notes=qa_report.notes,
        )

        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-feedback",
            permission_mode="plan",
            allowed_tools=["Read"],  # read-only, same posture as sdd-qa
            setting_sources=["project"],
        )

        proposed: FeedbackDecision = await self._dispatcher.dispatch(
            brief=brief,
            profile=profile,
            output_model=FeedbackDecision,
            run_id=shared["run_id"],
            node_id=self.name,
            cwd=research.worktree_path,
            session_host=session_host,
        )

        final = self._enforce(
            proposed, envelope_ok=envelope_ok, retry_allowed=retry_allowed
        )

        if session_host is not None:
            session_host.apply(
                FeedbackDecisionRecorded(
                    decision=final.decision,
                    dev_brief=final.dev_brief,
                    notes=final.notes,
                    qa_attempt=attempt,
                )
            )

        shared["feedback_decision"] = final
        return final

    # ------------------------------------------------------------------
    # Internal — deterministic envelope (spec §2 item 6)
    # ------------------------------------------------------------------

    @staticmethod
    def _deterministic_passed(qa_report: QAReport) -> bool:
        """``True`` iff every non-manual criterion passed AND lint passed.

        ``QAReport.passed`` folds in the qualitative code-review gate too
        (QANode's own ``deterministic_passed and cr_passed and
        blocking_passed``), so the pure-deterministic slice has to be
        recomputed from ``criterion_results`` + ``lint_passed`` rather
        than read off a single field.
        """
        return qa_report.lint_passed and all(
            cr.passed for cr in qa_report.criterion_results if cr.kind != "manual"
        )

    def _envelope_ok(self, qa_report: QAReport, review_verdict: Any) -> bool:
        """Compute the ``accept_with_notes`` envelope — Python, pre-dispatch.

        Fail-closed by construction: when no structured code-review
        verdict is available (dispatch degraded, or no review ran), the
        finding severities cannot be verified, so the envelope is closed
        rather than assumed open.

        Args:
            qa_report: The upstream :class:`QAReport`.
            review_verdict: ``shared.get("_code_review_verdict")`` — the
                structured ``CodeReviewVerdict`` QANode stashes internally
                (``None`` when the review dispatch degraded or never ran).
                Read across node boundaries deliberately: it is the only
                place in shared state carrying per-finding severities —
                ``QAReport.code_review_findings`` is plain strings.

        Returns:
            Whether ``accept_with_notes`` is currently permitted.
        """
        deterministic_passed = self._deterministic_passed(qa_report)
        no_blocking_manual_failures = not any(
            cr.kind == "manual" and not cr.passed for cr in qa_report.criterion_results
        )
        if review_verdict is None:
            findings_ok = False
        else:
            findings = list(getattr(review_verdict, "findings", []))
            findings_ok = all(
                getattr(f, "severity", None) in _MINOR_SEVERITIES for f in findings
            )
        return deterministic_passed and no_blocking_manual_failures and findings_ok

    # ------------------------------------------------------------------
    # Internal — stop rule (FEAT-377/A seam)
    # ------------------------------------------------------------------

    def _retry_allowed(self, session_host: Optional[SessionHost]) -> bool:
        """Stop-rule check — the FEAT-377/A repair-loop counter seam.

        Bounds the ``feedback_router -> development`` back-edge the same
        way the bug-mode ``qa -> development`` edge is bounded (TASK-1910)
        — reusing the same ``DEV_LOOP_QA_MAX_RETRIES`` config knob — except
        feature-mode has no ``QAReport.attempt`` field to read the counter
        off of (a ``FeedbackDecision`` carries no attempt number), so the
        comparison uses :meth:`_current_attempt`'s session-state-derived
        count instead: the number of feedback rounds already recorded in
        this run (1-indexed), mirroring ``QAReport.attempt``'s semantics
        exactly (both are "which attempt is this" counters, just sourced
        differently).

        Args:
            session_host: The run's :class:`SessionHost`, if any.

        Returns:
            ``True`` while ``_current_attempt(session_host) <
            conf.DEV_LOOP_QA_MAX_RETRIES``, else ``False``.
        """
        return self._current_attempt(session_host) < int(conf.DEV_LOOP_QA_MAX_RETRIES)

    def _current_attempt(self, session_host: Optional[SessionHost]) -> int:
        """Best-effort QA-attempt number for ``FeedbackDecisionRecorded``.

        Without FEAT-377/A's dedicated counter, derives the attempt number
        from how many feedback decisions have already been recorded in
        this run's session state (1-indexed).

        Args:
            session_host: The run's :class:`SessionHost`, if any.

        Returns:
            The current attempt number (``1`` when no session host, or on
            the first feedback round).
        """
        if session_host is None:
            return 1
        return len(session_host.state.feedback_decisions) + 1

    # ------------------------------------------------------------------
    # Internal — enforcement (post-parse, spec §2 item 6)
    # ------------------------------------------------------------------

    def _enforce(
        self,
        proposed: FeedbackDecision,
        *,
        envelope_ok: bool,
        retry_allowed: bool,
    ) -> FeedbackDecision:
        """Re-check the LLM's proposal against the hard rules; downgrade if needed.

        Args:
            proposed: The subagent's proposed :class:`FeedbackDecision`.
            envelope_ok: Result of :meth:`_envelope_ok`.
            retry_allowed: Result of :meth:`_retry_allowed`.

        Returns:
            The enforced :class:`FeedbackDecision` — ``proposed`` unchanged
            when it already satisfies both rules.
        """
        decision = proposed.decision

        if decision == "accept_with_notes" and not envelope_ok:
            downgraded = "retry" if retry_allowed else "escalate"
            self.logger.warning(
                "sdd-feedback proposed accept_with_notes outside the "
                "deterministic envelope; downgrading to %s.", downgraded,
            )
            decision = downgraded

        if decision == "retry" and not retry_allowed:
            self.logger.warning(
                "sdd-feedback proposed retry but the repair-loop stop "
                "rule disallows it (DEV_LOOP_QA_MAX_RETRIES attempts "
                "exhausted); downgrading to escalate.",
            )
            decision = "escalate"

        if decision == proposed.decision:
            return proposed
        return proposed.model_copy(update={"decision": decision})

    # ------------------------------------------------------------------
    # Internal — judge-panel context (informational, for the LLM's brief)
    # ------------------------------------------------------------------

    @staticmethod
    def _judge_verdict_summaries(session_host: Optional[SessionHost]) -> List[str]:
        """Human-readable summaries of the latest QA round's judge verdicts.

        Args:
            session_host: The run's :class:`SessionHost`, if any.

        Returns:
            One line per judge in the most recent recorded round, or an
            empty list when there is no session host or no verdicts yet.
        """
        if session_host is None:
            return []
        rounds = session_host.state.judge_verdicts
        if not rounds:
            return []
        latest_round = max(
            rounds, key=lambda r: max((v.ts for v in rounds[r]), default=0.0)
        )
        return [
            f"{v.judge_id} ({v.backend}): {'pass' if v.passed else 'fail'} "
            f"({v.findings_count} findings) — {v.summary}"
            for v in rounds[latest_round]
        ]


__all__ = ["FeedbackRouterNode"]
