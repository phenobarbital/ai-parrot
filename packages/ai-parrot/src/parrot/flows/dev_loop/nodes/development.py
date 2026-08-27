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
from parrot.flows.dev_loop.dispatchers import DevLoopCodeDispatcher
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    QAReport,
    ResearchOutput,
    TaskScopedBrief,
    WorkerSummary,
)
from parrot.flows.dev_loop.nodes.base import (
    DevLoopNode,
    condense_qa_failure,
    register_dev_loop_node,
    transition_issue_with_candidates,
)
from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler
from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager

DispatcherBuilder = Callable[[DevAgentSpec], Tuple[DevLoopCodeDispatcher, BaseModel]]


def should_fan_out(wave: List[TaskRef], pool_cfg: DevAgentPoolConfig) -> bool:
    """Check whether the first wave actually benefits from parallelism.

    A configured dev-agent pool is not automatically worth fanning out
    into: a straight dependency chain (every wave size 1) gains nothing
    from parallel workers.  This is a pure, no-LLM decision used as an
    **advisory log hint** — it no longer gates pool-vs-single dispatch.
    When a pool is configured, the pool path always runs; this function
    only tells callers whether true parallelism will occur.

    Args:
        wave: The first dispatchable wave (``TaskScheduler.next_wave()``,
            called before any task is marked done/failed).
        pool_cfg: The resolved pool configuration.

    Returns:
        ``True`` only when the wave has 2 or more independent tasks AND
        the pool has more than one effective worker slot — i.e. fanning
        out could actually run tasks in parallel.
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
        jira_toolkit: Any = None,
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
            jira_toolkit: Optional Jira toolkit for transitioning the
                ticket to "In Progress" at the start of development.
            name: Node id.
        """
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)
        object.__setattr__(self, "_dispatch_profile", dispatch_profile)
        object.__setattr__(self, "_pool_config", pool_config)
        object.__setattr__(self, "_dispatcher_builder", dispatcher_builder)
        object.__setattr__(self, "_pool_max", pool_max)
        object.__setattr__(self, "_jira", jira_toolkit)
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

        # Transition ticket to "In Progress" before dispatching work.
        issue_key = research.jira_issue_key
        if issue_key and self._jira and not shared.get("skip_jira", False):
            try:
                await transition_issue_with_candidates(
                    self._jira,
                    issue_key,
                    ["In Progress"],
                    logger=self.logger,
                )
            except Exception:  # noqa: BLE001
                pass

        await self._check_plan_approval(shared, research)
        research = self._with_prior_work_context(shared, research)
        research = self._with_repair_feedback(shared, research)

        pool_cfg = self._resolve_pool_config(shared)
        if pool_cfg is None:
            return await self._execute_single(shared, research)
        if self._dispatcher_builder is None:
            self.logger.warning(
                "Pool config present but no dispatcher_builder was configured "
                "on DevelopmentNode; degrading to single-agent."
            )
            return await self._execute_single(shared, research, pool_cfg=pool_cfg)

        scheduler = await self._build_scheduler(research)
        if scheduler is None:
            self.logger.warning(
                "No readable per-spec task index found for %s under %s; "
                "degrading to single-agent.",
                research.feat_id,
                research.worktree_path,
            )
            return await self._execute_single(shared, research, pool_cfg=pool_cfg)

        first_wave = scheduler.next_wave()
        if not should_fan_out(first_wave, pool_cfg):
            effective_slots = sum(spec.count for spec in pool_cfg.agents)
            self.logger.info(
                "should_fan_out(wave=%d task(s), pool_slots=%d) -> False; "
                "pool will dispatch tasks sequentially for %s.",
                len(first_wave),
                effective_slots,
                research.feat_id,
            )

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

        Whether the gate is required is resolved **per run** (FEAT-412):
        an explicit ``shared["require_plan_approval"]`` (``True`` *or*
        ``False``) wins over the constructor flag, so a UI toggle can turn
        the gate on/off for a single run without rebuilding the flow (the
        server passes it through ``DevLoopRunner.run(extra_shared=...)``).
        When the key is absent — or present as ``None`` — the
        constructor flag applies, so every pre-FEAT-412 call site behaves
        byte-identically.

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
        # FEAT-412: per-run override. Read with an absent-vs-explicit-False
        # distinction (NOT truthiness): a run that explicitly sets False must
        # suppress a gate the constructor flag would have opened, while an
        # absent key (or an explicit None) must fall back to that flag.
        override = shared.get("require_plan_approval")
        required = (
            self._require_plan_approval if override is None else bool(override)
        )
        if not required or shared.get("_plan_gate_checked"):
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
    # Prior-work context (worktree reuse)
    # ------------------------------------------------------------------

    @staticmethod
    def _with_prior_work_context(
        shared: Dict[str, Any], research: ResearchOutput
    ) -> ResearchOutput:
        """Inject prior-work context when reusing a worktree.

        When ``ResearchNode`` detects an existing worktree with prior
        commits, it stores a ``prior_work_context`` dict in shared
        state. This method folds a concise summary into
        ``research.log_excerpts`` so the sdd-worker's prompt includes
        what already exists — preventing it from repeating work.

        Consumed once: the key is popped so QA-repair re-entries
        (which also call this path) don't re-inject stale context.
        """
        prior = shared.pop("prior_work_context", None)
        if not prior:
            return research

        commits = prior.get("commits", [])
        diff_stat = prior.get("diff_stat", "")
        uncommitted = prior.get("uncommitted_stat", "")

        lines = [
            "[PRIOR WORK — worktree reused from a previous run]",
            f"Branch: {prior.get('branch', '?')}",
            f"Commits since merge-base: {prior.get('commit_count', 0)}",
        ]
        if commits:
            lines.append("Recent commits:")
            for c in commits[:15]:
                lines.append(f"  {c}")
            if len(commits) > 15:
                lines.append(f"  ... and {len(commits) - 15} more")
        if diff_stat:
            lines.append(f"Diff stat:\n{diff_stat}")
        if uncommitted:
            lines.append(f"Uncommitted changes:\n{uncommitted}")
        lines.append(
            "IMPORTANT: Review the existing code in the worktree BEFORE "
            "making changes. If work is already done for a task, verify "
            "and commit it — do NOT redo it from scratch."
        )

        note = "\n".join(lines)
        return research.model_copy(
            update={"log_excerpts": [note, *research.log_excerpts]}
        )

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
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        pool_cfg: Optional[DevAgentPoolConfig] = None,
    ) -> DevelopmentOutput:
        """Dispatch exactly one dev agent.

        FEAT-466: when a pool config resolved but the pool path was not
        reachable (no readable per-spec task index — the normal case for a
        hotfix, which reserves no ids), this path must still run on the
        backend/model the OPERATOR declared, not on the server's
        env-configured default. Falling back to ``self._dispatcher`` silently
        substituted the operator's choice.

        Args:
            shared: The flow's shared state dict.
            research: The upstream research output.
            pool_cfg: The resolved pool config, when one resolved. ``None``
                means no pool was declared and the legacy env dispatcher is
                correct.

        Returns:
            The validated :class:`DevelopmentOutput`, carrying one
            ``WorkerSummary`` describing the backend/model actually used.
        """
        dispatcher = self._dispatcher
        profile = self._dispatch_profile
        spec: Optional[DevAgentSpec] = None

        if pool_cfg is not None and self._dispatcher_builder is not None:
            spec = pool_cfg.agents[0]  # min_length=1 -> always safe
            if len(pool_cfg.agents) > 1 or spec.count > 1:
                self.logger.warning(
                    "Pool declared %d spec(s)/%d replica(s) but this run is "
                    "single-agent; using only %s/%s.",
                    len(pool_cfg.agents),
                    spec.count,
                    spec.agent,
                    spec.model or "<backend default>",
                )
            dispatcher, profile = self._dispatcher_builder(spec)  # sync call
            self.logger.info(
                "Single-agent dispatch honouring declared dev agent %s/%s.",
                spec.agent,
                spec.model or "<backend default>",
            )
        elif pool_cfg is not None:
            self.logger.warning(
                "Pool declared (%s) but no dispatcher_builder is configured; "
                "falling back to the env-configured dispatcher. The operator's "
                "selection is NOT being honoured.",
                ", ".join(
                    f"{s.agent}/{s.model or 'default'}" for s in pool_cfg.agents
                ),
            )

        profile = profile or ClaudeCodeDispatchProfile(
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

        dev_out: DevelopmentOutput = await dispatcher.dispatch(
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

        # Record what actually ran, so a substitution is auditable on the
        # run bundle. This ONLY applies when a declared pool spec was
        # actually materialized via the dispatcher_builder: appending here
        # unconditionally would return a *copy* of ``dev_out`` (breaking
        # object identity) on the legacy env-dispatcher path — the exact
        # path ``test_no_pool_exact_current_behavior`` and
        # ``test_no_dispatcher_builder_degrades_to_single`` assert must stay
        # byte-identical to pre-FEAT-466 behaviour. A labelling failure must
        # never fail a successful dispatch.
        if spec is not None:
            try:
                dev_out = dev_out.model_copy(
                    update={
                        "worker_summaries": [
                            *dev_out.worker_summaries,
                            WorkerSummary(
                                worker_id=f"{self.name}.single",
                                agent=spec.agent,
                                model=spec.model
                                or self._env_model_name(profile),
                                summary="single-agent dispatch",
                            ),
                        ]
                    }
                )
            except Exception:
                self.logger.warning(
                    "Could not record WorkerSummary for the single-agent "
                    "dispatch.",
                    exc_info=True,
                )

        shared["development_output"] = dev_out
        return dev_out

    @staticmethod
    def _env_model_name(profile: Any) -> str:
        """Best-effort model label pulled from a dispatch profile.

        Profiles differ per backend; this stays defensive rather than
        assuming a specific profile class.
        """
        return getattr(profile, "model", "") or ""

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
        if not feat_id:
            # FEAT-466: hotfix runs carry feat_id == "" and have no per-spec
            # task index. Returning None here (rather than scanning) keeps us
            # from matching an unrelated index whose feature_id key is absent
            # — json .get() returns None, and None == "" is False, but a file
            # with an explicit "feature_id": "" would match.
            return None
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
