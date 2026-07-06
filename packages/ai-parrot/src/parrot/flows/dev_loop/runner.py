"""DevLoopRunner — orchestrator-side hosting for the dev-loop flow.

Closes spec G5's orchestrator half: the dispatcher already caps
concurrent Claude Code dispatches (``CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES``);
this runner caps concurrent *flow runs* with an ``asyncio.Semaphore``
sized by ``FLOW_MAX_CONCURRENT_RUNS``.

Responsibilities:

- mint (or accept) the ``run_id`` and seed the :class:`FlowContext`
  (``shared_data['bug_brief']`` / ``['work_brief']`` / ``['run_id']``);
- bind the run_id to the flow's :class:`FlowEventPublisher` so
  node-lifecycle events land on ``flow:{run_id}:flow``;
- track active runs (``active_runs`` / ``is_active``).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional, Set

from navconfig.logging import logging

from parrot import conf
from parrot.bots.flows import AgentsFlow
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.result import FlowResult
from parrot.flows.dev_loop.definition import build_dev_loop_definition
from parrot.flows.dev_loop.factories import build_dev_loop_node_factories
from parrot.flows.dev_loop.flow import (
    FlowEventPublisher,
    _NullAgentRegistry,
    _qa_failed,
    _qa_passed,
)
from parrot.flows.dev_loop.models import (
    ResearchOutput,
    RevisionBrief,
    ShellCriterion,
    WorkBrief,
)


def build_dev_loop_revision_flow(
    *,
    dispatcher: Any,
    jira_toolkit: Any,
    git_toolkit: Any,
    redis_url: str,
    codereview_dispatcher: Optional[Any] = None,
    name: str = "dev-loop-revision",
    publish_flow_events: bool = True,
) -> AgentsFlow:
    """Build the short revision-mode ``AgentsFlow`` (FEAT-250 G6).

    Mirrors ``build_dev_loop_flow``'s declarative-materialize-then-explicit
    execution: the nodes come from ``build_dev_loop_definition(revision=True)``
    via the node factories, and the graph runs in explicit-edge mode (OR-join
    on the ``failure_handler`` fan-in). Topology: ``development → qa →
    (pass) revision_handoff → close`` / ``(fail) failure_handler``.
    """
    definition = build_dev_loop_definition(revision=True)
    factories = build_dev_loop_node_factories(
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        redis_url=redis_url,
        git_toolkit=git_toolkit,
        codereview_dispatcher=codereview_dispatcher,
    )
    staged = AgentsFlow.from_definition(
        definition,
        agent_registry=_NullAgentRegistry(),
        node_factories=factories,
    )
    nodes = staged._materialize_nodes()

    run_id_holder: Dict[str, str] = {}
    publisher = (
        FlowEventPublisher(redis_url, run_id_holder) if publish_flow_events else None
    )
    flow = AgentsFlow(name=name, on_node_event=publisher)
    flow._run_id_holder = run_id_holder  # type: ignore[attr-defined]
    flow._event_publisher = publisher  # type: ignore[attr-defined]
    flow._dev_loop_definition = definition  # type: ignore[attr-defined]

    for node in nodes.values():
        flow.add_node(node)

    flow.add_edge("development", "qa")
    flow.add_edge("qa", "revision_handoff", predicate=_qa_passed)
    flow.add_edge("qa", "failure_handler", predicate=_qa_failed)
    flow.add_edge("revision_handoff", "close")
    for source in ("development", "qa", "revision_handoff"):
        flow.add_edge(source, "failure_handler", condition="on_error")

    return flow


class DevLoopRunner:
    """Hosts dev-loop flow runs behind a global concurrency cap.

    Args:
        flow: The :class:`AgentsFlow` built by ``build_dev_loop_flow``.
        max_concurrent_runs: Cap on simultaneously executing runs.
            Defaults to ``conf.FLOW_MAX_CONCURRENT_RUNS``.
    """

    def __init__(
        self,
        flow: AgentsFlow,
        *,
        max_concurrent_runs: Optional[int] = None,
        dispatcher: Optional[Any] = None,
        jira_toolkit: Optional[Any] = None,
        git_toolkit: Optional[Any] = None,
        redis_url: Optional[str] = None,
        codereview_dispatcher: Optional[Any] = None,
    ) -> None:
        self.flow = flow
        self.max_concurrent_runs = int(
            max_concurrent_runs
            if max_concurrent_runs is not None
            else conf.FLOW_MAX_CONCURRENT_RUNS
        )
        self._semaphore = asyncio.Semaphore(self.max_concurrent_runs)
        self._active: Set[str] = set()
        # Deps needed to build the revision-mode flow on demand (FEAT-250 G6).
        # Optional so the legacy ``DevLoopRunner(flow)`` construction keeps
        # working; ``run_revision`` raises a clear error when they are absent.
        self._dispatcher = dispatcher
        self._jira_toolkit = jira_toolkit
        self._git_toolkit = git_toolkit
        self._redis_url = redis_url
        self._codereview_dispatcher = codereview_dispatcher
        # Lazily-built, reused revision flow (fixed topology — built once).
        self._rev_flow: Optional[AgentsFlow] = None
        self.logger = logging.getLogger("parrot.dev_loop.runner")

    # ── Introspection ─────────────────────────────────────────────────────

    @property
    def active_runs(self) -> Set[str]:
        """Run IDs currently executing (copy)."""
        return set(self._active)

    def is_active(self, run_id: str) -> bool:
        """True while *run_id* is executing."""
        return run_id in self._active

    # ── Execution ─────────────────────────────────────────────────────────

    async def run(
        self,
        brief: WorkBrief,
        *,
        run_id: Optional[str] = None,
        initial_task: str = "",
        extra_shared: Optional[Dict[str, Any]] = None,
    ) -> FlowResult:
        """Execute one dev-loop run for *brief*, respecting the run cap.

        Blocks (cooperatively) while ``max_concurrent_runs`` runs are
        already in flight.

        Args:
            brief: The validated :class:`WorkBrief` / ``BugBrief`` to process.
            run_id: Optional externally-minted run identifier; one is
                generated (``run-<hex8>``) when omitted.
            initial_task: Optional human-readable task line stored as the
                context's ``initial_task``.
            extra_shared: Extra entries merged into ``shared_data``.

        Returns:
            The aggregated :class:`FlowResult` for the run.
        """
        rid = run_id or f"run-{uuid.uuid4().hex[:8]}"
        shared: Dict[str, Any] = {
            "bug_brief": brief,    # legacy key — nodes read this
            "work_brief": brief,   # forward-compat name
            "run_id": rid,
        }
        if extra_shared:
            shared.update(extra_shared)

        ctx = FlowContext(
            initial_task=initial_task or brief.summary,
            shared_data=shared,
        )

        async with self._semaphore:
            self._active.add(rid)
            # Point the flow's event publisher at this run's stream.
            holder = getattr(self.flow, "_run_id_holder", None)
            if isinstance(holder, dict):
                holder["run_id"] = rid
            self.logger.info(
                "Starting dev-loop run %s (%d/%d active)",
                rid, len(self._active), self.max_concurrent_runs,
            )
            try:
                result = await self.flow.run_flow(ctx)
            finally:
                self._active.discard(rid)

        self.logger.info(
            "Dev-loop run %s finished status=%s", rid, result.status
        )
        return result

    async def run_revision(
        self,
        brief: RevisionBrief,
        *,
        run_id: Optional[str] = None,
    ) -> FlowResult:
        """Execute a revision-mode run for *brief* (FEAT-250 G6).

        Builds the short revision flow (``development → qa → revision_handoff →
        close`` / fail → ``failure_handler``), seeds the shared state to reuse
        the existing clone + branch (no Intent/BugIntake/Research/clone), and
        runs it. ``RevisionHandoffNode`` pushes to the existing branch and
        comments the same PR — it never opens a new PR.

        Args:
            brief: The :class:`RevisionBrief` describing the existing clone,
                branch, PR and reviewer feedback.
            run_id: Optional externally-minted id (``rev-<hex8>`` otherwise).

        Returns:
            The aggregated :class:`FlowResult` for the revision run.

        Raises:
            RuntimeError: If the runner was constructed without the deps needed
                to build the revision flow.
        """
        if not all(
            (self._dispatcher, self._jira_toolkit, self._git_toolkit, self._redis_url)
        ):
            raise RuntimeError(
                "run_revision requires the runner to be constructed with "
                "dispatcher, jira_toolkit, git_toolkit and redis_url."
            )

        rid = run_id or f"rev-{uuid.uuid4().hex[:8]}"
        # Build the revision flow once (fixed topology) and reuse it — fresh
        # node FSMs are materialized per run by the scheduler, like ``run``.
        if self._rev_flow is None:
            self._rev_flow = build_dev_loop_revision_flow(
                dispatcher=self._dispatcher,
                jira_toolkit=self._jira_toolkit,
                git_toolkit=self._git_toolkit,
                redis_url=self._redis_url,
                codereview_dispatcher=self._codereview_dispatcher,
            )
        rev_flow = self._rev_flow

        # Seed a synthetic ResearchOutput so Development/QA run against the
        # existing clone without re-cloning. v1 note: the original acceptance
        # criteria are not carried on RevisionBrief, so QA re-runs a lint gate
        # by default; the reviewer feedback is surfaced in shared state and the
        # context's initial_task.
        research = ResearchOutput(
            jira_issue_key=brief.jira_issue_key,
            spec_path="",
            feat_id="",
            branch_name=brief.branch,
            worktree_path=brief.repo_path,
            repo_path=brief.repo_path,
        )
        work = WorkBrief(
            kind="bug",
            summary=f"Revision for {brief.jira_issue_key or brief.branch}",
            description=brief.feedback,
            affected_component="(revision)",
            # NOTE: the revision graph skips BugIntakeNode, so this command is
            # NOT run through ACCEPTANCE_CRITERION_ALLOWLIST. It is injected by
            # the runner (trusted internal input, run via exec — no shell), so
            # the allowlist bypass is intentional and safe.
            acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
            escalation_assignee="",
            reporter="",
        )
        shared: Dict[str, Any] = {
            "run_id": rid,
            "mode": "revision",
            "research_output": research,
            "bug_brief": work,
            "work_brief": work,
            "repo_path": brief.repo_path,
            "branch": brief.branch,
            "pr_number": brief.pr_number,
            "repository": brief.repository,
            "jira_issue_key": brief.jira_issue_key,
            "feedback": brief.feedback,
            "head_sha": brief.head_sha,
        }
        ctx = FlowContext(
            initial_task=brief.feedback or "revision", shared_data=shared
        )

        async with self._semaphore:
            self._active.add(rid)
            holder = getattr(rev_flow, "_run_id_holder", None)
            if isinstance(holder, dict):
                holder["run_id"] = rid
            self.logger.info(
                "Starting dev-loop REVISION run %s (PR #%s, branch %s)",
                rid, brief.pr_number, brief.branch,
            )
            try:
                result = await rev_flow.run_flow(ctx)
            finally:
                self._active.discard(rid)

        self.logger.info(
            "Dev-loop revision run %s finished status=%s", rid, result.status
        )
        return result


__all__ = ["DevLoopRunner", "build_dev_loop_revision_flow"]
