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
    CriterionResult,
    ManualCriterion,
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

        Manual criteria (``kind="manual"``) are filtered out before
        dispatch — the deterministic subagent only sees executable
        criteria — and re-appended afterwards as ``passed=True`` results
        with their text in ``QAReport.notes`` for the human reviewer.

        The node returns the report whether ``passed`` is ``True`` or
        ``False``. The flow factory routes the failure path elsewhere;
        the *node* never raises on ``passed=False``.
        """
        research: ResearchOutput = ctx["research_output"]
        brief: BugBrief = ctx["bug_brief"]

        manual: List[ManualCriterion] = [
            c for c in brief.acceptance_criteria
            if isinstance(c, ManualCriterion)
        ]
        executable: List[AcceptanceCriterion] = [
            c for c in brief.acceptance_criteria
            if not isinstance(c, ManualCriterion)
        ]

        if executable:
            profile = ClaudeCodeDispatchProfile(
                subagent="sdd-qa",
                permission_mode="plan",
                allowed_tools=["Read", "Bash"],  # NEVER Edit/Write
                setting_sources=["project"],
            )
            qa_brief = _QABrief(
                acceptance_criteria=executable,
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
        else:
            # All criteria are manual — skip the dispatch entirely.
            report = QAReport(
                passed=True,
                criterion_results=[],
                lint_passed=True,
                lint_output="(skipped: no executable criteria)",
                notes="No executable acceptance criteria; manual review only.",
            )

        if manual:
            report = self._merge_manual_results(report, manual)

        self.logger.info(
            "QA report: passed=%s, lint_passed=%s, n_executable=%s, n_manual=%s",
            report.passed,
            report.lint_passed,
            len(executable),
            len(manual),
        )
        ctx["qa_report"] = report
        return report

    @staticmethod
    def _merge_manual_results(
        report: QAReport, manual: List[ManualCriterion]
    ) -> QAReport:
        """Append synthesized ``passed=True`` results for each manual criterion.

        Manual criteria don't gate the flow; they surface in the Jira
        ticket description (via ``ResearchNode._build_description``) and
        in the QA report's ``notes`` block so the human reviewer signs
        off as part of the PR review.
        """
        synthesized = [
            CriterionResult(
                name=m.name,
                kind="manual",
                exit_code=0,
                duration_seconds=0.0,
                stdout_tail="",
                stderr_tail="",
                passed=True,
            )
            for m in manual
        ]
        merged_results = list(report.criterion_results) + synthesized
        manual_block = "\n".join(f"- {m.name}: {m.text}" for m in manual)
        existing_notes = report.notes or ""
        sep = "\n\n" if existing_notes else ""
        new_notes = (
            f"{existing_notes}{sep}Manual verification required:\n{manual_block}"
        )
        return report.model_copy(
            update={
                "criterion_results": merged_results,
                "notes": new_notes,
            }
        )


__all__ = ["QANode"]
