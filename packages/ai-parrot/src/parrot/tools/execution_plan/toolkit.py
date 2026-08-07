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
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Sequence, Set, Union

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.flow.flow import AgentsFlow
from parrot.bots.flows.plan import (
    ArtifactRef,
    ExecutionPlan,
    PlanToolNode,
    build_manifest,
    ensure_tool_node_registered,
    make_tool_node_factory,
    to_flow_definition,
)
from parrot.registry.registry import AgentRegistry
from parrot.tools.decorators import tool_schema
from parrot.tools.toolkit import AbstractToolkit

from ..abstract import ToolResult
from .catalog import build_catalog, validate_with_allowlist
from .models import (
    PlanArtifactsArgs,
    PlanExecuteArgs,
    PlanStatusArgs,
    PlanValidateArgs,
    RunningSummary,
    RunRecord,
)
from .planner import PlanAuthoringError, PlanPlanner
from .store import PlanFileStore, PlanLoadError

if TYPE_CHECKING:
    from parrot.auth.permission import PermissionContext
    from parrot.tools.working_memory.tool import WorkingMemoryToolkit


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
            **kwargs: Forwarded to :class:`AbstractToolkit`.
        """
        super().__init__(**kwargs)
        self._tool_manager = tool_manager
        self._working_memory = working_memory
        self.planner_llm = planner_llm
        self.plans_dir: Optional[Path] = Path(plans_dir) if plans_dir is not None else None
        self.allowed_tools: Optional[list] = (
            list(allowed_tools) if allowed_tools is not None else None
        )
        self.soft_timeout = soft_timeout
        self.permission_context = permission_context
        self._on_node_event = on_node_event
        self.max_completed_runs = max_completed_runs

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

    # ── Internal executor path (spec §3 Module 2) ──────────────────────────

    def _get_agent_registry(self) -> AgentRegistry:
        """Return the cached empty ``AgentRegistry``, creating it once."""
        if self._agent_registry is None:
            self._agent_registry = AgentRegistry()
        return self._agent_registry

    async def _run_plan(
        self, plan: ExecutionPlan, *, source: str
    ) -> ToolResult:
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
        ensure_tool_node_registered(PlanToolNode)
        definition = to_flow_definition(plan)
        factory = make_tool_node_factory(
            self._tool_manager,
            self._working_memory,
            permission_context=self.permission_context,
        )
        agent_registry = self._get_agent_registry()
        flow = AgentsFlow.from_definition(
            definition,
            agent_registry=agent_registry,
            node_factories={"tool": factory},
            # FEAT-399 flow-level checkpointing defaults to
            # PlanMetadata.checkpoint=True and would otherwise require a
            # live checkpoint store (Redis by default) before the first
            # node ever dispatches — silently contradicting this feature's
            # own "pure in-RAM v1, no persistent backend" design (spec §1
            # Non-Goals). The toolkit's RunRecord registry is the v1
            # resumability story; explicitly disable flow-level
            # checkpointing regardless of what a plan file's `metadata`
            # block says.
            checkpoint=False,
        )

        plan_node_ids: Set[str] = {node.id for node in plan.nodes}
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        ctx = FlowContext(initial_task=plan.objective, agent_registry=agent_registry)
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

        flow.add_node_event_listener(self._make_progress_listener(run_id, plan_node_ids))
        if self._on_node_event is not None:
            flow.add_node_event_listener(self._on_node_event)

        task = asyncio.create_task(
            self._execute_flow(run_id, flow, plan, ctx, started_monotonic)
        )
        self._run_tasks[run_id] = task

        done, _pending = await asyncio.wait({task}, timeout=self.soft_timeout)
        if task in done:
            # Surface a background-task exception (defensive: _execute_flow
            # already catches everything it can and marks the run "failed").
            exc = task.exception()
            record = self._runs.get(run_id, record)
            if record.manifest is not None:
                return ToolResult(
                    status="success", result=record.manifest.model_dump(mode="json")
                )
            reason = record.flow_error or (str(exc) if exc is not None else None)
            return ToolResult(
                status="error",
                success=False,
                result=None,
                error=f"Plan run {run_id!r} finished without a manifest"
                + (f": {reason}" if reason else ""),
            )

        summary = RunningSummary(
            run_id=run_id,
            plan_name=plan.name,
            nodes_total=record.nodes_total,
            nodes_done=record.nodes_done,
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

        return _listener

    async def _execute_flow(
        self,
        run_id: str,
        flow: AgentsFlow,
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
        except Exception as exc:  # noqa: BLE001 - recorded, never re-raised
            self.logger.error("Plan run %r failed at the flow level: %s", run_id, exc)
            if record is not None:
                record.status = "failed"
                record.finished_at = datetime.now(timezone.utc)
                record.flow_error = str(exc)[:500]
            self._evict_completed_runs()
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
                refs.append(
                    ArtifactRef(node_id=node.id, status="error", errors=[str(error)[:300]])
                )
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

        self._evict_completed_runs()

    def _evict_completed_runs(self) -> None:
        """Evict oldest completed/failed runs beyond ``max_completed_runs``.

        In-flight (``status == "running"``) runs are never evicted.
        """
        finished = [
            (run_id, rec)
            for run_id, rec in self._runs.items()
            if rec.status != "running"
        ]
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
                run_id, self.max_completed_runs,
            )

    # ── Agent-facing tools ───────────────────────────────────────────────────

    @tool_schema(PlanStatusArgs)
    async def plan_status(self, run_id: str) -> ToolResult:
        """Return progress while a plan run executes, or its final manifest."""
        record = self._runs.get(run_id)
        if record is None:
            return ToolResult(
                status="error",
                success=False,
                result=None,
                error=f"Unknown run_id {run_id!r}. Known: {sorted(self._runs)}",
            )

        if record.status == "running" or record.manifest is None:
            summary = RunningSummary(
                run_id=run_id,
                plan_name=record.plan_name,
                nodes_total=record.nodes_total,
                nodes_done=record.nodes_done,
            )
            return ToolResult(status="success", result=summary.model_dump(mode="json"))

        return ToolResult(status="success", result=record.manifest.model_dump(mode="json"))

    @tool_schema(PlanArtifactsArgs)
    async def plan_artifacts(self, run_id: str) -> ToolResult:
        """Return the ArtifactRef list a run has produced so far."""
        record = self._runs.get(run_id)
        if record is None:
            return ToolResult(
                status="error",
                success=False,
                result=None,
                error=f"Unknown run_id {run_id!r}. Known: {sorted(self._runs)}",
            )

        if record.manifest is not None:
            artifacts = [ref.model_dump(mode="json") for ref in record.manifest.artifacts]
        else:
            ctx = self._run_contexts.get(run_id)
            artifacts = [
                value.model_dump(mode="json")
                for value in (ctx.results.values() if ctx is not None else ())
                if isinstance(value, ArtifactRef)
            ]

        return ToolResult(status="success", result={"run_id": run_id, "artifacts": artifacts})

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
            plan, _plan_json, report, source = await self._acquire_and_validate(
                objective, plan_name, params
            )
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
            plan, plan_json, report, _source = await self._acquire_and_validate(
                objective, plan_name, params
            )
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
            raise _StructuralError(
                "Provide exactly one of 'objective' or 'plan_name', not both."
            )
        if objective is None and plan_name is None:
            raise _StructuralError(
                "Provide exactly one of 'objective' or 'plan_name'."
            )
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
            raise _StructuralError(
                "plan_name mode requires the toolkit to be constructed with "
                "plans_dir=<path>."
            )
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
        report = validate_with_allowlist(plan, self._tool_manager, self.allowed_tools)
        return plan, plan_json, report, "plan_name"

    async def _acquire_from_objective(
        self, objective: str
    ) -> "tuple[ExecutionPlan, Dict[str, Any], Any, str]":
        """``objective`` mode: author via the planner, validate, ≤1 repair."""
        if self.planner_llm is None:
            raise _StructuralError(
                "objective mode requires the toolkit to be constructed with "
                "planner_llm=<...>."
            )
        catalog = build_catalog(self._tool_manager, self.allowed_tools)
        planner = PlanPlanner(self.planner_llm, catalog)

        try:
            plan = await planner.author(objective)
        except PlanAuthoringError as exc:
            raise _StructuralError(f"Planner failed to author a plan: {exc}") from exc

        plan_json = plan.model_dump(mode="json")
        report = validate_with_allowlist(plan, self._tool_manager, self.allowed_tools)

        if not report.ok:
            try:
                plan = await planner.repair(plan_json, report)
            except PlanAuthoringError as exc:
                raise _StructuralError(
                    "Planner repair round failed to produce a parseable plan: "
                    f"{exc}\nOriginal validation report:\n{report}"
                ) from exc
            plan_json = plan.model_dump(mode="json")
            report = validate_with_allowlist(plan, self._tool_manager, self.allowed_tools)

        return plan, plan_json, report, "objective"
