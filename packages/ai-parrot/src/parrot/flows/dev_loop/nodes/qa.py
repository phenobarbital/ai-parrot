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

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from parrot.bots.flow.node import Node
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import (
    AcceptanceCriterion,
    BugBrief,
    ClaudeCodeDispatchProfile,
    QAReport,
    ResearchOutput,
)


_DEFAULT_LINT_COMMAND = "ruff check . && mypy --no-incremental"


class _QABrief(BaseModel):
    """Internal brief shape passed to the ``sdd-qa`` subagent.

    Bundles the upstream ``BugBrief.acceptance_criteria`` together with
    the configurable lint command so the subagent has everything it
    needs in a single JSON payload (the dispatcher's ``_build_prompt``
    serializes the brief as the prompt body).
    """

    acceptance_criteria: List[AcceptanceCriterion] = Field(..., min_length=1)
    lint_command: str
    worktree_path: str
    summary: str = ""


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

        # Compose a QA-specific brief that the dispatcher will serialize
        # into the prompt body. This is what the spec means by "given a
        # list of AcceptanceCriterion and a worktree path".
        qa_brief = _QABrief(
            acceptance_criteria=brief.acceptance_criteria,
            lint_command=self._lint_command,
            worktree_path=research.worktree_path,
            summary=brief.summary,
        )

        report: QAReport = await self._dispatcher.dispatch(
            brief=qa_brief,
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
