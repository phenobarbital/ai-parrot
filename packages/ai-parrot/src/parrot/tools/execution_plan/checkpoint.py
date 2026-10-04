"""Plan-specific checkpoint policy around the existing flow scheduler."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Sequence, Tuple

from parrot.bots.flows.core.checkpoint import CheckpointPersistenceError, CheckpointStore, FlowCheckpoint
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.flow.flow import AgentsFlow
from parrot.bots.flows.plan import (
    ExecutionPlan,
    PlanToolNode,
    ensure_tool_node_registered,
    make_tool_node_factory,
    to_flow_definition,
)
from parrot.registry.registry import AgentRegistry

from .models import PLAN_RUN_SHARED_KEY, PlanRun, PlanRunError, PlanRunMetadata
from .runs import register_plan_checkpoint_types, select_latest

__all__ = (
    "LeaseDelegatingStore",
    "PlanContinuation",
    "PlanFlow",
    "build_plan_flow",
    "degraded_lock",
    "plan_run_projector",
)
_logger = logging.getLogger(__name__)


def plan_run_projector(ctx: FlowContext) -> Dict[str, Any]:
    """Project only the validated plan-run envelope into checkpoint shared data."""
    envelope = ctx.shared_data.get(PLAN_RUN_SHARED_KEY)
    return {PLAN_RUN_SHARED_KEY: envelope} if isinstance(envelope, dict) else {}


class PlanFlow(AgentsFlow):
    """Apply plan-specific checkpoint policy around the existing scheduler."""

    def __init__(self, name: str, **kwargs: Any) -> None:
        """Force required persistence and plan-only projection when enabled."""
        if kwargs.get("checkpoint"):
            kwargs["checkpoint_required"] = True
            kwargs["checkpoint_shared_data"] = plan_run_projector
            kwargs["checkpoint_include_responses"] = False
        super().__init__(name, **kwargs)

    async def _run_flow_scheduler(
        self,
        ctx: FlowContext,
        *,
        on_complete: Tuple[Callable[[FlowContext, FlowResult], Awaitable[None]], ...] = (),
    ) -> FlowResult:
        """Write start and terminal records within the checkpointer lease."""
        checkpointer = self._checkpointer
        if checkpointer is not None:
            await checkpointer.checkpoint(ctx, status="running")
        try:
            result = await super()._run_flow_scheduler(ctx, on_complete=on_complete)
        except asyncio.CancelledError:
            raise
        if checkpointer is not None:
            status = "failed" if ctx.errors else "completed"
            await checkpointer.checkpoint(ctx, status=status)
        return result


def build_plan_flow(
    plan: ExecutionPlan,
    *,
    run: PlanRunMetadata,
    tool_manager: Any,
    working_memory: Any,
    agent_registry: AgentRegistry,
    permission_context: Any,
    step_mapping: Mapping[str, str],
    store: Optional[CheckpointStore],
    durable_store: Optional[CheckpointStore],
    delegates: Sequence[Any] = (),
    delegate_trace_sink: Optional[Any] = None,
    allow_delegate_side_effects: bool = False,
) -> PlanFlow:
    """Compile a plan and bind its run identity and checkpoint policy."""
    ensure_tool_node_registered(PlanToolNode)
    register_plan_checkpoint_types()
    definition = to_flow_definition(plan)
    factory = make_tool_node_factory(
        tool_manager,
        working_memory,
        permission_context=permission_context,
        plan_run_id=run.run_id,
        step_mapping=dict(step_mapping),
    )
    node_factories: Dict[str, Any] = {"tool": factory}
    if delegates:
        from parrot.bots.flows.plan import ensure_delegate_node_registered  # noqa: PLC0415
        from parrot.bots.flows.plan.delegate import DelegateToolNode, make_delegate_node_factory  # noqa: PLC0415

        ensure_delegate_node_registered(DelegateToolNode)
        node_factories["delegate"] = make_delegate_node_factory(
            tool_manager,
            working_memory,
            delegates,
            trace_sink=delegate_trace_sink,
            allow_delegate_side_effects=allow_delegate_side_effects,
            permission_context=permission_context,
            plan_run_id=run.run_id,
            step_mapping=dict(step_mapping),
        )
    enabled = store is not None and plan.metadata.checkpoint
    flow = PlanFlow.from_definition(
        definition,
        agent_registry=agent_registry,
        node_factories=node_factories,
        checkpoint=enabled,
        durable=enabled and durable_store is not None,
        checkpoint_store=store,
        durable_store=durable_store,
        flow_id=run.run_id,
    )
    _logger.debug(
        "built PlanFlow run_id=%s checkpoint=%s durable=%s",
        run.run_id,
        enabled,
        durable_store is not None,
    )
    return flow


class LeaseDelegatingStore(CheckpointStore):
    """Delegate store calls while handing the continuation lease to a resumed flow."""

    def __init__(self, inner: CheckpointStore, *, root_flow_id: str, holder: str, leased_flow_ids: set[str]) -> None:
        """Bind the borrowed store, real lease holder, and covered flow ids."""
        self._inner = inner
        self._root = root_flow_id
        self._holder = holder
        self._leased = set(leased_flow_ids)
        self._aliases: Dict[str, str] = {}
        self._write_locks: Dict[str, asyncio.Lock] = {}

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        """Hand off covered leases and acquire all other flow leases normally."""
        if flow_id in self._leased:
            self._aliases[holder] = self._holder
            return True
        return await self._inner.acquire_lease(flow_id, holder, ttl)

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        """Renew a covered lease with the continuation's real holder."""
        real_holder = self._aliases.get(holder, holder) if flow_id in self._leased else holder
        return await self._inner.renew_lease(flow_id, real_holder, ttl)

    async def release_lease(self, flow_id: str, holder: str) -> None:
        """Keep covered leases owned by the continuation until its exit."""
        if flow_id not in self._leased:
            await self._inner.release_lease(flow_id, holder)

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        """Reject delayed older writes while permitting equal-id final rewrites."""
        if checkpoint.flow_id not in self._leased:
            await self._inner.put(checkpoint)
            return
        lock = self._write_locks.setdefault(checkpoint.flow_id, asyncio.Lock())
        async with lock:
            latest = await self._inner.latest(checkpoint.flow_id)
            if latest is not None and checkpoint.checkpoint_id < latest.checkpoint_id:
                raise CheckpointPersistenceError(
                    f"stale write {checkpoint.flow_id}@{checkpoint.checkpoint_id} < {latest.checkpoint_id}"
                )
            await self._inner.put(checkpoint)

    async def latest(self, flow_id: str) -> FlowCheckpoint | None:
        """Delegate latest-checkpoint lookup."""
        return await self._inner.latest(flow_id)

    async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint | None:
        """Delegate checkpoint lookup by id."""
        return await self._inner.get(flow_id, checkpoint_id)

    async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]:
        """Delegate checkpoint history lookup."""
        return await self._inner.history(flow_id, limit)

    async def list_flows(self, status: str | None = None) -> list[dict[str, Any]]:
        """Delegate flow listing."""
        return await self._inner.list_flows(status)

    async def delete_flow(self, flow_id: str) -> None:
        """Delegate flow deletion."""
        await self._inner.delete_flow(flow_id)

    async def close(self) -> None:
        """Leave the borrowed inner store open."""


