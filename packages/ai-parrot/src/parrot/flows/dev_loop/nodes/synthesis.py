"""SynthesisNode — post-merge reconciliation owner for the feature-mode flow.

Implements **Module 3** of the FEAT-378 spec. The explicit "reduce →
synthesize" step of the multi-worker diamond: after :class:`DevelopmentNode`
merges the sub-worktrees (FEAT-323 ``SubWorktreeManager.merge_sequential``),
this node dispatches an agent in the now-integrated worktree to reconcile
inter-worker inconsistencies (interfaces, imports, duplications) and run the
integration test suite, committing any reconciliation adjustments it makes.

Resolved design decision (spec §2): a separate node — own telemetry, own
``on_error`` edge, explicit owner of the merge point — rather than a phase
bolted onto ``DevelopmentNode``.

**Skip guard.** Reconciliation only has subject matter when at least two
workers' sub-worktrees were actually merged. A single-agent run, a pool
collapsed to one seat by ``_collapse_for_single_task``, or any run with
``isolation_mode="shared"`` (no sub-worktrees are created, so
``SubWorktreeManager.merge_sequential`` never runs) reaches this node with
nothing to reconcile — and the dispatch below is not cheap when it has
nothing to find: run-459dd2f8 burned 9m06s / 40 turns / $1.30 hunting for
inter-worker seams that could not exist, because the prompt asserted a merge
that never happened. :meth:`SynthesisNode.execute` now short-circuits that
case with a synthetic report, which also makes the prompt's "multiple
workers ... already merged" premise true by construction on every path that
still dispatches.

Note this node is NOT the run's test gate — ``QANode`` is. The pytest step
below verifies the *merge*, not the feature.

No dedicated subagent prompt file: unlike ``sdd-research``/``sdd-qa``/
``sdd-planner``, the reconciliation brief is short and fully described by
``system_prompt_override`` (``ClaudeCodeDispatchProfile.subagent=None``
falls back to a generic session per its own docstring, models.py:519-527) —
this mirrors how one-off inline dispatches elsewhere in the dev-loop are
built rather than adding a fifth ``_subagent_data/*.md`` file for a task
this narrowly scoped.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from parrot import conf
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.dispatchers import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    DevelopmentOutput,
    ResearchOutput,
    SynthesisReport,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node

_SYNTHESIS_SYSTEM_PROMPT = """\
You are the **synthesis phase** of the AI-Parrot dev-loop feature-mode flow.
Multiple dev-agent workers have each completed their assigned tasks in
isolated sub-worktrees, which have already been merged sequentially back
into the integrated feature worktree you are now running in (the merge
itself already happened — you do NOT run any git-merge commands).

Your job, scoped ONLY to reconciliation:

1. Review inter-worker consistency: mismatched interfaces, duplicate or
   conflicting implementations, imports that no longer resolve, and any
   other seams left by combining independently-developed changes.
2. Run the project's integration test suite (``pytest``) in this worktree.
3. If you find reconcilable issues, fix them and commit the adjustments
   to the current branch. Keep adjustments strictly to reconciliation —
   this is NOT a full code review (a QA judge panel reviews the change
   next); do not relitigate individual workers' implementation choices.

## Output Contract

Emit a single JSON object as your **final** assistant turn (no markdown
fences, no prose around it):

```json
{
  "consistent": true,
  "adjustments": ["Fixed import of X in Y", "..."],
  "summary": "Short summary of what was reconciled (or why not)."
}
```

