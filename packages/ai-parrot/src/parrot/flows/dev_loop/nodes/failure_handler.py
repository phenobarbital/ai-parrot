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

import logging
from typing import Any, Dict, Optional

from parrot.bots.flow.node import Node
from parrot.flows.dev_loop.models import (
    BugBrief,
    QAReport,
    ResearchOutput,
)


class FailureHandlerNode(Node):
    """Terminal failure node — comment + transition + reassign on Jira."""

    def __init__(
        self,
        *,
        jira_toolkit: Any,
        name: str = "failure_handler",
    ) -> None:
        super().__init__()
        self._name = name
        self._init_node(name)
        self._jira = jira_toolkit
        self.logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        return self._name

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self, prompt: str, ctx: Dict[str, Any]
    ) -> Dict[str, str]:
        """Escalate the run to a human via Jira. Never raises.

        Returns:
            ``{"status": "escalated", "issue_key": "OPS-..."}`` on
            success, or
            ``{"status": "escalated_without_ticket"}`` when no Jira
            issue exists yet, or
            ``{"status": "escalation_failed", "error": "..."}`` if any
            Jira call raises.
        """
        brief: Optional[BugBrief] = ctx.get("bug_brief")
        research: Optional[ResearchOutput] = ctx.get("research_output")
        failure_kind: str = ctx.get("failure_kind", "node_error")
        failure_payload: Any = ctx.get("failure_payload")

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
