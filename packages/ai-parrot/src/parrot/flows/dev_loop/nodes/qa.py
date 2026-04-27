"""QANode — sdd-qa dispatch in plan mode.

Implements **Module 7**. Dispatches the ``sdd-qa`` subagent under
``permission_mode="plan"`` with no edit/write tools so the QA pass is
strictly read-only. The subagent runs each acceptance criterion as a
subprocess (deterministic — exit code is the source of truth, not LLM
judgement; spec G6) and runs lint, then returns a :class:`QAReport`.

The node returns the report regardless of ``passed`` — the flow factory
(TASK-886) decides routing via a :class:`FlowTransition`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from parrot.bots.flow.node import Node
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import (
    BugBrief,
    ClaudeCodeDispatchProfile,
    QAReport,
    ResearchOutput,
)


_DEFAULT_LINT_COMMAND = "ruff check . && mypy --no-incremental"


class QANode(Node):
    """Fourth node — runs deterministic acceptance verification."""

    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        lint_command: Optional[str] = None,
        name: str = "qa",
    ) -> None:
        super().__init__()
        self._name = name
        self._init_node(name)
        self._dispatcher = dispatcher
        self._lint_command = lint_command or _DEFAULT_LINT_COMMAND
        self.logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        return self._name

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> QAReport:
        """Dispatch ``sdd-qa`` and return the :class:`QAReport`.

        The node returns the report whether ``passed`` is ``True`` or
        ``False``. The flow factory routes the failure path elsewhere;
        the *node* never raises on ``passed=False``.
        """
        research: ResearchOutput = ctx["research_output"]
        brief: BugBrief = ctx["bug_brief"]

        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-qa",
            permission_mode="plan",
            allowed_tools=["Read", "Bash"],  # NEVER Edit/Write
            setting_sources=["project"],
        )

        criteria_json = json.dumps(
            [c.model_dump() for c in brief.acceptance_criteria]
        )
        # The dispatcher builds its own JSON-output prompt; pass the
        # criteria + lint command via the ctx so the subagent can read
        # them after introspecting the brief. We rely on the dispatcher's
        # standard prompt builder to wrap the brief; the additional QA
        # instructions are embedded by storing them on the brief copy
        # via ctx['_qa_instructions'] (subagent prompt logic is in M13
        # subagent definition; this node only configures the dispatch
        # surface).
        ctx["_qa_instructions"] = {
            "criteria": criteria_json,
            "lint_command": self._lint_command,
        }

        report: QAReport = await self._dispatcher.dispatch(
            brief=brief,
            profile=profile,
            output_model=QAReport,
            run_id=ctx["run_id"],
            node_id=self.name,
            cwd=research.worktree_path,
        )
        # Log structured outcome — the flow takes routing decisions on
        # `report.passed`. Returning is intentional even on failure.
        self.logger.info(
            "QA report: passed=%s, lint_passed=%s, n_criteria=%s",
            report.passed,
            report.lint_passed,
            len(report.criterion_results),
        )
        ctx["qa_report"] = report
        return report


__all__ = ["QANode"]