Set ``consistent`` to ``false`` when integration pytest still fails, or an
inconsistency could not be resolved, after your attempt — do not paper
over an unresolved conflict by reporting ``true``.
"""


class _SynthesisBrief(BaseModel):
    """Local dispatch payload for the inline synthesis session.

    Not a canonical dev-loop model — this is a per-dispatch summary of the
    merged :class:`DevelopmentOutput` the reconciliation agent needs as
    starting context, mirroring the locally-scoped brief pattern used by
    ``code_review.py``'s ``_JudgeSynthesisBrief`` and ``planner.py``'s
    ``_PlannerBrief``.
    """

    worktree_path: str
    files_changed: List[str] = Field(default_factory=list)
    commit_shas: List[str] = Field(default_factory=list)
    summary: str = ""
    worker_count: int = 0
    merge_performed: bool = False


@register_dev_loop_node("dev_loop.synthesis")
class SynthesisNode(DevLoopNode):
    """Post-merge reconciliation node — dispatches in the integrated worktree.

    Args:
        dispatcher: A :class:`ClaudeCodeDispatcher` instance shared by
            every node in the flow.
        name: Node id, default ``"synthesis"``.
    """

    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        name: str = "synthesis",
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
    ) -> SynthesisReport:
        """Dispatch the reconciliation session and return the report.

        Reads ``research_output`` (for the integrated worktree path — the
        shared-state key every dev-loop node keys off, feature-mode
        included per TASK-1925's topology bridge) and
        ``development_output`` from shared state; writes
        ``synthesis_report``.

        When no sub-worktree merge happened — a single-agent run, a pool
        collapsed to one seat, or ``isolation_mode="shared"`` — the
        dispatch is skipped entirely and a synthetic
        ``SynthesisReport(consistent=True)`` is published instead. See
        the module docstring for why an unconditional dispatch is
        expensive precisely when it has nothing to do.

        Raises:
            Exception: Any dispatch/parse failure from the underlying
                dispatcher propagates unmodified — this node never
                degrades a synthesis failure to a passing result.
            RuntimeError: When the agent itself reports
                ``SynthesisReport.consistent=False`` after its attempt.
                Both cases are meant to route to ``failure_handler`` via
                the flow's ``on_error`` edge (wired in TASK-1925).
        """
        shared = self.shared_state(ctx)
        research: ResearchOutput = shared["research_output"]
        development: DevelopmentOutput = shared["development_output"]

        worker_count = len(development.worker_summaries)
        if not development.merge_performed or worker_count <= 1:
            return self._skip(shared, research, development, worker_count)

        profile = ClaudeCodeDispatchProfile(
            subagent=None,
            system_prompt_override=_SYNTHESIS_SYSTEM_PROMPT,
            permission_mode="acceptEdits",
            allowed_tools=["Read", "Grep", "Glob", "Bash", "Write", "Edit"],
            setting_sources=["project"],
            # Cost guard: reconciliation is a bounded task, and an
            # unbounded session is how a 40-turn seam hunt happens. The
            # cap surfaces as a DispatchExecutionError naming it, which
            # routes to failure_handler like any other dispatch failure.
            max_turns=conf.DEV_LOOP_SYNTHESIS_MAX_TURNS or None,
        )
        brief = _SynthesisBrief(
            worktree_path=research.worktree_path,
            files_changed=development.files_changed,
            commit_shas=development.commit_shas,
            summary=development.summary,
            worker_count=worker_count,
            merge_performed=development.merge_performed,
        )

        self.logger.info(
            "Dispatching synthesis reconciliation in %s (%d files changed "
            "by %d worker(s))",
            research.worktree_path, len(development.files_changed),
            len(development.worker_summaries),
        )

        report: SynthesisReport = await self._dispatcher.dispatch(
            brief=brief,
            profile=profile,
            output_model=SynthesisReport,
            run_id=shared["run_id"],
            node_id=self.name,
            cwd=research.worktree_path,
            # FEAT-322: fold dispatch-level events into the run's
            # SessionHost when one is present (same pattern as every
            # other dev-loop node).
            session_host=shared.get("session_host"),
        )

        shared["synthesis_report"] = report

        if not report.consistent:
            self.logger.error(
                "Synthesis reconciliation reported inconsistent for %s: %s",
                research.worktree_path, report.summary,
            )
            raise RuntimeError(
                f"SynthesisNode: reconciliation left the worktree "
                f"inconsistent — {report.summary}"
            )

        return report

    # ------------------------------------------------------------------
    # Skip path
    # ------------------------------------------------------------------

    def _skip(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        development: DevelopmentOutput,
        worker_count: int,
    ) -> SynthesisReport:
        """Publish a synthetic report for a run with no merge to reconcile.

        ``consistent=True`` here is not a claim that the code is good — it
        is the accurate statement that there were no inter-worker seams to
        reconcile, which is what this node measures. Verification of the
        change itself belongs to ``QANode``.

        Args:
            shared: The run's shared state (``synthesis_report`` is written).
            research: Upstream research output (worktree path, for logs).
            development: The merged development output being skipped over.
            worker_count: Number of worker summaries on ``development``.

        Returns:
            A ``SynthesisReport`` with ``consistent=True`` and a summary
            naming the reason the dispatch was skipped.
        """
        reason = (
            f"no sub-worktree merge happened "
            f"(merge_performed={development.merge_performed}, "
            f"worker_count={worker_count})"
        )
        self.logger.info(
            "Skipping synthesis reconciliation for %s: %s — nothing to reconcile.",
            research.worktree_path,
            reason,
        )
        if shared.get("skip_qa"):
            # Synthesis used to be the de-facto (and, with skip_qa on, the
            # only) test run. Skipping it while QA is bypassed means this
            # run executes no tests at all — say so instead of letting the
            # bundle read green.
            self.logger.warning(
                "Synthesis skipped while skip_qa is enabled — this run "
                "executes no test suite at all."
            )
        report = SynthesisReport(
            consistent=True,
            adjustments=[],
            summary=f"Synthesis skipped: {reason}.",
        )
        shared["synthesis_report"] = report
        return report


__all__ = ["SynthesisNode"]
