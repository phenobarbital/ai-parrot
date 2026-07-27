"""DevelopmentNode — sdd-worker dispatch, single-agent or multi-agent pool.

Implements **Module 6** of FEAT-323 (parallel development node), extending
the original **Module 6** of FEAT-129/FEAT-250 (single ``sdd-worker``
dispatch).

Config cascade (FEAT-323): ``WorkBrief.dev_agents`` (via
``shared["work_brief"]`` / legacy ``shared["bug_brief"]``) takes priority
over a ``pool_config`` injected at construction time (resolved from env by
the server/factories, TASK-1859); when neither is present the node runs
the **exact** single-dispatch path from before this feature — same default
profile, same ``node_id``, same ``cwd``.

The dispatcher's R4 cwd-safety check verifies that any dispatch ``cwd``
(including sub-worktrees created for 'isolated' mode) lives under
``conf.WORKTREE_BASE_PATH``. This node trusts that check and does not
duplicate it, beyond building sub-worktree paths through
:class:`SubWorktreeManager`, which enforces the same invariant.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel

from parrot import conf
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.agent_pool import DevAgentPool, WaveResult, aggregate_outputs
from parrot.flows.dev_loop.dispatcher import DevLoopCodeDispatcher
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    QAReport,
    ResearchOutput,
    TaskScopedBrief,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode, condense_qa_failure, register_dev_loop_node
from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler
from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager

DispatcherBuilder = Callable[[DevAgentSpec], Tuple[DevLoopCodeDispatcher, BaseModel]]


def should_fan_out(wave: List[TaskRef], pool_cfg: DevAgentPoolConfig) -> bool:
    """Deterministic parallelism stop rule (FEAT-377 TASK-1913 — G4).

    A configured dev-agent pool is not automatically worth fanning out
    into: a straight dependency chain (every wave size 1) gains nothing
    from parallel workers and only adds pool-orchestration overhead. This
    is a pure, no-LLM decision — everything needed lives in the two
    arguments.

    Args:
        wave: The first dispatchable wave (``TaskScheduler.next_wave()``,
            called before any task is marked done/failed).
        pool_cfg: The resolved pool configuration.

    Returns:
        ``True`` only when the wave has 2 or more independent tasks AND
        the pool has more than one effective worker slot (``sum(spec.count
        for spec in pool_cfg.agents)``) — i.e. fanning out could actually
        run tasks in parallel. ``False`` otherwise, including when the
        wave is empty (nothing to schedule at all).
    """
    if len(wave) < 2:
        return False
    effective_slots = sum(spec.count for spec in pool_cfg.agents)
    return effective_slots > 1


@register_dev_loop_node("dev_loop.development")
class DevelopmentNode(DevLoopNode):
    """Third node — dispatches the implementation phase to ``sdd-worker``(s)."""

    def __init__(
        self,
        *,
        dispatcher: DevLoopCodeDispatcher,
        dispatch_profile: Optional[Any] = None,
        pool_config: Optional[DevAgentPoolConfig] = None,
        dispatcher_builder: Optional[DispatcherBuilder] = None,
        pool_max: int = 4,
        require_plan_approval: bool = False,
        name: str = "development",
    ) -> None:
        """Initialise the node.

        Args:
            dispatcher: The single-agent dispatcher (unchanged behaviour
                when no pool config resolves).
            dispatch_profile: The single-agent dispatch profile override.
            pool_config: An already-resolved pool config (e.g. parsed from
                ``DEV_LOOP_DEV_AGENTS`` by the server/factories, TASK-1859).
                A ``WorkBrief.dev_agents`` found in shared state at
                ``execute()`` time always takes priority over this.
            dispatcher_builder: ``(DevAgentSpec) -> (dispatcher, profile)``
                callable used to materialize pool workers and the conflict
                resolver's claude-code fallback. Required for the pool path;
                its absence degrades to single-agent with a warning.
            pool_max: Hard cap on total pool workers (``DEV_LOOP_DEV_POOL_MAX``).
            require_plan_approval: FEAT-377 TASK-1916 (G5) opt-in — when
                ``True`` AND a ``SessionHost`` is present, opens a
                ``plan_approval`` gate on this node's FIRST entry (before
                any dispatch) and awaits its resolution. Mirrors
                ``DeploymentHandoffNode.require_deployment_approval``'s
                shape/fail-open-on-no-host semantics; placed here (the
                first node after ``ResearchNode``) because the engine has
                no external "pause between two nodes" hook — every
                existing gate is opened and awaited FROM WITHIN the node
                that would otherwise act next, which is what actually
                blocks the scheduler's dispatch of that node's own work.
            name: Node id.
        """
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)
        object.__setattr__(self, "_dispatch_profile", dispatch_profile)
        object.__setattr__(self, "_pool_config", pool_config)
        object.__setattr__(self, "_dispatcher_builder", dispatcher_builder)
        object.__setattr__(self, "_pool_max", pool_max)
        object.__setattr__(self, "_require_plan_approval", require_plan_approval)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> DevelopmentOutput:
        """Dispatch ``sdd-worker`` inside the upstream worktree.

        Args:
            ctx: Flow context whose shared state must contain ``"run_id"``
                and ``"research_output"`` (a :class:`ResearchOutput`
                produced by ``ResearchNode``).
            deps: Dependency results (unused — payloads travel in the
                shared state).
            **kwargs: Extra execution context (ignored).

        Returns:
            The validated :class:`DevelopmentOutput` (single-agent output,
            or the pool-aggregated output — same shape either way).

        Raises:
            ValueError: Propagated from ``TaskScheduler`` on a
                ``depends_on`` cycle.
            SubWorktreeMergeError: Propagated when 'isolated' mode hits an
                unresolvable merge conflict.
            RuntimeError: When every dispatchable task in the pool path
                ends up incomplete (the flow must not proceed to QA).
        """
        shared = self.shared_state(ctx)
        research: ResearchOutput = shared["research_output"]
        await self._check_plan_approval(shared, research)
        research = self._with_repair_feedback(shared, research)

        pool_cfg = self._resolve_pool_config(shared)
        if pool_cfg is None:
            return await self._execute_single(shared, research)
        if self._dispatcher_builder is None:
            self.logger.warning(
                "Pool config present but no dispatcher_builder was configured "
                "on DevelopmentNode; degrading to single-agent."
            )
            return await self._execute_single(shared, research)

        scheduler = await self._build_scheduler(research)
        if scheduler is None:
            self.logger.warning(
                "No readable per-spec task index found for %s under %s; "
                "degrading to single-agent.",
                research.feat_id,
                research.worktree_path,
            )
            return await self._execute_single(shared, research)

        # FEAT-377 TASK-1913 (G4): deterministic parallelism stop rule — a
        # configured pool still degrades to single-agent when the task
        # graph doesn't actually offer any parallelism (e.g. a straight
        # dependency chain, every wave size 1).
        first_wave = scheduler.next_wave()
        if not should_fan_out(first_wave, pool_cfg):
            self.logger.info(
                "should_fan_out(wave=%d task(s), pool_slots=%d) -> False; "
                "degrading to single-agent for %s.",
                len(first_wave),
                sum(spec.count for spec in pool_cfg.agents),
                research.feat_id,
            )
            return await self._execute_single(shared, research)

        return await self._execute_pool(shared, research, pool_cfg, scheduler)

    # ------------------------------------------------------------------
    # plan_approval HITL gate (FEAT-377 TASK-1916 — G5)
    # ------------------------------------------------------------------

    async def _check_plan_approval(
        self, shared: Dict[str, Any], research: ResearchOutput
    ) -> None:
        """Open and await the ``plan_approval`` gate on this run's FIRST
        entry into this node (opt-in via ``require_plan_approval``).

        No-op when the flag is off, when this run already checked the
        gate (a QA-repair-loop re-entry must never re-open it — the plan
        was already approved), or — matching
        ``DeploymentHandoffNode.require_deployment_approval``'s fail-open
        legacy fallback — when no ``SessionHost`` is present.

        Args:
            shared: The flow's shared state dict.
            research: The upstream research output (Jira key, spec path).

        Raises:
            RuntimeError: The gate resolved to anything other than
                ``"approved"`` (rejected, or expired with a fail-closed
                policy — this gate is opened with ``on_expiry="approve"``,
                so only an explicit human rejection reaches this branch).
                Any hard error from this node routes to ``failure_handler``
                via the flow's ``on_error`` edge, the same terminate-the-run
                effect a rejected ``deployment_approval`` gate has.
        """
        if not self._require_plan_approval or shared.get("_plan_gate_checked"):
            return
        shared["_plan_gate_checked"] = True

        host = shared.get("session_host")
        if host is None:
            self.logger.warning(
                "DevelopmentNode: require_plan_approval=True but no "
                "session_host in shared state (legacy DevLoopRunner "
                "construction) — proceeding without a plan_approval gate."
            )
            return

        # Lazy import — avoids a runner.py <-> factories.py <-> this module
        # import cycle (runner.py imports factories.py, which imports this
        # module to build the node) — same pattern as
        # deployment_handoff.py's own gate helper.
        from parrot.flows.dev_loop.runner import gate_ttl_for

        task_count = await self._count_tasks(research)
        instructions = (
            f"Jira: {research.jira_issue_key}\n"
            f"Spec: {research.spec_path}\n"
            f"Tasks: {task_count if task_count is not None else 'not yet decomposed'}"
        )
        gate_id, _ = host.open_gate(
            kind="plan_approval",
            node_id=self.name,
            title=f"Approve plan: {research.jira_issue_key}",
            instructions=instructions,
            ttl_seconds=gate_ttl_for("plan_approval"),
            on_expiry="approve",
        )
        gate = await host.wait_gate(gate_id)
        if gate.status != "approved":
            raise RuntimeError(
                f"plan_approval {gate.status} by {gate.resolved_by or 'ttl'}"
            )

    async def _count_tasks(self, research: ResearchOutput) -> Optional[int]:
        """Best-effort total task count from the per-spec index, for the
        gate's instructions text. ``None`` when no index is readable yet
        (e.g. the research subagent hasn't scaffolded tasks)."""
        scheduler = await self._build_scheduler(research)
        if scheduler is None:
            return None
        return len(scheduler._tasks)  # noqa: SLF001 - same-package internal read

    # ------------------------------------------------------------------
    # QA repair-loop re-entry (FEAT-377 TASK-1911)
    # ------------------------------------------------------------------

    def _with_repair_feedback(
        self, shared: Dict[str, Any], research: ResearchOutput
    ) -> ResearchOutput:
        """Bump the attempt counter and carry prior-QA feedback on re-entry.

        Re-entry is detected via a failing ``QAReport`` already in shared
        state (set by ``QANode`` on a previous pass through this run's
        ``qa -> development`` retry edge — TASK-1910). This node OWNS the
        ``qa_attempt`` counter (``QANode`` only reads it to stamp
        ``QAReport.attempt``); a fresh run therefore starts implicitly at
        attempt 1 (``QANode``'s default) without this method ever running.

        Worktree reuse falls out for free: this only augments
        ``log_excerpts`` — ``research.worktree_path`` (and every other
        field) is copied unchanged, and `research` (hence the worktree) is
        never re-derived because the retry edge never re-enters
        ``ResearchNode``.

        Args:
            shared: The flow's shared state dict.
            research: The upstream research output (read fresh each call).

        Returns:
            ``research`` unchanged on a first pass or a passing prior
            report; otherwise a copy with the prior failure condensed into
            ``log_excerpts`` so both dispatch paths' briefs carry it.
        """
        prior_report: Optional[QAReport] = shared.get("qa_report")
        if prior_report is None or prior_report.passed:
            return research
        shared["qa_attempt"] = shared.get("qa_attempt", 1) + 1
        feedback = condense_qa_failure(prior_report)
        note = (
            f"[QA repair-loop feedback — attempt {shared['qa_attempt']}]\n{feedback}"
        )
        return research.model_copy(
            update={"log_excerpts": [*research.log_excerpts, note]}
        )

    # ------------------------------------------------------------------
    # Config cascade
    # ------------------------------------------------------------------

    def _resolve_pool_config(self, shared: Dict[str, Any]) -> Optional[DevAgentPoolConfig]:
        """Resolve the effective pool config: brief > injected > none.

        Args:
            shared: The flow's shared state dict.

        Returns:
            A :class:`DevAgentPoolConfig`, or ``None`` when no pool config
            resolves from either source (single-agent path).
        """
        brief = shared.get("work_brief") or shared.get("bug_brief")
        dev_agents = getattr(brief, "dev_agents", None) if brief is not None else None
        if dev_agents:
            isolation_mode = getattr(brief, "dev_isolation", None) or "shared"
            return DevAgentPoolConfig(agents=dev_agents, isolation_mode=isolation_mode)
        return self._pool_config

    # ------------------------------------------------------------------
    # Single-agent path (byte-identical to the pre-FEAT-323 behaviour)
    # ------------------------------------------------------------------

    async def _execute_single(
        self, shared: Dict[str, Any], research: ResearchOutput
    ) -> DevelopmentOutput:
        """The exact single-dispatch path used before FEAT-323.

        Args:
            shared: The flow's shared state dict.
            research: The upstream research output.

        Returns:
            The validated :class:`DevelopmentOutput`.
        """
        profile = self._dispatch_profile or ClaudeCodeDispatchProfile(
            subagent="sdd-worker",
            permission_mode="acceptEdits",
            allowed_tools=[
                "Read",
                "Edit",
                "Write",
                "Bash",
                "Grep",
                "Glob",
            ],
            setting_sources=["project"],
        )

        dev_out: DevelopmentOutput = await self._dispatcher.dispatch(
            brief=research,
            profile=profile,
            output_model=DevelopmentOutput,
            run_id=shared["run_id"],
            node_id=self.name,
            cwd=research.worktree_path,
            # FEAT-322: fold dispatch-level events (queued/started/message/
            # tool_use/…) into the run's SessionHost when one is present
            # (seeded by DevLoopRunner.run(); absent for nodes invoked
            # outside the runner). `dispatch()` defaults this to None.
            session_host=shared.get("session_host"),
        )
        shared["development_output"] = dev_out
        return dev_out

    # ------------------------------------------------------------------
    # Pool path
    # ------------------------------------------------------------------

    @staticmethod
    def _find_feature_slug(worktree_path: str, feat_id: str) -> Optional[str]:
        """Resolve the per-spec index feature slug by scanning the index dir.

        Never assumes the slug matches any derived name — matches strictly
        on the index file's own ``feature_id`` header field (FEAT-145).

        Args:
            worktree_path: The feature worktree root.
            feat_id: e.g. ``"FEAT-323"`` (``ResearchOutput.feat_id``).

        Returns:
            The ``feature`` slug, or ``None`` if no matching index is found
            (or the index dir does not exist / no file is readable).
        """
        index_dir = Path(worktree_path) / "sdd" / "tasks" / "index"
        if not index_dir.is_dir():
            return None
        for path in sorted(index_dir.glob("*.json")):
            if path.name == "_orphans.json":
                continue
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("feature_id") == feat_id:
                return data.get("feature") or path.stem
        return None

    async def _build_scheduler(self, research: ResearchOutput) -> Optional[TaskScheduler]:
        """Resolve the per-spec index and build a :class:`TaskScheduler`.

        FEAT-377 TASK-1913: split out of ``_execute_pool`` so the
        fan-out decision (``should_fan_out``, computed in ``execute()``
        against this same scheduler's first wave) and the pool-execution
        loop share ONE scheduler instance rather than reading the index
        twice.

        Args:
            research: The upstream research output.

        Returns:
            A :class:`TaskScheduler`, or ``None`` when no readable
            per-spec index is found (caller degrades to single-agent).
        """
        # Index discovery + parsing are small local filesystem reads; keep
        # them off the event loop to honour the async-first rule.
        feature_slug = await asyncio.to_thread(
            self._find_feature_slug, research.worktree_path, research.feat_id
        )
        if feature_slug is None:
            return None
        return await asyncio.to_thread(
            TaskScheduler.from_worktree, research.worktree_path, feature_slug
        )

    async def _execute_pool(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        pool_cfg: DevAgentPoolConfig,
        scheduler: TaskScheduler,
    ) -> DevelopmentOutput:
        """Orchestrate the multi-agent pool: waves, aggregation.

        Args:
            shared: The flow's shared state dict.
            research: The upstream research output.
            pool_cfg: The resolved pool configuration.
            scheduler: The already-built :class:`TaskScheduler` (FEAT-377
                TASK-1913: built once in ``execute()`` for the
                ``should_fan_out`` decision, reused here).

        Returns:
            The aggregated :class:`DevelopmentOutput`.

        Raises:
            ValueError: Cycle in ``depends_on`` (propagated from the scheduler).
            SubWorktreeMergeError: Unresolvable merge conflict in 'isolated' mode.
            RuntimeError: Every dispatchable task ended up incomplete.
        """
        pool = DevAgentPool.build(pool_cfg, self._dispatcher_builder, self._pool_max)
        run_id = shared["run_id"]

        manager: Optional[SubWorktreeManager] = None
        worker_cwds: Dict[str, str] = {}
        if pool_cfg.isolation_mode == "isolated":
            manager = SubWorktreeManager(
                base_worktree=research.worktree_path,
                feature_branch=research.branch_name,
                worktree_base_path=conf.WORKTREE_BASE_PATH,
            )
            for worker in pool.workers:
                worker_cwds[worker.worker_id] = await manager.create(worker.worker_id)

        def _cwd_for(worker_id: str) -> str:
            if manager is not None:
                return worker_cwds[worker_id]
            return research.worktree_path

        async def _resolver(path: str, description: str) -> bool:
            return await self._resolve_conflict(
                path, description, pool=pool, research=research, run_id=run_id
            )

        # FEAT-377 TASK-1912 (G3): on a QA repair-loop redispatch
        # (attempt >= 2 — stamped by `_with_repair_feedback` above), every
        # worker's dispatch in this run uses its `escalation_model` when
        # set, not just an internal within-wave retry.
        escalate = shared.get("qa_attempt", 1) >= 2

        wave_results: List[WaveResult] = []
        try:
            while True:
                wave = scheduler.next_wave()
                if not wave:
                    break

                result = await pool.run_wave(
                    wave, research=research, run_id=run_id, cwd_for=_cwd_for,
                    escalate=escalate,
                )
                wave_results.append(result)

                for task_id in result.completed:
                    scheduler.mark_done(task_id)
                for task_id in result.failed:
                    scheduler.mark_failed(task_id)

                if manager is not None:
                    await manager.merge_sequential(resolver=_resolver)
                    # Propagate this wave's merged output into every
                    # sub-worktree so the next wave's tasks (which may
                    # depend_on a task another worker just finished) build
                    # on the integrated feature branch, not a stale tree.
                    await manager.refresh_all()
        finally:
            if manager is not None:
                await manager.cleanup(keep_on_conflict=True)

        incomplete = [t.id for t in scheduler.failed()] + [t.id for t in scheduler.skipped()]
        total_completed = sum(len(wr.completed) for wr in wave_results)

        if incomplete and total_completed == 0:
            raise RuntimeError(
                f"DevelopmentNode pool: all tasks incomplete for {research.feat_id} "
                f"({incomplete}); not proceeding to QA."
            )

        dev_out = aggregate_outputs(wave_results, incomplete)
        shared["development_output"] = dev_out
        return dev_out

    async def _resolve_conflict(
        self,
        path: str,
        description: str,
        *,
        pool: DevAgentPool,
        research: ResearchOutput,
        run_id: str,
    ) -> bool:
        """Merge-conflict resolver policy: first pool worker, claude-code fallback.

        Dispatches the first worker of the pool into ``path`` (the base
        worktree passed by ``SubWorktreeManager.merge_sequential`` — where
        the actual conflict markers / ``git status`` live, NOT any
        sub-worktree) with a ``TaskScopedBrief`` wrapping the shared
        research output, mirroring how every other pool dispatch is
        briefed — the resolver is expected to inspect ``git status``,
        resolve the conflict markers, and commit, exactly like the
        merge-conflict resolver dispatch described in the spec. If that
        dispatch raises and the first worker is not already
        ``claude-code``, retries once with a dedicated claude-code
        dispatcher built via ``dispatcher_builder``.

        Args:
            path: The base worktree path where the conflict occurred (see
                ``SubWorktreeManager.merge_sequential``'s ``resolver``
                contract).
            description: Human-readable conflict description (unused
                directly here — the resolver agent discovers the conflict
                via ``git status`` in ``path``; kept for logging).
            pool: The active pool (its first worker is the primary resolver).
            research: The shared research output.
            run_id: The flow run id.

        Returns:
            ``True`` if either dispatch succeeded, ``False`` otherwise.
        """
        brief = TaskScopedBrief(research=research, task_id="RESOLVE_MERGE_CONFLICT")
        first_worker = pool.workers[0]

        try:
            await first_worker.dispatcher.dispatch(
                brief=brief,
                profile=first_worker.profile,
                output_model=DevelopmentOutput,
                run_id=run_id,
                node_id="development.resolver",
                cwd=path,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - any dispatch failure triggers fallback/failure
            self.logger.warning(
                "Conflict resolver (%s) failed on %s: %s", first_worker.spec.agent, path, exc
            )

        if first_worker.spec.agent == "claude-code" or self._dispatcher_builder is None:
            return False

        try:
            fallback_dispatcher, fallback_profile = self._dispatcher_builder(
                DevAgentSpec(agent="claude-code")
            )
            await fallback_dispatcher.dispatch(
                brief=brief,
                profile=fallback_profile,
                output_model=DevelopmentOutput,
                run_id=run_id,
                node_id="development.resolver",
                cwd=path,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - fallback failure -> resolver fully failed
            self.logger.warning("Fallback claude-code conflict resolver also failed on %s: %s", path, exc)
            return False


__all__ = ["DevelopmentNode"]
