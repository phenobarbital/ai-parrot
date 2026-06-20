"""DevLoopCloseNode — terminal node that records a run's final state.

Implements **Module 10** of the FEAT-250 dev-loop refactor (G7). A pure
AI-Parrot node (no Claude Code dispatch) that posts a Jira summary comment
and transitions the ticket, then returns a terminal status dict. Used on
both the **initial** path (after ``DeploymentHandoffNode``) and the
**revision** path (after ``RevisionHandoffNode``); the transition label
branches on a ``shared["mode"]`` flag set by the runner (defaults to
``"initial"`` when absent).

Like the other terminal nodes (``FailureHandlerNode``), it MUST NOT raise:
Jira-side errors are logged and surfaced as a degraded status dict.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.models import QAReport, ResearchOutput
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node


# Transition label per run mode.
_TRANSITION_BY_MODE = {
    "initial": "Ready to Deploy",
    "revision": "In Review – revised",
}


@register_dev_loop_node("dev_loop.close")
class DevLoopCloseNode(DevLoopNode):
    """Terminal node — Jira summary comment + transition, then end the flow."""

    def __init__(
        self,
        jira_toolkit: Any,
        name: str = "close",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_jira", jira_toolkit)

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> Dict[str, str]:
        """Record the run's final state on Jira. Never raises.

        Reads ``research_output`` (for the issue key + feature id),
        ``qa_report``, and any deployment/revision result from shared state,
        posts a summary comment, transitions the ticket based on
        ``shared.get("mode", "initial")``, and returns a terminal status.

        Returns:
            ``{"status": "closed", "issue_key": ..., "mode": ...}`` on
            success, ``{"status": "closed_without_ticket", ...}`` when no
            Jira issue exists, or ``{"status": "close_failed", "error": ...}``
            when a Jira call raises.
        """
        shared = self.shared_state(ctx)
        research: Optional[ResearchOutput] = shared.get("research_output")
        mode = shared.get("mode", "initial")

        issue_key = research.jira_issue_key if research else None
        if not issue_key:
            self.logger.warning(
                "DevLoopClose: no jira_issue_key in shared state (mode=%s).",
                mode,
            )
            return {"status": "closed_without_ticket", "mode": mode}

        transition = _TRANSITION_BY_MODE.get(mode, _TRANSITION_BY_MODE["initial"])
        body = self._build_summary(mode, shared)

        try:
            await self._jira.jira_add_comment(issue=issue_key, body=body)
            await self._jira.jira_transition_issue(
                issue=issue_key, transition=transition
            )
        except Exception as exc:  # noqa: BLE001 - terminal node, never raises
            self.logger.exception("DevLoopClose Jira call failed: %s", exc)
            return {
                "status": "close_failed",
                "issue_key": issue_key,
                "mode": mode,
                "error": str(exc),
            }

        return {"status": "closed", "issue_key": issue_key, "mode": mode}

    # ------------------------------------------------------------------
    # Internal — summary construction
    # ------------------------------------------------------------------

    def _build_summary(self, mode: str, shared: Dict[str, Any]) -> str:
        """Build the terminal Jira summary comment."""
        qa_report = shared.get("qa_report")
        deployment = shared.get("deployment_result") or {}
        revision = shared.get("revision_result") or {}

        pr_url = deployment.get("pr_url") or revision.get("pr_url")
        pr_number = deployment.get("pr_number") or revision.get("pr_number")

        lines = [
            f"flow-bot: dev-loop run {'revised' if mode == 'revision' else 'completed'}.",
        ]
        if pr_url:
            lines.append(f"PR: {pr_url}" + (f" (#{pr_number})" if pr_number else ""))
        elif pr_number:
            lines.append(f"PR #{pr_number}")

        if isinstance(qa_report, QAReport):
            lines.append(
                f"QA: passed={qa_report.passed}, "
                f"code_review_passed={qa_report.code_review_passed}."
            )
            if qa_report.code_review_findings:
                findings = "\n".join(
                    f"- {f}" for f in qa_report.code_review_findings
                )
                lines.append(f"Code-review findings:\n{findings}")

        return "\n".join(lines)


__all__ = ["DevLoopCloseNode"]
