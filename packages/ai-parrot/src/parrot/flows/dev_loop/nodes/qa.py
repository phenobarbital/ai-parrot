"""QANode — sdd-qa dispatch in plan mode + pluggable code-review gate.

Implements **Module 7** (FEAT-129/132) and its FEAT-270 extension. Dispatches
the ``sdd-qa`` subagent under ``permission_mode="plan"`` with no edit/write
tools so the deterministic QA pass is strictly read-only. The subagent runs
each acceptance criterion as a subprocess (deterministic — exit code is the
source of truth, not LLM judgement; spec G6) and runs lint, then returns a
:class:`QAReport`.

The code-review gate (FEAT-250, extended by FEAT-270) is additive and
pluggable: it delegates to an :class:`AbstractCodeReviewDispatcher` (Claude,
Codex, or Gemini) which is allowed to fix issues it finds and commit the
fixes to the worktree branch. When the reviewer reports modified files, the
deterministic QA pass re-runs to confirm the fix didn't regress anything.

The node returns the report regardless of ``passed`` — the flow factory
(TASK-886) decides routing via a :class:`FlowTransition`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    ClaudeCodeReviewDispatcher,
)
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
    """Brief passed to the code-review dispatcher (FEAT-250 / FEAT-270).

    Bundles the acceptance criteria the change must satisfy with the path to
    review and the issue summary, so the reviewer can judge the diff against
    the criteria + the project's standards in a single JSON payload.
    """

    acceptance_criteria: List[AcceptanceCriterion]
    worktree_path: str
    summary: str = ""
    jira_issue_key: str = ""


@register_dev_loop_node("dev_loop.qa")
class QANode(DevLoopNode):
    """Fourth node — runs deterministic acceptance verification."""

    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        lint_command: Optional[str] = None,
        codereview_dispatcher: Optional[AbstractCodeReviewDispatcher] = None,
        name: str = "qa",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)
        object.__setattr__(self, "_lint_command", lint_command or _DEFAULT_LINT_COMMAND)
        # Backward compat: if no reviewer dispatcher is supplied, wrap the
        # existing development dispatcher in a ClaudeCodeReviewDispatcher so
        # zero-config callers keep working unchanged (FEAT-270).
        if codereview_dispatcher is None:
            codereview_dispatcher = ClaudeCodeReviewDispatcher(dispatcher=dispatcher)
        object.__setattr__(self, "_codereview_dispatcher", codereview_dispatcher)

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

        report = await self._run_deterministic_qa(
            shared, research, brief, executable
        )
        deterministic_passed = report.passed

        # FEAT-250 G4 / FEAT-270: additive code-review gate. A run passes QA
        # only when the deterministic criteria/lint AND the qualitative
        # review both pass. The reviewer may fix issues it finds and commit
        # the fixes to the worktree branch (FEAT-270); when it does, the
        # deterministic pass re-runs to confirm the fix didn't regress.
        cr_passed, cr_findings, files_modified = await self._run_code_review(
            shared, research, brief
        )
        cr_skipped = any(
            f.startswith(_CODE_REVIEW_SKIP_PREFIX) for f in cr_findings
        )

        if files_modified:
            self.logger.info(
                "Code review modified %s — re-running deterministic QA",
                files_modified,
            )
            report = await self._run_deterministic_qa(
                shared, research, brief, executable
            )
            deterministic_passed = report.passed

        if manual:
            report = self._merge_manual_results(report, manual)

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
            "code_review_ran=%s, lint_passed=%s, n_executable=%s, n_manual=%s, "
            "files_modified=%s",
            report.passed,
            deterministic_passed,
            cr_passed,
            not cr_skipped,
            report.lint_passed,
            len(executable),
            len(manual),
            files_modified,
        )
        shared["qa_report"] = report
        return report

    # ------------------------------------------------------------------
    # Deterministic QA dispatch
    # ------------------------------------------------------------------

    async def _run_deterministic_qa(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        brief: BugBrief,
        executable: List[AcceptanceCriterion],
    ) -> QAReport:
        """Dispatch the read-only ``sdd-qa`` gate (or synthesize a report).

        Used both for the initial deterministic pass and for the
        review-fix-rerun loop (FEAT-270) — same subagent, same profile, same
        brief shape; only the worktree contents may have changed between
        calls (the reviewer's fix commit).
        """
        if not executable:
            # All criteria are manual — skip the dispatch entirely.
            return QAReport(
                passed=True,
                criterion_results=[],
                lint_passed=True,
                lint_output="(skipped: no executable criteria)",
                notes="No executable acceptance criteria; manual review only.",
            )
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
        return await self._dispatcher.dispatch(
            brief=qa_brief,
            profile=profile,
            output_model=QAReport,
            run_id=shared["run_id"],
            node_id=self.name,
            cwd=research.worktree_path,
        )

    # ------------------------------------------------------------------
    # Code-review gate (FEAT-250, pluggable dispatcher since FEAT-270)
    # ------------------------------------------------------------------

    async def _run_code_review(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        brief: BugBrief,
    ) -> tuple[bool, List[str], List[str]]:
        """Delegate to the configured code-review dispatcher.

        Returns ``(passed, findings, files_modified)``. A dispatch error
        never raises and never blocks the flow on infra grounds — the
        dispatcher itself degrades to
        ``CodeReviewVerdict(passed=True, findings=["code-review could not
        run: …"])`` so the deterministic gate remains the hard guarantee
        (FEAT-250 G4).
        """
        review_cwd = research.repo_path or research.worktree_path
        review_brief = _CodeReviewBrief(
            acceptance_criteria=list(brief.acceptance_criteria),
            worktree_path=review_cwd,
            summary=brief.summary,
            jira_issue_key=research.jira_issue_key,
        )
        verdict = await self._codereview_dispatcher.review(
            brief=review_brief,
            run_id=shared["run_id"],
            node_id=self.name,
            cwd=review_cwd,
        )
        findings = [f.message for f in verdict.findings]
        return verdict.passed, findings, list(verdict.files_modified)

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
