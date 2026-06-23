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

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from parrot import conf
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
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
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node


_DEFAULT_LINT_COMMAND = "ruff check . && mypy --no-incremental"

# Prefix of the synthetic finding emitted when the code-review gate could not
# run (infra error). Used to detect a *skipped* (vs. genuinely passed) review
# so the skip is surfaced loudly instead of masquerading as a clean review.
_CODE_REVIEW_SKIP_PREFIX = "code-review could not run:"


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


class _CodeReviewBrief(BaseModel):
    """Brief passed to the ``sdd-codereview`` subagent (FEAT-250).

    Bundles the acceptance criteria the change must satisfy with the path to
    review and the issue summary, so the reviewer can judge the diff against
    the criteria + the project's standards in a single JSON payload.
    """

    acceptance_criteria: List[AcceptanceCriterion]
    worktree_path: str
    summary: str = ""
    jira_issue_key: str = ""


class _CodeReviewVerdict(BaseModel):
    """Structured verdict emitted by the ``sdd-codereview`` subagent.

    Backward-tolerant defaults: a malformed/empty verdict is treated as a
    pass so an infra hiccup never blocks the flow (the deterministic gate is
    the hard guarantee; code-review is additive).
    """

    passed: bool = True
    findings: List[str] = Field(default_factory=list)
    summary: str = ""


@register_dev_loop_node("dev_loop.qa")
class QANode(DevLoopNode):
    """Fourth node — runs deterministic acceptance verification."""

    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        lint_command: Optional[str] = None,
        codereview_model: Optional[str] = None,
        name: str = "qa",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)
        object.__setattr__(self, "_lint_command", lint_command or _DEFAULT_LINT_COMMAND)
        object.__setattr__(
            self,
            "_codereview_model",
            codereview_model or conf.DEV_LOOP_CODEREVIEW_MODEL,
        )

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> QAReport:
        """Dispatch ``sdd-qa`` and return the :class:`QAReport`.

        Manual criteria (``kind="manual"``) are filtered out before
        dispatch — the deterministic subagent only sees executable
        criteria — and re-appended afterwards as ``passed=True`` results
        with their text in ``QAReport.notes`` for the human reviewer.

        The node returns the report whether ``passed`` is ``True`` or
        ``False``. The flow factory routes the failure path elsewhere;
        the *node* never raises on ``passed=False``.
        """
        shared = self.shared_state(ctx)
        research: ResearchOutput = shared["research_output"]
        brief: BugBrief = shared["bug_brief"]

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
                run_id=shared["run_id"],
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

        # FEAT-250 G4: additive code-review gate. A run passes QA only when the
        # deterministic criteria/lint AND the qualitative review both pass.
        deterministic_passed = report.passed
        cr_passed, cr_findings = await self._run_code_review(
            shared, research, brief
        )
        cr_skipped = any(
            f.startswith(_CODE_REVIEW_SKIP_PREFIX) for f in cr_findings
        )
        update: Dict[str, Any] = {
            "passed": deterministic_passed and cr_passed,
            "code_review_passed": cr_passed,
            "code_review_findings": cr_findings,
        }
        if cr_skipped:
            # Degrade-to-pass (FEAT-250 G4) keeps the deterministic gate as the
            # hard guarantee, but a skipped review must NOT read as green: here
            # ``code_review_passed=True`` means "not reviewed", not "reviewed
            # clean". Make that loud in the log AND in the report's notes.
            self.logger.warning(
                "Code-review gate did NOT run for %s — QA is passing on the "
                "DETERMINISTIC gate only; code_review_passed=True means "
                "'not reviewed', not 'reviewed clean'. Detail: %s",
                research.jira_issue_key or research.feat_id,
                "; ".join(cr_findings),
            )
            skip_note = "⚠ Code-review gate SKIPPED (infra) — change NOT reviewed."
            existing_notes = report.notes or ""
            sep = "\n\n" if existing_notes else ""
            update["notes"] = f"{existing_notes}{sep}{skip_note}"
        report = report.model_copy(update=update)

        self.logger.info(
            "QA report: passed=%s, deterministic=%s, code_review=%s, "
            "code_review_ran=%s, lint_passed=%s, n_executable=%s, n_manual=%s",
            report.passed,
            deterministic_passed,
            cr_passed,
            not cr_skipped,
            report.lint_passed,
            len(executable),
            len(manual),
        )
        shared["qa_report"] = report
        return report

    # ------------------------------------------------------------------
    # Code-review gate (FEAT-250)
    # ------------------------------------------------------------------

    async def _run_code_review(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        brief: BugBrief,
    ) -> tuple[bool, List[str]]:
        """Dispatch the read-only ``sdd-codereview`` gate.

        Returns ``(passed, findings)``. A dispatch error never raises and
        never blocks the flow on infra grounds — it degrades to
        ``(True, ["code-review could not run: …"])`` so the deterministic
        gate remains the hard guarantee.
        """
        review_cwd = research.repo_path or research.worktree_path
        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-codereview",
            permission_mode="plan",
            allowed_tools=["Read", "Bash", "Grep", "Glob"],  # NEVER Edit/Write
            setting_sources=["project"],
            model=self._codereview_model,
        )
        review_brief = _CodeReviewBrief(
            acceptance_criteria=list(brief.acceptance_criteria),
            worktree_path=review_cwd,
            summary=brief.summary,
            jira_issue_key=research.jira_issue_key,
        )
        try:
            verdict: _CodeReviewVerdict = await self._dispatcher.dispatch(
                brief=review_brief,
                profile=profile,
                output_model=_CodeReviewVerdict,
                run_id=shared["run_id"],
                node_id=self.name,
                cwd=review_cwd,
            )
            return verdict.passed, list(verdict.findings)
        except Exception as exc:  # noqa: BLE001 - never raise from QA
            self.logger.warning(
                "Code-review dispatch failed (not blocking): %s", exc
            )
            return True, [f"code-review could not run: {exc}"]

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
