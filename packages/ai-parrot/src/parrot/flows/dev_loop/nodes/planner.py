"""PlannerNode — document-driven planning for the dev-loop feature-mode flow.

Implements **Module 2** of the FEAT-378 spec. The feature-mode replacement
for :class:`~parrot.flows.dev_loop.nodes.research.ResearchNode`: instead of
log triage + mandatory Jira, it takes a
:class:`~parrot.flows.dev_loop.models.FeatureBrief` document
(brainstorm/proposal/spec), dispatches the ``sdd-planner`` subagent to
generate whatever SDD artifacts are still missing (spec via ``/sdd-spec``,
task index via ``/sdd-task``) and the feature worktree, then derives the
effective dev-agent pool size from the task dependency graph.

Sequence (per spec §3 Module 2):

1. Read ``shared["feature_brief"]`` (a :class:`FeatureBrief`, placed by the
   classifier — TASK-1925).
2. Best-effort graph context via ``DevLoopGraphMemory.build_research_context()``
   — degrades to empty context when no facade was injected (the default).
3. Dispatch ``sdd-planner``; parse the final JSON into :class:`PlannerOutput`.
4. Jira: pass ``FeatureBrief.jira_issue_key`` straight through — this node
   NEVER creates, transitions, or comments on a Jira ticket.
5. Resolve the effective :class:`DevAgentPoolConfig`: the brief's
   ``dev_agents`` wins when set; otherwise size from the width of the first
   :class:`TaskScheduler` wave, capped at ``development_pool_max``.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union

from pydantic import BaseModel

from parrot import conf
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.dispatchers import ClaudeCodeDispatcher
from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    DevAgentPoolConfig,
    DevAgentSpec,
    FeatureBrief,
    PlannerOutput,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node
from parrot.flows.dev_loop.task_scheduler import TaskScheduler


class _PlannerBrief(BaseModel):
    """Local dispatch payload for the ``sdd-planner`` subagent.

    NOT the canonical :class:`FeatureBrief` (TASK-1918) — this carries the
    same document pointer/kind/Jira passthrough fields plus an ephemeral
    ``graph_context`` string that only exists for the lifetime of a single
    dispatch (mirrors ``code_review.py``'s locally-scoped ``_JudgeSynthesisBrief``
    pattern rather than growing the shared models module for a per-dispatch
    concern).
    """

    document_path: str
    document_kind: Literal["brainstorm", "proposal", "spec"]
    jira_issue_key: Optional[str] = None
    graph_context: str = ""


@register_dev_loop_node("dev_loop.planner")
class PlannerNode(DevLoopNode):
    """Feature-mode planning node — document-driven, no Jira creation.

    Args:
        dispatcher: A :class:`ClaudeCodeDispatcher` instance shared by
            every node in the flow.
        development_pool_max: Hard cap on the derived dev-agent pool size
            when sizing from the task-graph wave width (FEAT-323 parity).
        graph_memory: Optional :class:`DevLoopGraphMemory` used to inject
            best-effort graph context into the ``sdd-planner`` dispatch.
            ``None`` (the default) disables the seam entirely.
        name: Node id, default ``"planner"``.
    """

    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        development_pool_max: int = 4,
        graph_memory: Optional[DevLoopGraphMemory] = None,
        name: str = "planner",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)
        object.__setattr__(self, "_pool_max", development_pool_max)
        # FEAT-377 TASK-1915 (G2 seam 2): opt-in graph-memory context
        # injection, built once by the caller via
        # ``DevLoopGraphMemory.from_config()``. None (default) is a strict
        # no-op — same contract as ResearchNode/QANode/DevLoopCloseNode.
        object.__setattr__(self, "_graph_memory", graph_memory)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> PlannerOutput:
        """Run the planning phase. Returns a validated :class:`PlannerOutput`.

        Reads ``feature_brief`` and ``run_id`` from the shared state; writes
        ``planner_output`` and (when a Jira key is present) ``jira_issue_key``.

        Raises:
            ValueError: Cycle in the generated task index's ``depends_on``
                graph (propagated from :class:`TaskScheduler` — no dev
                dispatch follows a failed planning phase).
        """
        shared = self.shared_state(ctx)
        brief: FeatureBrief = shared["feature_brief"]

        graph_context = await self._build_graph_context(brief.document_path)

        planner_brief = _PlannerBrief(
            document_path=brief.document_path,
            document_kind=brief.document_kind,
            jira_issue_key=brief.jira_issue_key,
            graph_context=graph_context,
        )

        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-planner",
            permission_mode="acceptEdits",
            # SlashCommand: the subagent runs /sdd-spec and /sdd-task.
            # Write: it scaffolds spec/task files under sdd/. Read/Grep/Glob
            # for reading the document, Bash for git worktree plumbing.
            allowed_tools=[
                "Read", "Grep", "Glob", "Bash", "Write", "SlashCommand",
            ],
            model="claude-sonnet-4-6",
        )
        dispatch_cwd = os.path.abspath(conf.WORKTREE_BASE_PATH)
        os.makedirs(dispatch_cwd, exist_ok=True)

        planner_out: PlannerOutput = await self._dispatcher.dispatch(
            brief=planner_brief,
            profile=profile,
            output_model=PlannerOutput,
            run_id=shared["run_id"],
            node_id=self.name,
            cwd=dispatch_cwd,
            # FEAT-322: fold dispatch-level events into the run's
            # SessionHost when one is present (same pattern as
            # ResearchNode/DevelopmentNode) — this is how planner
            # completion is recorded via the existing session-state
            # mechanisms, no bespoke action needed here.
            session_host=shared.get("session_host"),
        )

        # Jira passthrough only — this node NEVER creates a Jira issue.
        if not planner_out.jira_issue_key and brief.jira_issue_key:
            planner_out = planner_out.model_copy(
                update={"jira_issue_key": brief.jira_issue_key}
            )
        if planner_out.jira_issue_key:
            shared["jira_issue_key"] = planner_out.jira_issue_key

        pool_cfg = await self._resolve_pool(brief, planner_out)
        planner_out = planner_out.model_copy(update={"suggested_pool": pool_cfg})

        shared["planner_output"] = planner_out
        # Compat bridge (code-review finding, post-TASK-1925): every
        # downstream node reused from the bug/revision topologies
        # (DevelopmentNode, SynthesisNode, QANode, FeedbackRouterNode) reads
        # the mandatory ``shared["research_output"]`` (a ResearchOutput) —
        # feature-mode never populated it, so every real run KeyError'd at
        # the very next node. PlannerOutput carries the same
        # spec/feat/branch/worktree/repo/jira fields ResearchNode's output
        # does, so bridge it here rather than touching four already-shared
        # node bodies (``log_excerpts`` defaults to ``[]``, matching a bug
        # run before ResearchNode's own log-excerpt gathering runs).
        shared["research_output"] = ResearchOutput(
            jira_issue_key=planner_out.jira_issue_key or "",
            spec_path=planner_out.spec_path,
            feat_id=planner_out.feat_id,
            branch_name=planner_out.branch_name,
            worktree_path=planner_out.worktree_path,
            repo_path=planner_out.repo_path,
        )
        return planner_out

    # ------------------------------------------------------------------
    # Internal — graph context (FEAT-377/B, optional)
    # ------------------------------------------------------------------

    @staticmethod
    def _document_query(document_path: str) -> str:
        """Derive a retrieval query from an SDD document path.

        :class:`FeatureBrief` carries no ``summary`` to retrieve on (unlike
        :class:`WorkBrief`), so the document's slug is the query: e.g.
        ``sdd/proposals/devloop-enhancement.brainstorm.md`` ->
        ``"devloop enhancement"``.

        Args:
            document_path: The ``FeatureBrief.document_path``.

        Returns:
            A whitespace-separated query string (possibly empty).
        """
        stem = Path(document_path).stem  # drops the trailing '.md'
        # Drop a phase suffix ('.brainstorm' / '.proposal' / '.spec').
        slug = stem.rsplit(".", 1)[0] if "." in stem else stem
        return slug.replace("-", " ").replace("_", " ").strip()

    async def _build_graph_context(self, document_path: str) -> str:
        """Best-effort graph context via ``DevLoopGraphMemory`` (FEAT-377 G2).

        Mirrors ``ResearchNode``'s seam: the facade is injected (built once
        by the caller via ``DevLoopGraphMemory.from_config()``), never
        constructed here — ``DevLoopGraphMemory.__init__`` is keyword-only
        and its docstring mandates ``from_config``.

        Args:
            document_path: The ``FeatureBrief.document_path`` to build
                context around.

        Returns:
            The graph context string, or ``""`` when the facade is
            disabled or found nothing.
        """
        if self._graph_memory is None:
            return ""
        query = self._document_query(document_path)
        if not query:
            return ""
        context = await self._graph_memory.build_research_context(query)
        return context or ""

    # ------------------------------------------------------------------
    # Internal — dev-agent pool sizing (FEAT-323 parity)
    # ------------------------------------------------------------------

    async def _resolve_pool(
        self, brief: FeatureBrief, planner_out: PlannerOutput
    ) -> DevAgentPoolConfig:
        """Resolve the effective :class:`DevAgentPoolConfig`.

        Brief override wins; otherwise size from the width of the first
        :class:`TaskScheduler` wave, capped at ``development_pool_max``. A
        single task (or no ``depends_on`` edges at all) naturally degrades
        to a width-1 wave — i.e. a single agent.

        Args:
            brief: The input :class:`FeatureBrief`.
            planner_out: The subagent's :class:`PlannerOutput` (supplies
                ``task_index_path`` / ``worktree_path`` / ``feat_id``).

        Returns:
            The resolved :class:`DevAgentPoolConfig`.

        Raises:
            ValueError: Cycle in the ``depends_on`` graph (propagated from
                :class:`TaskScheduler`).
        """
        if brief.dev_agents:
            self.logger.info(
                "Pool sizing for %s: using brief override (%d agent spec(s)).",
                planner_out.feat_id, len(brief.dev_agents),
            )
            return DevAgentPoolConfig(agents=list(brief.dev_agents))

        feature_slug = Path(planner_out.task_index_path).stem
        scheduler = await asyncio.to_thread(
            TaskScheduler.from_worktree, planner_out.worktree_path, feature_slug
        )
        if scheduler is None:
            self.logger.info(
                "No readable per-spec task index at %s for %s; defaulting "
                "to a single-agent pool.",
                planner_out.task_index_path, planner_out.feat_id,
            )
            return DevAgentPoolConfig(
                agents=[DevAgentSpec(agent="claude-code", count=1)]
            )

        wave = scheduler.next_wave()
        width = max(1, len(wave))
        count = min(width, self._pool_max)
        self.logger.info(
            "Pool sizing for %s: wave-1 width=%d, capped at "
            "development_pool_max=%d -> count=%d",
            planner_out.feat_id, width, self._pool_max, count,
        )
        return DevAgentPoolConfig(
            agents=[DevAgentSpec(agent="claude-code", count=count)]
        )


__all__ = ["PlannerNode"]