_degraded_locks: Dict[str, asyncio.Lock] = {}


def degraded_lock(run_id: str) -> asyncio.Lock:
    """Return the process-wide serialization lock for an uncheckpointed run."""
    return _degraded_locks.setdefault(run_id, asyncio.Lock())


class PlanContinuation:
    """Hold one root lease across validation, authoring, and flow execution."""

    def __init__(
        self,
        run: PlanRun,
        *,
        store: Optional[CheckpointStore],
        durable_store: Optional[CheckpointStore] = None,
        ttl: int = 60,
    ) -> None:
        """Bind the root identity, expected revision, stores, and lease TTL."""
        self._run = run
        self._store = store
        self._durable = durable_store
        self._ttl = ttl
        self._root = run.metadata.root_run_id
        # The root lease is always acquired on `self._root` (spec: "one root
        # lease across validation, authoring, and flow execution"), but the
        # staleness check below must compare against the checkpoint that
        # `run.checkpoint_id` actually belongs to: PlanRunResolver.resolve()
        # returns the CHILD's own (independently-numbered) checkpoint_id
        # once it has descended a repair-child lineage, while
        # `run.metadata.run_id` tracks that same descent (it equals
        # `root_run_id` for an undescended run, and the accepted child's own
        # id once resolved into one) — using `self._root` there compared an
        # unrelated flow's checkpoint sequence and misfired on every resume
        # of an already-accepted child, even with zero real contention.
        self._snapshot_flow_id = run.metadata.run_id
        self._holder = f"plan-continuation:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._heartbeat: Optional[asyncio.Task[None]] = None
        self.lease_lost = False
        self.logger = logging.getLogger(f"{__name__}.PlanContinuation")

    async def __aenter__(self) -> "PlanContinuation":
        """Acquire the root lease and reject stale snapshots before caller work begins."""
        if self._store is None:
            raise PlanRunError("checkpoint_unavailable", "a continuation requires a checkpoint store")
        if not await self._store.acquire_lease(self._root, self._holder, self._ttl):
            raise PlanRunError("run_busy", f"run {self._root!r} is leased by another continuation")
        self._heartbeat = asyncio.create_task(self._heartbeat_loop())
        try:
            latest = await select_latest(self._store, self._durable, self._snapshot_flow_id)
            if latest is None or latest.checkpoint_id != self._run.checkpoint_id:
                raise PlanRunError("run_busy", "stale snapshot: re-resolve the run")
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Stop heartbeat and release the root lease on every exit path."""
        if self._heartbeat is not None:
            self._heartbeat.cancel()
            try:
                await self._heartbeat
            except asyncio.CancelledError:
                pass
            self._heartbeat = None
        if self._store is None:
            return
        try:
            await asyncio.shield(self._store.release_lease(self._root, self._holder))
        except Exception as release_exc:  # noqa: BLE001 - never mask caller errors
            self.logger.warning("release_lease failed for %s: %s", self._root, release_exc)

    async def _heartbeat_loop(self) -> None:
        """Renew the root lease until it is lost or the continuation exits."""
        try:
            while True:
                await asyncio.sleep(self._ttl / 3)
                if self._store is None or not await self._store.renew_lease(self._root, self._holder, self._ttl):
                    self.lease_lost = True
                    return
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 - a failed heartbeat loses the lease
            self.logger.warning("lease renewal failed for %s: %s", self._root, exc)
            self.lease_lost = True

    def raise_if_lease_lost(self) -> None:
        """Raise a structured error when the heartbeat has lost the root lease."""
        if self.lease_lost:
            raise PlanRunError("run_busy", f"lease on {self._root!r} was lost")

    def flow_store(self, *extra_flow_ids: str) -> CheckpointStore:
        """Return a store that hands the root lease to resumed flow checkpointers."""
        if self._store is None:
            raise PlanRunError("checkpoint_unavailable", "a continuation requires a checkpoint store")
        return LeaseDelegatingStore(
            self._store,
            root_flow_id=self._root,
            holder=self._holder,
            leased_flow_ids={self._root, *extra_flow_ids},
        )
