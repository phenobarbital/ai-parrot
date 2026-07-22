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
    ResearchOutput,
    TaskScopedBrief,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node
from parrot.flows.dev_loop.task_scheduler import TaskScheduler
from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager

DispatcherBuilder = Callable[[DevAgentSpec], Tuple[DevLoopCodeDispatcher, BaseModel]]


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
            name: Node id.
        """
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)
        object.__setattr__(self, "_dispatch_profile", dispatch_profile)
        object.__setattr__(self, "_pool_config", pool_config)
        object.__setattr__(self, "_dispatcher_builder", dispatcher_builder)
        object.__setattr__(self, "_pool_max", pool_max)

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

        pool_cfg = self._resolve_pool_config(shared)
        if pool_cfg is None:
            return await self._execute_single(shared, research)
        if self._dispatcher_builder is None:
            self.logger.warning(
                "Pool config present but no dispatcher_builder was configured "
                "on DevelopmentNode; degrading to single-agent."
            )
            return await self._execute_single(shared, research)

        return await self._execute_pool(shared, research, pool_cfg)

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

    async def _execute_pool(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        pool_cfg: DevAgentPoolConfig,
    ) -> DevelopmentOutput:
        """Orchestrate the multi-agent pool: scheduler, waves, aggregation.

        Args:
            shared: The flow's shared state dict.
            research: The upstream research output.
            pool_cfg: The resolved pool configuration.

        Returns:
            The aggregated :class:`DevelopmentOutput`.

        Raises:
            ValueError: Cycle in ``depends_on`` (propagated from the scheduler).
            SubWorktreeMergeError: Unresolvable merge conflict in 'isolated' mode.
            RuntimeError: Every dispatchable task ended up incomplete.
        """
        # Index discovery + parsing are small local filesystem reads; keep
        # them off the event loop to honour the async-first rule.
        feature_slug = await asyncio.to_thread(
            self._find_feature_slug, research.worktree_path, research.feat_id
        )
        scheduler = (
            await asyncio.to_thread(
                TaskScheduler.from_worktree, research.worktree_path, feature_slug
            )
            if feature_slug is not None
            else None
        )
        if scheduler is None:
            self.logger.warning(
                "No readable per-spec task index found for %s under %s; "
                "degrading to single-agent.",
                research.feat_id,
                research.worktree_path,
            )
            return await self._execute_single(shared, research)

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

        wave_results: List[WaveResult] = []
        try:
            while True:
                wave = scheduler.next_wave()
                if not wave:
                    break

                result = await pool.run_wave(
                    wave, research=research, run_id=run_id, cwd_for=_cwd_for
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
