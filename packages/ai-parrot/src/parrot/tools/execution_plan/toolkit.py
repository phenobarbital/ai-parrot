"""``ExecutionPlanToolkit`` — lets a plain ``BasicAgent`` trigger a deterministic
tool-call DAG (``ExecutionPlan``) through a bounded tool call, with zero LLM
tokens spent while it executes.

This module implements the toolkit's core (spec §3 Module 2): constructor
wiring, the bounded run registry, and the soft-timeout execution path over
``AgentsFlow``. The plan-acquisition front (``plan_execute``/``plan_validate``)
is added by TASK-2184; the plan file store, planner client and
allowlist/catalog layering are added by TASK-2181/2182/2183 respectively.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Mapping, Optional, Sequence, Set, Union

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.checkpoint import (
    CheckpointPersistenceError,
    CheckpointStore,
    FlowCheckpointer,
    FlowLockedError,
    FlowStateSerializer,
    get_checkpoint_store,
)
from parrot.bots.flows.plan import (
    ArtifactRef,
    ExecutionPlan,
    build_manifest,
)
from parrot.bots.flows.plan.validator import ValidationReport
from parrot.registry.registry import AgentRegistry
from parrot.tools.decorators import tool_schema
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.working_memory.task_memory.models import TaskScope

from ..abstract import ToolResult
from .catalog import build_catalog, validate_with_allowlist
from .models import (
    PLAN_RUN_SHARED_KEY,
    PlanArtifactsArgs,
    PlanDelta,
    PlanExecuteArgs,
    PlanRepairArgs,
    PlanStatusArgs,
    PlanValidateArgs,
    PlanResumeArgs,
    PlanRecoveryConfig,
    PlanRecoveryEnvelope,
    PlanRun,
    PlanRunError,
    PlanRunManifest,
    PlanRunMetadata,
    PlanRunSummary,
    RunRecord,
)
from .checkpoint import PlanContinuation, PlanFlow, build_plan_flow, plan_run_projector
from .memory import PlanMemoryBinding, RestoreError
from .planner import PlanAuthoringError, PlanPlanner
from .repair import eligible_repair_nodes, merge_delta, protected_node_ids, validate_delta
from .runs import PlanRunResolver, plan_fingerprint, process_identity, register_plan_checkpoint_types, select_latest
from parrot.bots.flows.flow.definition import FlowDefinition
from .store import PlanFileStore, PlanLoadError

if TYPE_CHECKING:
    from parrot.auth.permission import PermissionContext
    from parrot.tools.working_memory.tool import WorkingMemoryToolkit
    from parrot.tools.working_memory.task_memory.config import TaskMemoryRuntime


class _StructuralError(Exception):
    """Internal signal for a structural (non-manifest) tool-error condition.

    Raised by the arbitration/acquisition helpers and caught at the
    `plan_execute`/`plan_validate` tool boundary — never crosses it.
    """


class ExecutionPlanToolkit(AbstractToolkit):
    """Runs a validated :class:`ExecutionPlan` on ``AgentsFlow`` with no LLM
    tokens in the loop and returns a bounded manifest to the agent.

    One instance is initialized with live dependencies (the FEAT-207
    shared-state toolkit pattern) and shared across every tool call:
    the run registry, plan store and tool catalog all live on ``self``.

    Attributes:
        planner_llm: Raw ``planner_llm`` constructor value, consumed by
            TASK-2183's ``PlanPlanner``.
        plans_dir: Resolved ``Path`` for ``plan_name`` mode, consumed by
            TASK-2181's ``PlanFileStore``.
        allowed_tools: Explicit allowlist, or ``None`` for "all manager
            tools" — consumed by TASK-2182's catalog/allowlist layering.
        soft_timeout: Seconds ``plan_execute`` waits before returning a
            :class:`RunningSummary` instead of the full manifest.
        permission_context: Optional constructor-level default forwarded
            to every plan node's ``ToolManager.execute_tool`` call.
        max_completed_runs: Bound on completed/failed run-registry
            entries; oldest evicted first. In-flight runs are never
            evicted.
        plan_step_mapping: Explicit ``{plan_node_id: domain_step_id}``
            mapping forwarded to every plan node (FEAT-538). Supplying an
            entry is the ONLY way a plan call is attributed to a task
            step: a plan node id is not a step id, and a plan run never
            creates a task or a step by itself.
    """

    name: str = "execution_plan"
    description: str = (
        "Runs a deterministic tool-call DAG (an ExecutionPlan) with zero "
        "LLM tokens spent during execution. Tool payloads never enter the "
        "conversation — only small ArtifactRefs and a bounded manifest "
        "come back."
    )

    def __init__(
        self,
        *,
        tool_manager: Any,
        working_memory: "WorkingMemoryToolkit",
        planner_llm: Union[str, dict, Any, None] = None,
        plans_dir: Union[str, Path, None] = None,
        allowed_tools: Optional[Sequence[str]] = None,
        soft_timeout: float = 60.0,
        permission_context: Optional["PermissionContext"] = None,
        on_node_event: Optional[Callable[..., Any]] = None,
        max_completed_runs: int = 50,
        plan_step_mapping: Optional[Mapping[str, str]] = None,
        recovery: Optional[PlanRecoveryConfig] = None,
        checkpoint_store: Union["CheckpointStore", str, None] = None,
        durable_store: Union["CheckpointStore", str, None] = None,
        task_memory_runtime: Optional["TaskMemoryRuntime"] = None,
        delegates: Optional[Sequence[Any]] = None,
        delegate_trace_sink: Optional[Any] = None,
        allow_delegate_side_effects: bool = False,
        scope: Optional[TaskScope] = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the toolkit with its live dependencies.

        Args:
            tool_manager: Shared ``ToolManager`` — every plan node dispatches
                through it (never ``tool.execute()`` directly).
            working_memory: The SAME ``WorkingMemoryToolkit`` instance the
                analyst agent uses; plan payloads land here.
            planner_llm: Enables ``objective`` mode when set. Same accepted
                formats as bots' ``llm``/``secondary_llm``. Consumed by
                TASK-2183.
            plans_dir: Enables ``plan_name`` mode when set. Consumed by
                TASK-2181.
            allowed_tools: Explicit tool allowlist. ``None`` means every
                tool registered on ``tool_manager`` is allowed. Consumed by
                TASK-2182.
            soft_timeout: Seconds to await a run before returning a
                ``RunningSummary``. Never cancels the run.
            permission_context: Optional default forwarded to
                ``ToolManager.execute_tool`` for every plan node.
            on_node_event: Optional flow-lifecycle listener, forwarded to
                every run's ``AgentsFlow`` in addition to this toolkit's
                own progress-tracking listener.
            max_completed_runs: Bound on completed/failed run-registry
                entries.
            plan_step_mapping: Explicit ``{plan_node_id: domain_step_id}``
                mapping (FEAT-538). ``None`` — the default — leaves every
                plan call task-level with ``plan`` provenance, which is the
                honest answer when nobody has said which step a node is.
            delegates: Ordered ``ToolCallDelegate`` chain; ``[0]`` is primary.
                Owned and closed by :meth:`cleanup`.
            delegate_trace_sink: Opt-in ``DelegateTraceSink`` never persisted
                in checkpoints.
            allow_delegate_side_effects: Host policy; plan text alone can
                never grant delegate side effects.
            **kwargs: Forwarded to :class:`AbstractToolkit`.
        """
        super().__init__(**kwargs)
        self._tool_manager = tool_manager
        self._working_memory = working_memory
        self.planner_llm = planner_llm
        self.plans_dir: Optional[Path] = Path(plans_dir) if plans_dir is not None else None
        self.allowed_tools: Optional[list] = list(allowed_tools) if allowed_tools is not None else None
        self.soft_timeout = soft_timeout
        self.permission_context = permission_context
        self._on_node_event = on_node_event
        self.max_completed_runs = max_completed_runs
        self.plan_step_mapping: Dict[str, str] = dict(plan_step_mapping or {})
        self._delegates: tuple = tuple(delegates or ())
        self._delegate_trace_sink = delegate_trace_sink
        self._allow_delegate_side_effects = allow_delegate_side_effects

        # Run registry (bounded) — toolkit-internal state, never travels
        # through NodeDefinition.config.
        self._runs: Dict[str, RunRecord] = {}
        # Live handles kept OUT of RunRecord (non-serializable).
        self._run_tasks: Dict[str, "asyncio.Task"] = {}
        self._run_contexts: Dict[str, FlowContext] = {}
        # Lazily created, empty AgentRegistry — AgentsFlow.from_definition
        # requires one unconditionally even though a plan can never contain
        # an agent-type node (PlanNode has no agent_ref field at all).
        self._agent_registry: Optional[AgentRegistry] = None
        # FEAT-585 recovery wiring — trusted host inputs, borrowed, no I/O here.
        self.recovery: PlanRecoveryConfig = recovery or PlanRecoveryConfig()
        self._checkpoint_store: Optional[CheckpointStore] = self._resolve_store(checkpoint_store)
        self._durable_store: Optional[CheckpointStore] = self._resolve_store(durable_store)
        self._store_probe: Optional[bool] = None
        self._task_memory_runtime = task_memory_runtime
        self._scope: Optional[TaskScope] = scope
        self._memory_binding = PlanMemoryBinding(
            working_memory,
            runtime=task_memory_runtime,
            scope=scope,
            max_restore_bytes=self.recovery.max_restore_bytes,
        )
        self._plan_runs: Dict[str, PlanRun] = {}
        self._resolver = PlanRunResolver(
            store=self._checkpoint_store,
            durable_store=self._durable_store,
            scope=scope,
            cache=self._plan_runs,
        )

    # ── Internal executor path (spec §3 Module 2) ──────────────────────────

    @staticmethod
    def _resolve_store(arg: Union["CheckpointStore", str, None]) -> Optional[CheckpointStore]:
        """Keep an omitted tier disabled; resolve configured names and instances."""
        return None if arg is None else get_checkpoint_store(arg)

    def _legacy_envelope(self, record: RunRecord) -> PlanRecoveryEnvelope:
        """Build the honest recovery envelope for a pre-checkpoint run."""
        return PlanRecoveryEnvelope(
            run_id=record.run_id,
            root_run_id=record.run_id,
            checkpoint_enabled=False,
            artifact_mode=self._memory_binding.artifact_mode,
            resume_level="none",
            resumable=False,
            recovery_reason="checkpoint_unavailable",
            max_repair_rounds=self.recovery.max_repair_rounds,
        )

    def _error(self, exc: PlanRunError, *, run_id: Optional[str] = None) -> ToolResult:
        """Map a structured resolver error to the agent-facing result shape."""
        result = exc.to_tool_result()
        if exc.code == "unknown_run" and isinstance(result.result, dict):
            result.result["known_run_ids"] = sorted(set(self._plan_runs) | set(self._runs))[:20]
        self.logger.info("plan run error code=%s run_id=%s", exc.code, run_id)
        return result

    async def _resolve_or_legacy(self, run_id: str) -> tuple[Optional[PlanRun], Optional[RunRecord]]:
        """Resolve checkpoint state first, retaining same-process legacy compatibility."""
        try:
            return await self._resolver.resolve(run_id), None
        except PlanRunError as exc:
            record = self._runs.get(run_id)
            if record is not None and exc.code in ("unknown_run", "missing_or_expired", "checkpoint_unavailable"):
                return None, record
            raise

    async def cleanup(self) -> None:
        """Close owned plan-memory resources without closing borrowed stores."""
        for delegate in self._delegates:
            try:
                await delegate.aclose()
            except Exception as exc:  # noqa: BLE001 - close remaining delegates
                self.logger.warning("delegate cleanup failed: %s", exc)
        await self._memory_binding.close()
        await super().cleanup()

    def _validation_kwargs(self) -> Dict[str, Any]:
        """Delegate kwargs for ``validate_with_allowlist`` and ``validate_delta``."""
        return {
            "delegates": self._delegates,
            "allow_delegate_side_effects": self._allow_delegate_side_effects,
        }

    def _flow_delegate_kwargs(self) -> Dict[str, Any]:
        """Delegate kwargs for ``build_plan_flow``."""
        return {**self._validation_kwargs(), "delegate_trace_sink": self._delegate_trace_sink}

    def _planner(self, catalog: Any) -> PlanPlanner:
        """Build the planner, enabling delegate rules only when delegates exist."""
        if not self._delegates:
            return PlanPlanner(self.planner_llm, catalog)
        allowed = self.allowed_tools if self.allowed_tools is not None else self._tool_manager.list_tools()
        safe_tools = [name for name in allowed if getattr(self._tool_manager.get_tool(name), "delegate_safe", False)]
        return PlanPlanner(
            self.planner_llm,
            catalog,
            delegate_safe_tools=safe_tools,
            delegate_max_tools=self._delegates[0].max_tools,
        )

    def _get_agent_registry(self) -> AgentRegistry:
        """Return the cached empty ``AgentRegistry``, creating it once."""
        if self._agent_registry is None:
            self._agent_registry = AgentRegistry()
        return self._agent_registry

    async def _probe_checkpoint_store(self) -> bool:
        """Probe the configured store once without making outages fatal to fresh runs."""
        if self._checkpoint_store is None:
            return False
        if self._store_probe is not None:
            return self._store_probe
        try:
            await asyncio.wait_for(
                self._checkpoint_store.latest("__plan_probe__"),
                timeout=self.recovery.checkpoint_probe_timeout,
            )
            self._store_probe = True
        except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
            self.logger.warning("checkpoint store unreachable (%s); plan runs execute without checkpointing", exc)
            self._store_probe = False
        except Exception as exc:  # noqa: BLE001 - configuration errors are explicit
            raise PlanRunError("checkpoint_unavailable", f"checkpoint store misconfigured: {exc}") from exc
        return self._store_probe

    def _new_run_metadata(
        self, plan: ExecutionPlan, *, source: str, run_id: str, checkpointed: bool
    ) -> PlanRunMetadata:
        """Build the persisted recovery envelope for a newly accepted root run."""
        del checkpointed
        allowed = (
            sorted(self.allowed_tools) if self.allowed_tools is not None else sorted(self._tool_manager.list_tools())
        )
        scope = self._memory_binding.scope
        mode = self._memory_binding.artifact_mode
        return PlanRunMetadata(
            run_id=run_id,
            root_run_id=run_id,
            plan=plan,
            original_plan=plan,
            source=source,
            started_at=datetime.now(timezone.utc),
            scope_key=scope.cache_key() if scope is not None else None,
            allowed_tools=allowed,
            plan_fingerprint=plan_fingerprint(plan),
            artifact_mode=mode,
            process_id=process_identity() if mode == "memory" else None,
            max_repair_rounds=self.recovery.max_repair_rounds,
        )

    async def _run_plan(self, plan: ExecutionPlan, *, source: str) -> ToolResult:
        """Compile, run and bound the response to ``soft_timeout``.

        Callers are responsible for validating ``plan`` first (TASK-2184's
        ``plan_execute``/``plan_validate`` layer) — this method executes
        unconditionally.

        Args:
            plan: A structurally valid :class:`ExecutionPlan`.
            source: ``"objective"`` or ``"plan_name"`` — recorded on the
                run for observability.

        Returns:
            A ``ToolResult`` whose ``result`` is either the full
            ``ExecutionManifest`` (run finished within ``soft_timeout``) or
            a :class:`RunningSummary` (run continues in the background).
        """
        run_id = str(uuid.uuid4())
        try:
            probe_ok = await self._probe_checkpoint_store()
        except PlanRunError as exc:
            return self._error(exc, run_id=run_id)
        checkpointed = probe_ok and plan.metadata.checkpoint and self._checkpoint_store is not None
        try:
            await self._memory_binding.prepare()
        except Exception as exc:  # noqa: BLE001 - activation failure dispatches nothing
            return self._error(
                PlanRunError("artifacts_unavailable", f"plan memory activation failed: {exc}"), run_id=run_id
            )
        metadata = self._new_run_metadata(plan, source=source, run_id=run_id, checkpointed=checkpointed)
        agent_registry = self._get_agent_registry()
        flow = build_plan_flow(
            plan,
            run=metadata,
            tool_manager=self._tool_manager,
            working_memory=self._working_memory,
            agent_registry=agent_registry,
            permission_context=self.permission_context,
            step_mapping=self.plan_step_mapping,
            store=self._checkpoint_store if checkpointed else None,
            durable_store=self._durable_store if checkpointed else None,
            **self._flow_delegate_kwargs(),
        )

        plan_node_ids: Set[str] = {node.id for node in plan.nodes}
        ctx = FlowContext(initial_task=plan.objective, agent_registry=agent_registry)
        ctx.shared_data[PLAN_RUN_SHARED_KEY] = metadata.model_dump(mode="json")
        started_monotonic = time.monotonic()
        record = RunRecord(
            run_id=run_id,
            plan_name=plan.name,
            source=source,
            status="running",
            started_at=datetime.now(timezone.utc),
            nodes_total=len(plan.nodes),
            nodes_done=0,
        )
        self._runs[run_id] = record
        self._run_contexts[run_id] = ctx
        self._plan_runs[run_id] = PlanRun(
            metadata=metadata,
            status="running",
            checkpoint_enabled=checkpointed,
            resume_level=("none" if not checkpointed else self._memory_binding.resume_level_hint),
            resumable=False,
            recovery_reason=None if checkpointed else "checkpoint_unavailable",
        )

        flow.add_node_event_listener(self._make_progress_listener(run_id, plan_node_ids))
        if self._on_node_event is not None:
            flow.add_node_event_listener(self._on_node_event)

        task = asyncio.create_task(self._execute_flow(run_id, flow, plan, ctx, started_monotonic))
        self._run_tasks[run_id] = task

        done, _pending = await asyncio.wait({task}, timeout=self.soft_timeout)
        if task in done:
            # Surface a background-task exception (defensive: _execute_flow
            # already catches everything it can and marks the run "failed").
            exc = task.exception()
            record = self._runs.get(run_id, record)
            if record.manifest is not None:
                run = self._plan_runs[run_id]
                envelope = PlanRecoveryEnvelope(
                    run_id=run_id,
                    root_run_id=run_id,
                    checkpoint_enabled=run.checkpoint_enabled,
                    artifact_mode=metadata.artifact_mode,
                    resume_level=run.resume_level,
                    resumable=run.resumable,
                    recovery_reason=run.recovery_reason,
                    max_repair_rounds=self.recovery.max_repair_rounds,
                )
                manifest = PlanRunManifest(
                    **record.manifest.model_dump(), **envelope.model_dump(), status=record.status
                )
                return ToolResult(status="success", result=manifest.model_dump(mode="json"))
            run = self._plan_runs.get(run_id)
            reason = record.flow_error or (str(exc) if exc is not None else None)
            if run is not None and run.recovery_reason is not None:
                return self._error(PlanRunError(run.recovery_reason, reason or run.recovery_reason), run_id=run_id)
            return ToolResult(
                status="error",
                success=False,
                result=None,
                error=f"Plan run {run_id!r} finished without a manifest" + (f": {reason}" if reason else ""),
            )

        run = self._plan_runs[run_id]
        summary = PlanRunSummary(
            run_id=run_id,
            root_run_id=run_id,
            checkpoint_enabled=checkpointed,
            artifact_mode=metadata.artifact_mode,
            resume_level=run.resume_level,
            resumable=False,
            recovery_reason=run.recovery_reason,
            max_repair_rounds=self.recovery.max_repair_rounds,
            plan_name=plan.name,
            nodes_total=record.nodes_total,
            nodes_done=record.nodes_done,
            uncheckpointed_progress=not checkpointed,
        )
        return ToolResult(status="success", result=summary.model_dump(mode="json"))

    def _make_progress_listener(
        self, run_id: str, plan_node_ids: Set[str]
    ) -> Callable[[str, str, Dict[str, Any]], None]:
        """Build an ``on_node_event`` callback that updates ``nodes_done``.

        Args:
            run_id: The run this listener tracks.
            plan_node_ids: Node ids belonging to the plan (excludes the
                synthetic ``__start__``/``__end__`` sentinels).

        Returns:
            A sync callback matching ``AgentsFlow``'s listener contract.
        """

        def _listener(event: str, node_id: str, _info: Dict[str, Any]) -> None:
            if node_id not in plan_node_ids:
                return
            if event in ("node_completed", "node_failed", "node_skipped"):
                record = self._runs.get(run_id)
                if record is not None:
                    record.nodes_done += 1
                run = self._plan_runs.get(run_id)
                if run is not None:
                    run.nodes_done += 1

        return _listener

    async def _execute_flow(
        self,
        run_id: str,
        flow: PlanFlow,
        plan: ExecutionPlan,
        ctx: FlowContext,
        started_monotonic: float,
    ) -> None:
        """Run ``flow`` to completion and populate the final manifest.

        Runs as a background ``asyncio.Task`` — soft-timeout must NOT
        cancel this. Any failure (per-node or flow-level) is recorded as
        data on the ``RunRecord``, never re-raised: partial failure is
        data, not an exception (spec §1 Goals).
        """
        record = self._runs.get(run_id)
        try:
            await flow.run_flow(ctx)
        except CheckpointPersistenceError as exc:
            self._fail_run(run_id, code="checkpoint_write_failed", message=str(exc), flow=flow)
            return
        except FlowLockedError as exc:
            self._fail_run(run_id, code="run_busy", message=str(exc), flow=flow)
            return
        except Exception as exc:  # noqa: BLE001 - recorded, never re-raised
            self._fail_run(run_id, code="flow_error", message=str(exc), flow=flow)
            return

        refs = []
        for node in plan.nodes:
            value = ctx.results.get(node.id)
            if isinstance(value, ArtifactRef):
                refs.append(value)
                continue
            error = ctx.errors.get(node.id)
            if error is not None:
                # A hard node failure (retry exhaustion, on_item_error="fail")
                # never returns an ArtifactRef; synthesize one so the
                # manifest's counts stay honest instead of silently
                # dropping the node.
                refs.append(ArtifactRef(node_id=node.id, status="error", errors=[str(error)[:300]]))
                continue
            # Neither a result nor a recorded error: the node was never
            # dispatched at all — a hard upstream failure blocked it (the
            # scheduler's AND-join gate only advances past a dependency
            # that reached `completed`; a `mark_failed` dependency leaves
            # dependents un-dispatched, with no "skipped"/"error" event of
            # their own). Without this branch such a node would silently
            # vanish from the manifest instead of showing up as blocked.
            refs.append(
                ArtifactRef(
                    node_id=node.id,
                    status="error",
                    errors=["node never dispatched: blocked by a failed dependency"],
                )
            )

        duration = time.monotonic() - started_monotonic
        manifest = build_manifest(plan, refs, duration_seconds=duration)

        if record is not None:
            record.manifest = manifest
            record.nodes_done = len(refs)
            record.finished_at = datetime.now(timezone.utc)
            if manifest.nodes_failed == 0:
                record.status = "completed"
            elif manifest.nodes_ok > 0 or manifest.nodes_skipped > 0:
                record.status = "partial"
            else:
                record.status = "failed"
        run = self._plan_runs.get(run_id)
        if run is not None:
            run.refs = refs
            run.nodes_done = len(refs)
            run.status = record.status if record is not None else "failed"
            run.resumable = False
            if run.checkpoint_enabled:
                run.recovery_reason = "completed" if run.status == "completed" else "terminal"
            # else: checkpointing was never enabled for this run — keep the
            # "checkpoint_unavailable" reason set at creation (AC-2): a
            # terminal status does not retroactively grant recovery capability.

        self._evict_completed_runs()

    def _fail_run(self, run_id: str, *, code: str, message: str, flow: Any) -> None:
        """Record a flow-level failure on both the legacy and recovery caches."""
        self.logger.error("Plan run %r failed (%s): %s", run_id, code, message[:300])
        record = self._runs.get(run_id)
        if record is not None:
            record.status = "failed"
            record.finished_at = datetime.now(timezone.utc)
            record.flow_error = message[:500]
        run = self._plan_runs.get(run_id)
        if run is not None:
            run.status = "failed"
            run.recovery_reason = code
            run.resumable = False
            run.checkpoint_id = getattr(getattr(flow, "_checkpointer", None), "_last_checkpoint_id", None)
        self._evict_completed_runs()

    def _evict_completed_runs(self) -> None:
        """Evict oldest completed/failed runs beyond ``max_completed_runs``.

        In-flight (``status == "running"``) runs are never evicted.
        """
        finished = [(run_id, rec) for run_id, rec in self._runs.items() if rec.status != "running"]
        overflow = len(finished) - self.max_completed_runs
        if overflow <= 0:
            return

        finished.sort(key=lambda pair: pair[1].finished_at or pair[1].started_at)
        for run_id, _rec in finished[:overflow]:
            self._runs.pop(run_id, None)
            self._run_tasks.pop(run_id, None)
            self._run_contexts.pop(run_id, None)
            self.logger.debug(
                "Evicted completed run %r (max_completed_runs=%d)",
                run_id,
                self.max_completed_runs,
            )

    def _assert_policy(self, run: PlanRun) -> None:
        """Require current policy to retain every tool in the recorded plan."""
        current = set(self.allowed_tools) if self.allowed_tools is not None else set(self._tool_manager.list_tools())
        needed = {name for node in run.metadata.plan.nodes for name in node.tool_names()}
        if not needed <= (set(run.metadata.allowed_tools) & current):
            raise PlanRunError("policy_mismatch", "current tool policy no longer permits every tool this run uses")
        if plan_fingerprint(run.metadata.plan) != run.metadata.plan_fingerprint:
            raise PlanRunError("policy_mismatch", "effective plan fingerprint does not match the recorded run")

    def _resume_flow_factory(
        self, run: PlanRun, *, store: Optional[CheckpointStore]
    ) -> Callable[[FlowDefinition], PlanFlow]:
        """Rebuild a resumed plan with fresh live dependencies and permissions."""

        def _factory(_definition: FlowDefinition) -> PlanFlow:
            return build_plan_flow(
                run.metadata.plan,
                run=run.metadata,
                tool_manager=self._tool_manager,
                working_memory=self._working_memory,
                agent_registry=self._get_agent_registry(),
                permission_context=self.permission_context,
                step_mapping=self.plan_step_mapping,
                store=store,
                durable_store=self._durable_store,
                **self._flow_delegate_kwargs(),
            )

        return _factory

    def _seed_context(self, run: PlanRun) -> FlowContext:
        """Seed a fresh context with the validated persisted plan envelope."""
        ctx = FlowContext(initial_task=run.metadata.plan.objective, agent_registry=self._get_agent_registry())
        ctx.shared_data[PLAN_RUN_SHARED_KEY] = run.metadata.model_dump(mode="json")
        return ctx

    async def _run_continuation(self, run: PlanRun, flow: PlanFlow, *, continuation: PlanContinuation) -> ToolResult:
        """Run a resumed flow and retain its lease until terminal completion."""

        async def _finish() -> ToolResult:
            try:
                await flow.run_flow()
                continuation.raise_if_lease_lost()
                terminal = await self._resolver.resolve(run.metadata.run_id)
                envelope = self._resolver.envelope(terminal)
                if terminal.status == "running":
                    summary = PlanRunSummary(
                        **envelope.model_dump(),
                        plan_name=terminal.metadata.plan.name,
                        nodes_total=len(terminal.metadata.plan.nodes),
                        nodes_done=terminal.nodes_done,
                    )
                    return ToolResult(status="success", result=summary.model_dump(mode="json"))
                manifest = PlanRunManifest(
                    **build_manifest(terminal.metadata.plan, terminal.refs, duration_seconds=0.0).model_dump(),
                    **envelope.model_dump(),
                    status=terminal.status,
                )
                return ToolResult(status="success", result=manifest.model_dump(mode="json"))
            except CheckpointPersistenceError as exc:
                return self._error(PlanRunError("checkpoint_write_failed", str(exc)), run_id=run.metadata.run_id)
            except (FlowLockedError, PlanRunError) as exc:
                if isinstance(exc, PlanRunError):
                    return self._error(exc, run_id=run.metadata.run_id)
                return self._error(PlanRunError("run_busy", str(exc)), run_id=run.metadata.run_id)
            except Exception as exc:  # noqa: BLE001 - return bounded flow failures to the tool caller
                return self._error(PlanRunError("flow_error", str(exc)), run_id=run.metadata.run_id)
            finally:
                await continuation.__aexit__(None, None, None)

        task = asyncio.create_task(_finish())
        self._run_tasks[run.metadata.run_id] = task
        done, _pending = await asyncio.wait({task}, timeout=self.soft_timeout)
        if task in done:
            return await task

        envelope = self._resolver.envelope(run)
        summary = PlanRunSummary(
            **envelope.model_dump(),
            plan_name=run.metadata.plan.name,
            nodes_total=len(run.metadata.plan.nodes),
            nodes_done=run.nodes_done,
        )
        return ToolResult(status="success", result=summary.model_dump(mode="json"))

    async def _write_root_envelope(self, run: PlanRun, metadata: PlanRunMetadata, *, store: CheckpointStore) -> int:
        """Persist an updated root ``plan_run`` document as a NEW root checkpoint.

        Builds a fresh :class:`FlowCheckpointer` bound to the root's own
        definition/flow_name, seeds a :class:`FlowContext` that replays
        every node the latest root checkpoint already completed (so the
        new checkpoint stays a complete, self-contained record — spec §2,
        bounded by AC8), and writes exactly one required checkpoint whose
        ``plan_run`` shared-data document is ``metadata``.

        Args:
            run: The currently resolved root view (for ``root_run_id``).
            metadata: The updated ``plan_run`` envelope to persist.
            store: The continuation's lease-delegating store.

        Returns:
            The new checkpoint's id.

        Raises:
            PlanRunError: ``checkpoint_unavailable`` if the root checkpoint
                vanished, or ``checkpoint_write_failed`` if the write itself
                fails.
        """
        register_plan_checkpoint_types()
        latest = await select_latest(store, self._durable_store, run.metadata.root_run_id)
        if latest is None:
            raise PlanRunError("checkpoint_unavailable", "root checkpoint vanished during continuation")
        checkpointer = FlowCheckpointer(
            flow_id=run.metadata.root_run_id,
            flow_name=latest.flow_name,
            definition=latest.definition,
            store=store,
            durable_store=self._durable_store,
            durable=self._durable_store is not None,
            starting_checkpoint_id=latest.checkpoint_id,
            shared_data_projector=plan_run_projector,
        )
        ctx = self._seed_context(run)
        ctx.shared_data[PLAN_RUN_SHARED_KEY] = metadata.model_dump(mode="json")
        serializer = FlowStateSerializer()
        for node_id in latest.context.completion_order:
            if node_id in latest.context.results:
                ctx.mark_completed(node_id, result=serializer.from_safe(latest.context.results[node_id]))
        try:
            checkpoint = await checkpointer.checkpoint(ctx, status=latest.status)
        except CheckpointPersistenceError as exc:
            raise PlanRunError("checkpoint_write_failed", str(exc)) from exc
        return checkpoint.checkpoint_id

    async def _author_delta(self, run: PlanRun, eligible: "frozenset[str]") -> PlanDelta:
        """Make one ``replan`` call, then at most one structural correction.

        Args:
            run: The terminal run being repaired.
            eligible: Node ids the planner may replace.

        Returns:
            A validated :class:`PlanDelta`.

        Raises:
            PlanRunError: ``delta_invalid`` if the corrected delta is still
                unparseable or fails validation — the attempt this bounds
                is exactly "one replan call plus at most one repair_delta
                correction" (§2, AC8).
        """
        planner = self._planner(build_catalog(self._tool_manager, self.allowed_tools))
        manifest = build_manifest(run.metadata.plan, run.refs)
        allowed = self.allowed_tools if self.allowed_tools is not None else self._tool_manager.list_tools()
        try:
            delta = await planner.replan(run.metadata.plan, manifest, eligible_node_ids=eligible)
            report = validate_delta(
                delta, run=run, tool_manager=self._tool_manager, allowed_tools=allowed, **self._validation_kwargs()
            )
            if report.ok:
                return delta
            delta_json = delta.model_dump(mode="json")
        except PlanAuthoringError as exc:
            delta_json, report = {"error": str(exc)[:300]}, ValidationReport(issues=[])
        try:
            delta = await planner.repair_delta(delta_json, report, plan=run.metadata.plan, eligible_node_ids=eligible)
        except PlanAuthoringError as exc:
            raise PlanRunError("delta_invalid", f"corrected delta unparseable: {exc}") from exc
        report = validate_delta(
            delta, run=run, tool_manager=self._tool_manager, allowed_tools=allowed, **self._validation_kwargs()
        )
        if not report.ok:
            raise PlanRunError("delta_invalid", f"corrected delta still invalid:\n{report}")
        return delta

    def _child_metadata(self, run: PlanRun, merged_plan: ExecutionPlan, child_id: str) -> PlanRunMetadata:
        """Build the accepted repair child's persisted ``plan_run`` envelope.

        Args:
            run: The parent run this child replaces failed/blocked nodes of.
            merged_plan: The delta merged into the parent's effective plan.
            child_id: The freshly allocated child run id.

        Returns:
            A ``source="repair"`` :class:`PlanRunMetadata` — same allowlist,
            scope and task_id as the parent, fingerprint recomputed over
            ``merged_plan``, and ``repair_attempts_used`` carrying the
            attempt just spent to author it.
        """
        return PlanRunMetadata(
            run_id=child_id,
            root_run_id=run.metadata.root_run_id,
            parent_run_id=run.metadata.run_id,
            plan=merged_plan,
            original_plan=run.metadata.original_plan,
            source="repair",
            started_at=datetime.now(timezone.utc),
            scope_key=run.metadata.scope_key,
            task_id=run.metadata.task_id,
            allowed_tools=run.metadata.allowed_tools,
            plan_fingerprint=plan_fingerprint(merged_plan),
            artifact_mode=run.metadata.artifact_mode,
            process_id=process_identity() if run.metadata.artifact_mode == "memory" else None,
            repair_attempts_used=run.metadata.repair_attempts_used + 1,
            max_repair_rounds=run.metadata.max_repair_rounds,
        )

    def _seed_child_context(self, run: PlanRun, child_meta: PlanRunMetadata) -> FlowContext:
        """Seed a fresh child context with the parent's protected refs completed.

        Every node NOT eligible for repair (ok/skipped/partial) is marked
        completed with its original ref so the child flow's scheduler
        never re-dispatches it — only the replacement nodes run.

        Args:
            run: The parent run (source of the protected refs).
            child_meta: The accepted child's persisted envelope.

        Returns:
            A :class:`FlowContext` seeded with the child's ``plan_run``
            envelope and the parent's protected completions.
        """
        ctx = FlowContext(initial_task=child_meta.plan.objective, agent_registry=self._get_agent_registry())
        ctx.shared_data[PLAN_RUN_SHARED_KEY] = child_meta.model_dump(mode="json")
        protected = protected_node_ids(run)
        for ref in run.refs:
            if ref.node_id in protected:
                ctx.mark_completed(ref.node_id, result=ref)
        return ctx

    async def _reconcile_lineage(self, run: PlanRun) -> PlanRun:
        """Reconcile a resolved view that walked into a still-open repair child.

        ``PlanRunResolver.resolve`` already walks ``active_child_run_id``
        and returns the consolidated view at the terminal-most link (spec
        §2 "root lookup follows this bounded chain"). When that walk
        crossed into a child (``run.metadata.parent_run_id`` is set) and
        the child itself has not reached a terminal checkpoint status, an
        earlier ``plan_repair`` call persisted and started that child but
        never saw it finish — never plan on top of an unresolved
        continuation. A terminal child is already folded into ``run`` by
        the resolver, so it is returned unchanged and the ordinary repair
        contract proceeds against that consolidated state.

        Args:
            run: The already-resolved (possibly lineage-consolidated) view.

        Returns:
            ``run`` unchanged, when there is nothing to reconcile.

        Raises:
            PlanRunError: ``repair_interrupted`` when an accepted child is
                still running/suspended — resume it with ``plan_resume``
                before repairing again.
        """
        if run.metadata.parent_run_id is not None and run.status == "running":
            raise PlanRunError(
                "repair_interrupted",
                f"run {run.metadata.root_run_id!r} has an unfinished repair child "
                f"{run.metadata.run_id!r}; resume it with plan_resume before repairing again",
                envelope=self._resolver.envelope(run),
            )
        return run

    # ── Agent-facing tools ───────────────────────────────────────────────────

    @tool_schema(PlanStatusArgs)
    async def plan_status(self, run_id: str) -> ToolResult:
        """Return progress while a plan run executes, or its final manifest."""
        try:
            run, record = await self._resolve_or_legacy(run_id)
        except PlanRunError as exc:
            return self._error(exc, run_id=run_id)

        if record is not None:
            envelope = self._legacy_envelope(record)
            if record.status == "running" or record.manifest is None:
                summary = PlanRunSummary(
                    **envelope.model_dump(),
                    plan_name=record.plan_name,
                    nodes_total=record.nodes_total,
                    nodes_done=record.nodes_done,
                    uncheckpointed_progress=record.nodes_done > 0,
                )
                return ToolResult(status="success", result=summary.model_dump(mode="json"))
            manifest = PlanRunManifest(
                **record.manifest.model_dump(),
                **envelope.model_dump(),
                status=record.status,
            )
            return ToolResult(status="success", result=manifest.model_dump(mode="json"))

        assert run is not None
        envelope = self._resolver.envelope(run)
        if run.status == "running":
            summary = PlanRunSummary(
                **envelope.model_dump(),
                plan_name=run.metadata.plan.name,
                nodes_total=len(run.metadata.plan.nodes),
                nodes_done=run.nodes_done,
            )
            return ToolResult(status="success", result=summary.model_dump(mode="json"))

        manifest = PlanRunManifest(
            **build_manifest(run.metadata.plan, run.refs, duration_seconds=0.0).model_dump(),
            **envelope.model_dump(),
            status=run.status,
        )
        return ToolResult(status="success", result=manifest.model_dump(mode="json"))

    @tool_schema(PlanArtifactsArgs)
    async def plan_artifacts(self, run_id: str) -> ToolResult:
        """Return the ArtifactRef list a run has produced so far."""
        try:
            run, record = await self._resolve_or_legacy(run_id)
        except PlanRunError as exc:
            return self._error(exc, run_id=run_id)

        if record is not None:
            if record.manifest is not None:
                artifacts = [ref.model_dump(mode="json") for ref in record.manifest.artifacts]
            else:
                ctx = self._run_contexts.get(run_id)
                artifacts = [
                    value.model_dump(mode="json")
                    for value in (ctx.results.values() if ctx is not None else ())
                    if isinstance(value, ArtifactRef)
                ]
            return ToolResult(
                status="success",
                result={
                    "run_id": run_id,
                    "artifacts": artifacts,
                    **self._legacy_envelope(record).model_dump(mode="json"),
                },
            )

        assert run is not None
        return ToolResult(
            status="success",
            result={
                "run_id": run_id,
                "artifacts": [ref.model_dump(mode="json") for ref in run.refs],
                **self._resolver.envelope(run).model_dump(mode="json"),
            },
        )

    @tool_schema(PlanResumeArgs)
    async def plan_resume(self, run_id: str) -> ToolResult:
        """Resume an interrupted checkpointed run without replaying completions."""
        continuation: Optional[PlanContinuation] = None
        ownership_transferred = False
        try:
            run = await self._resolver.resolve(run_id)
            self._assert_policy(run)
            if not run.resumable:
                raise PlanRunError(
                    run.recovery_reason or "run_not_resumable",
                    f"run {run_id!r} cannot be resumed",
                    envelope=self._resolver.envelope(run),
                )
            await self._memory_binding.prepare()
            continuation = PlanContinuation(run, store=self._checkpoint_store, durable_store=self._durable_store)
            await continuation.__aenter__()
            run = await self._resolver.resolve(run_id)
            self._assert_policy(run)
            if not run.resumable:
                raise PlanRunError(
                    run.recovery_reason or "run_not_resumable",
                    f"run {run_id!r} cannot be resumed",
                    envelope=self._resolver.envelope(run),
                )
            await self._memory_binding.restore(
                [ref for ref in run.refs if ref.status in ("ok", "partial") and ref.versions]
            )
            store = continuation.flow_store()
            flow = await PlanFlow.resume(
                run.metadata.run_id,
                agent_registry=self._get_agent_registry(),
                store=store,
                durable_store=self._durable_store,
                flow_factory=self._resume_flow_factory(run, store=store),
                seed_context=self._seed_context(run),
            )
            continuation.raise_if_lease_lost()
            ownership_transferred = True
            return await self._run_continuation(run, flow, continuation=continuation)
        except RestoreError as exc:
            return self._error(PlanRunError(exc.code, str(exc)), run_id=run_id)
        except FlowLockedError as exc:
            return self._error(PlanRunError("run_busy", str(exc)), run_id=run_id)
        except PlanRunError as exc:
            return self._error(exc, run_id=run_id)
        finally:
            if continuation is not None and not ownership_transferred:
                await continuation.__aexit__(None, None, None)

    @tool_schema(PlanRepairArgs)
    async def plan_repair(self, run_id: str) -> ToolResult:
        """Spend one permitted repair attempt on a failed/partial run's error ids.

        Computes the eligible (error/undispatched) node ids under the root
        lease, refuses (consuming nothing) when the run is not repairable,
        has nothing eligible, has exhausted ``max_repair_rounds``, or no
        ``planner_llm`` is configured. Otherwise persists the incremented
        attempt count and the freshly allocated child id BEFORE making any
        planner call — an authoring failure, a lost lease, or a crash from
        that point on still leaves the attempt spent. Makes one ``replan``
        call plus at most one ``repair_delta`` correction, merges and
        validates the result, seeds a child flow with every protected
        (ok/skipped/partial) node already marked completed, persists the
        accepted child as the run's new active continuation, and runs it.
        Never restarts the whole run and never makes an autonomous planner
        call on top of an interrupted repair child (spec §2 Module 6).
        """
        continuation: Optional[PlanContinuation] = None
        ownership_transferred = False
        try:
            run = await self._resolver.resolve(run_id)
            run = await self._reconcile_lineage(run)
            self._assert_policy(run)
            envelope = self._resolver.envelope(run)
            if not run.checkpoint_enabled:
                raise PlanRunError(
                    "checkpoint_unavailable",
                    "runs without a checkpoint cannot be repaired (§8 D2)",
                    envelope=envelope,
                )
            if run.status not in ("failed", "partial"):
                raise PlanRunError("run_not_repairable", f"run status is {run.status!r}", envelope=envelope)
            eligible = eligible_repair_nodes(run)
            if not eligible:
                raise PlanRunError(
                    "no_repairable_nodes",
                    "no error or undispatched nodes to replace (partial fan-out is not error)",
                    envelope=envelope,
                )
            if run.metadata.repair_attempts_used >= run.metadata.max_repair_rounds:
                raise PlanRunError(
                    "repair_limit_reached",
                    f"{run.metadata.repair_attempts_used}/{run.metadata.max_repair_rounds} rounds used",
                    envelope=envelope,
                )
            if self.planner_llm is None:
                raise PlanRunError("planner_unavailable", "plan_repair requires planner_llm", envelope=envelope)

            await self._memory_binding.prepare()
            continuation = PlanContinuation(run, store=self._checkpoint_store, durable_store=self._durable_store)
            await continuation.__aenter__()

            run = await self._resolver.resolve(run_id)
            run = await self._reconcile_lineage(run)
            self._assert_policy(run)
            envelope = self._resolver.envelope(run)
            if not run.checkpoint_enabled:
                raise PlanRunError(
                    "checkpoint_unavailable",
                    "runs without a checkpoint cannot be repaired (§8 D2)",
                    envelope=envelope,
                )
            if run.status not in ("failed", "partial"):
                raise PlanRunError("run_not_repairable", f"run status is {run.status!r}", envelope=envelope)
            eligible = eligible_repair_nodes(run)
            if not eligible:
                raise PlanRunError(
                    "no_repairable_nodes",
                    "no error or undispatched nodes to replace (partial fan-out is not error)",
                    envelope=envelope,
                )
            if run.metadata.repair_attempts_used >= run.metadata.max_repair_rounds:
                raise PlanRunError(
                    "repair_limit_reached",
                    f"{run.metadata.repair_attempts_used}/{run.metadata.max_repair_rounds} rounds used",
                    envelope=envelope,
                )

            child_id = str(uuid.uuid4())
            metadata = run.metadata.model_copy(
                update={
                    "repair_attempts_used": run.metadata.repair_attempts_used + 1,
                    "repair_children": [*run.metadata.repair_children, child_id],
                }
            )
            # Attempt reserved BEFORE any LLM call (AC8): an authoring
            # failure, a lost lease, or a crash from here on leaves it spent.
            await self._write_root_envelope(run, metadata, store=continuation.flow_store())
            delta = await self._author_delta(run, eligible)
            continuation.raise_if_lease_lost()

            merged = merge_delta(run.metadata.plan, delta)
            child_meta = self._child_metadata(run, merged, child_id)
            protected = protected_node_ids(run)
            await self._memory_binding.restore(
                [
                    ref
                    for ref in run.refs
                    if ref.node_id in protected and ref.status in ("ok", "partial") and ref.versions
                ]
            )

            child_flow = build_plan_flow(
                merged,
                run=child_meta,
                tool_manager=self._tool_manager,
                working_memory=self._working_memory,
                agent_registry=self._get_agent_registry(),
                permission_context=self.permission_context,
                step_mapping=self.plan_step_mapping,
                store=continuation.flow_store(child_id),
                durable_store=self._durable_store,
                **self._flow_delegate_kwargs(),
            )
            child_flow._resume_seed_context = self._seed_child_context(run, child_meta)

            metadata = metadata.model_copy(update={"active_child_run_id": child_id})
            # Persist the accepted child definition/id before dispatch (§2).
            await self._write_root_envelope(run, metadata, store=continuation.flow_store())

            child_run = PlanRun(
                metadata=child_meta,
                checkpoint_id=None,
                status="running",
                refs=[],
                nodes_done=0,
                checkpoint_enabled=True,
                resume_level=run.resume_level,
                resumable=False,
                recovery_reason=None,
                dispatched_node_ids=[],
            )
            ownership_transferred = True
            return await self._run_continuation(child_run, child_flow, continuation=continuation)
        except RestoreError as exc:
            return self._error(PlanRunError(exc.code, str(exc)), run_id=run_id)
        except FlowLockedError as exc:
            return self._error(PlanRunError("run_busy", str(exc)), run_id=run_id)
        except PlanRunError as exc:
            return self._error(exc, run_id=run_id)
        finally:
            if continuation is not None and not ownership_transferred:
                await continuation.__aexit__(None, None, None)

    @tool_schema(PlanExecuteArgs)
    async def plan_execute(
        self,
        objective: Optional[str] = None,
        plan_name: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Acquire, validate and run an ExecutionPlan.

        Provide exactly one of `objective` (planner-authored) or
        `plan_name` (versioned file). Returns the full manifest, or a
        `run_id` summary if still running after `soft_timeout`.
        """
        try:
            plan, _plan_json, report, source = await self._acquire_and_validate(objective, plan_name, params)
        except _StructuralError as exc:
            return ToolResult(status="error", success=False, result=None, error=str(exc))

        if not report.ok:
            return ToolResult(
                status="error",
                success=False,
                result=None,
                error=f"Plan {plan.name!r} is invalid — nothing executed:\n{report}",
            )

        return await self._run_plan(plan, source=source)

    @tool_schema(PlanValidateArgs)
    async def plan_validate(
        self,
        objective: Optional[str] = None,
        plan_name: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Dry-run: acquire and validate an ExecutionPlan without running it.

        Returns the acquired plan JSON verbatim plus the full validation
        report (`ok` + per-issue node_id/code/message/severity). Never
        calls a tool.
        """
        try:
            plan, plan_json, report, _source = await self._acquire_and_validate(objective, plan_name, params)
        except _StructuralError as exc:
            return ToolResult(status="error", success=False, result=None, error=str(exc))

        return ToolResult(
            status="success",
            result={
                "plan": plan_json,
                "ok": report.ok,
                "issues": [
                    {
                        "node_id": issue.node_id,
                        "code": issue.code,
                        "message": issue.message,
                        "severity": issue.severity,
                    }
                    for issue in report.issues
                ],
            },
        )

    # ── Acquisition + validation (shared by plan_execute/plan_validate) ────

    async def _acquire_and_validate(
        self,
        objective: Optional[str],
        plan_name: Optional[str],
        params: Optional[Dict[str, Any]],
    ) -> "tuple[ExecutionPlan, Dict[str, Any], Any, str]":
        """Arbitrate inputs, acquire the plan, and validate (+ repair once).

        Never raises for "the plan is invalid" — that is data returned to
        the caller (`report.ok=False`); `plan_execute` converts it into a
        tool error itself, `plan_validate` returns it as its whole point.
        Only genuine structural problems (bad arbitration, an unreadable
        plan file, an unconfigured `planner_llm`/`plans_dir`, or a planner
        response that never parses even after one repair round) raise
        `_StructuralError`.

        Returns:
            ``(plan, plan_json, report, source)``.

        Raises:
            _StructuralError: On any structural acquisition failure.
        """
        self._check_arbitration(objective, plan_name, params)
        if plan_name is not None:
            return await self._acquire_from_file(plan_name, params)
        return await self._acquire_from_objective(objective)

    def _check_arbitration(
        self,
        objective: Optional[str],
        plan_name: Optional[str],
        params: Optional[Dict[str, Any]],
    ) -> None:
        """Enforce exactly one of objective/plan_name, and params only with plan_name."""
        if objective is not None and plan_name is not None:
            raise _StructuralError("Provide exactly one of 'objective' or 'plan_name', not both.")
        if objective is None and plan_name is None:
            raise _StructuralError("Provide exactly one of 'objective' or 'plan_name'.")
        if objective is not None and params is not None:
            raise _StructuralError(
                "'params' is a plan_name-mode concept ({params.<name>} load-time "
                "substitution) and cannot be combined with 'objective'."
            )

    async def _acquire_from_file(
        self, plan_name: str, params: Optional[Dict[str, Any]]
    ) -> "tuple[ExecutionPlan, Dict[str, Any], Any, str]":
        """``plan_name`` mode: load from ``plans_dir``, validate, no repair."""
        if self.plans_dir is None:
            raise _StructuralError("plan_name mode requires the toolkit to be constructed with " "plans_dir=<path>.")

        def _load() -> ExecutionPlan:
            # PlanFileStore (construction + load) is sync file I/O.
            return PlanFileStore(self.plans_dir).load(plan_name, params)

        try:
            # This is an async method — offload the sync I/O to a worker
            # thread rather than blocking the event loop.
            plan = await asyncio.to_thread(_load)
        except PlanLoadError as exc:
            raise _StructuralError(str(exc)) from exc

        plan_json = plan.model_dump(mode="json")
        report = validate_with_allowlist(plan, self._tool_manager, self.allowed_tools, **self._validation_kwargs())
        return plan, plan_json, report, "plan_name"

    async def _acquire_from_objective(self, objective: str) -> "tuple[ExecutionPlan, Dict[str, Any], Any, str]":
        """``objective`` mode: author via the planner, validate, ≤1 repair."""
        if self.planner_llm is None:
            raise _StructuralError("objective mode requires the toolkit to be constructed with " "planner_llm=<...>.")
        catalog = build_catalog(self._tool_manager, self.allowed_tools)
        planner = self._planner(catalog)

        try:
            plan = await planner.author(objective)
        except PlanAuthoringError as exc:
            raise _StructuralError(f"Planner failed to author a plan: {exc}") from exc

        plan_json = plan.model_dump(mode="json")
        report = validate_with_allowlist(plan, self._tool_manager, self.allowed_tools, **self._validation_kwargs())

        if not report.ok:
            try:
                plan = await planner.repair(plan_json, report)
            except PlanAuthoringError as exc:
                raise _StructuralError(
                    "Planner repair round failed to produce a parseable plan: "
                    f"{exc}\nOriginal validation report:\n{report}"
                ) from exc
            plan_json = plan.model_dump(mode="json")
            report = validate_with_allowlist(plan, self._tool_manager, self.allowed_tools, **self._validation_kwargs())

        return plan, plan_json, report, "objective"
