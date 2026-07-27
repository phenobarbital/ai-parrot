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

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
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

        profile = ClaudeCodeDispatchProfile(
            subagent=None,
            system_prompt_override=_SYNTHESIS_SYSTEM_PROMPT,
            permission_mode="acceptEdits",
            allowed_tools=["Read", "Grep", "Glob", "Bash", "Write", "Edit"],
            setting_sources=["project"],
        )
        brief = _SynthesisBrief(
            worktree_path=research.worktree_path,
            files_changed=development.files_changed,
            commit_shas=development.commit_shas,
            summary=development.summary,
            worker_count=len(development.worker_summaries),
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


__all__ = ["SynthesisNode"]
