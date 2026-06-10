"""FailureHandlerNode — Jira escalation on flow failure.

Implements **Module 9** of the dev-loop spec. Terminal failure node
routed to either by:

* The QA pass/fail transition when ``QAReport.passed is False``.
* A global error transition when any earlier node raises a
  ``DispatchExecutionError``, ``DispatchOutputValidationError``, or
  ``RuntimeError``.

Behavior: post a structured Jira comment, transition the ticket to
*Needs Human Review*, and reassign to ``BugBrief.escalation_assignee``.
The node MUST NOT raise — Jira-side errors are logged and the node
returns a structured ``dict`` describing the outcome.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Union

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.models import (
    BugBrief,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode


class FailureHandlerNode(DevLoopNode):
    """Terminal failure node — comment + transition + reassign on Jira."""

    def __init__(
        self,
        *,
        jira_toolkit: Any,
        name: str = "failure_handler",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_jira", jira_toolkit)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> Dict[str, str]:
        """Escalate the run to a human via Jira. Never raises.

        The failure context is taken from the shared state when present
        (``failure_kind`` / ``failure_payload``); otherwise it is derived:
        a failed ``qa_report`` becomes ``qa_failed``, and the first node
        error recorded on the :class:`FlowContext` becomes ``node_error``.

        Returns:
            ``{"status": "escalated", "issue_key": "OPS-..."}`` on
            success, or
            ``{"status": "escalated_without_ticket"}`` when no Jira
            issue exists yet, or
            ``{"status": "escalation_failed", "error": "..."}`` if any
            Jira call raises.
        """
        shared = self.shared_state(ctx)
        brief: Optional[BugBrief] = shared.get("bug_brief")
        research: Optional[ResearchOutput] = shared.get("research_output")
        failure_kind, failure_payload = self._resolve_failure(ctx, shared)

        issue_key = research.jira_issue_key if research else None
        if not issue_key:
            self.logger.error(
                "FailureHandler: no jira_issue_key in ctx; research never "
                "created the ticket. failure_kind=%s",
                failure_kind,
            )
            return {"status": "escalated_without_ticket"}

        body = self._build_comment(failure_kind, failure_payload)

        try:
            await self._jira.jira_add_comment(issue=issue_key, body=body)
            await self._jira.jira_transition_issue(
                issue=issue_key, transition="Needs Human Review"
            )
            if brief is not None and brief.escalation_assignee:
                await self._jira.jira_assign_issue(
                    issue=issue_key,
                    assignee=brief.escalation_assignee,
                )
        except Exception as exc:  # noqa: BLE001 - terminal node
            self.logger.exception("Escalation Jira call failed: %s", exc)
            return {
                "status": "escalation_failed",
                "issue_key": issue_key,
                "error": str(exc),
            }

        return {"status": "escalated", "issue_key": issue_key}

    # ------------------------------------------------------------------
    # Internal — failure-context resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_failure(
        ctx: Union[FlowContext, Dict[str, Any]],
        shared: Dict[str, Any],
    ) -> Tuple[str, Any]:
        """Determine ``(failure_kind, failure_payload)`` for this escalation.

        Resolution order:

        1. Explicit ``shared['failure_kind']`` / ``shared['failure_payload']``.
        2. A failed :class:`QAReport` in ``shared['qa_report']`` →
           ``("qa_failed", report)``.
        3. The first error recorded on the :class:`FlowContext` →
           ``("node_error", {node_id, exception_type, message})``.
        4. Fallback ``("node_error", None)``.

        Args:
            ctx: The flow execution context (used for ``ctx.errors``).
            shared: The shared state dict.

        Returns:
            Tuple of failure kind and payload.
        """
        if "failure_kind" in shared:
            return shared["failure_kind"], shared.get("failure_payload")

        qa_report = shared.get("qa_report")
        if isinstance(qa_report, QAReport) and not qa_report.passed:
            return "qa_failed", qa_report

        errors = getattr(ctx, "errors", None) or {}
        if errors:
            node_id, exc = next(iter(errors.items()))
            return "node_error", {
                "node_id": node_id,
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
        return "node_error", shared.get("failure_payload")

    # ------------------------------------------------------------------
    # Internal — comment construction
    # ------------------------------------------------------------------

    def _build_comment(self, kind: str, payload: Any) -> str:
        if kind == "qa_failed" and isinstance(payload, QAReport):
            criterion_lines = "\n".join(
                f"- {r.name}: exit={r.exit_code}, passed={r.passed}, "
                f"stderr_tail={r.stderr_tail!r}"
                for r in payload.criterion_results
            ) or "(no criterion results captured)"
            return (
                "flow-bot: QA failed.\n\n"
                f"Acceptance criterion results:\n{criterion_lines}\n\n"
                f"Lint passed: {payload.lint_passed}\n"
                f"Notes: {payload.notes or '(none)'}"
            )
        if kind == "node_error":
            d = payload if isinstance(payload, dict) else {}
            node_id = d.get("node_id", "?")
            exc_type = d.get("exception_type", "?")
            message = d.get("message", "")
            return (
                f"flow-bot: flow halted on node `{node_id}` with "
                f"`{exc_type}`.\n\n```\n{message}\n```"
            )
        return f"flow-bot: flow failed (kind={kind})"


__all__ = ["FailureHandlerNode"]
