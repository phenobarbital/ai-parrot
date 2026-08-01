"""FlowCheckpointer — event-driven snapshots, write-through, dump, lease
(FEAT-399, TASK-2051).

Subscribes to a running `AgentsFlow`'s node-event stream, assembles a
`FlowCheckpoint` after every node completion/failure, and writes it
fire-and-forget to the ephemeral store (and, in write-through mode, to
the durable store too). Owns `dump()` (ephemeral → durable, marking the
flow `suspended`) and the resume lease lifecycle (acquire/heartbeat/
release).

Checkpoint writes must NEVER propagate exceptions into the flow — the
fire-and-forget + pending-task-set discipline mirrors `PersistenceMixin`
(`core/storage/persistence.py`): tasks are tracked in ``_pending_tasks``
and awaited (with ``return_exceptions=True``) in ``aclose()``; write
failures are logged as warnings only.

`FlowContext.to_snapshot()` does not exist yet (TASK-2052) — the
snapshot is assembled here directly from the public `FlowContext` fields
listed in this module's tests/contract.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from navconfig.logging import logging

from parrot.bots.flows.core.checkpoint.errors import FlowLockedError
from parrot.bots.flows.core.checkpoint.model import (
    ContextSnapshot,
    FlowCheckpoint,
    MemoryRefs,
    NodeStateSnapshot,
)
from parrot.bots.flows.core.checkpoint.serializer import FlowStateSerializer
from parrot.bots.flows.core.checkpoint.store.base import CheckpointStore
from parrot.conf import FLOW_CHECKPOINT_LEASE_TTL

if TYPE_CHECKING:
    from parrot.bots.flows.core.context import FlowContext
    from parrot.bots.flows.flow.definition import FlowDefinition


#: Node events that trigger a checkpoint write (spec §3 Module 6).
_CHECKPOINT_EVENTS = ("node_completed", "node_failed")


class FlowCheckpointer:
    """Assembles and persists `FlowCheckpoint`s for one flow run.

    Args:
        flow_id: Unique identifier of the flow run.
        flow_name: Flow name (mirrored onto every checkpoint).
        definition: The `FlowDefinition` graph snapshot embedded in every
            checkpoint (spec §2: checkpoints are self-contained).
        store: The ephemeral `CheckpointStore` (always written to).
        durable_store: Optional durable `CheckpointStore`. Required for
            write-through mode and `dump()`.
        serializer: `FlowStateSerializer` instance (shared type registry).
        include_responses: When True, raw `FlowContext.responses` are
            included in the snapshot (heavy; opt-in, spec resolved OQ2).
        durable: When True, every `put()` write-throughs to both stores.
        history_limit: Max checkpoints `dump()` copies from ephemeral to
            durable (mirrors `FLOW_CHECKPOINT_HISTORY`).
        memory_refs: References to conversational memory (not content).
        starting_checkpoint_id: The last checkpoint id already written
            (e.g. loaded from a resumed run); the next write uses
            ``starting_checkpoint_id + 1``. Defaults to 0 (fresh run).
    """

    def __init__(
        self,
        flow_id: str,
        flow_name: str,
        definition: FlowDefinition,
        store: CheckpointStore,
        *,
        durable_store: CheckpointStore | None = None,
        serializer: FlowStateSerializer | None = None,
        include_responses: bool = False,
        durable: bool = False,
        history_limit: int = 10,
        memory_refs: MemoryRefs | None = None,
        starting_checkpoint_id: int = 0,
    ) -> None:
        self._flow_id = flow_id
        self._flow_name = flow_name
        self._definition = definition
        self._store = store
        self._durable_store = durable_store
        self._serializer = serializer or FlowStateSerializer()
        self._include_responses = include_responses
        self._durable = durable
        self._history_limit = history_limit
        self._memory_refs = memory_refs or MemoryRefs()

        self._last_checkpoint_id: int = starting_checkpoint_id
        self._parent_checkpoint_id: int | None = (
            starting_checkpoint_id if starting_checkpoint_id > 0 else None
        )
        self._pending_tasks: set[asyncio.Task] = set()

        self._lease_holder: str | None = None
        self._lease_heartbeat_task: asyncio.Task | None = None

        self.logger = logging.getLogger("parrot.flows.checkpoint.checkpointer")

    # ── Snapshot assembly ──────────────────────────────────────────────────

    def _build_checkpoint(
        self, ctx: FlowContext, status: str
    ) -> FlowCheckpoint:
        """Assemble a `FlowCheckpoint` from the current `FlowContext` state.

        Args:
            ctx: The live `FlowContext` (its non-serializable fields —
                `agent_registry`/`synthesis_client`/`trace_context` —
                are never included).
            status: Run status to embed (``running``/``suspended``/
                ``completed``/``failed``).

        Returns:
            The assembled `FlowCheckpoint` (not yet persisted).
        """
        results_safe, results_lossy = self._serializer.to_safe_with_meta(ctx.results)
        responses_safe: dict[str, Any] | None = None
        responses_lossy = False
        if self._include_responses:
            responses_safe, responses_lossy = self._serializer.to_safe_with_meta(
                ctx.responses
            )

        errors_structured = {
            node_id: self._serializer.encode_error(exc)
            for node_id, exc in ctx.errors.items()
        }

        node_states = [
            NodeStateSnapshot(
                node_id=node_id,
                fsm_state=getattr(info, "status", "unknown"),
                completed_at=None,
            )
            for node_id, info in ctx.node_metadata.items()
        ]

        context_snapshot = ContextSnapshot(
            initial_task=ctx.initial_task,
            results=results_safe,
            responses=responses_safe,
            completed_tasks=sorted(ctx.completed_tasks),
            completion_order=list(ctx.completion_order),
            shared_data=dict(ctx.shared_data),
            errors=errors_structured,
        )

        checkpoint_id = self._last_checkpoint_id + 1
        checkpoint = FlowCheckpoint(
            flow_id=self._flow_id,
            flow_name=self._flow_name,
            checkpoint_id=checkpoint_id,
            parent_checkpoint_id=self._parent_checkpoint_id,
            created_at=datetime.now(UTC),
            status=status,  # type: ignore[arg-type]
            definition=self._definition,
            context=context_snapshot,
            node_states=node_states,
            memory_refs=self._memory_refs,
            lossy=results_lossy or responses_lossy,
        )
        self._last_checkpoint_id = checkpoint_id
        self._parent_checkpoint_id = checkpoint_id
        return checkpoint

    # ── Fire-and-forget write path ─────────────────────────────────────────

    async def _write(self, checkpoint: FlowCheckpoint) -> None:
        """Persist ``checkpoint`` to the ephemeral store (and durable, write-through).

        Never raises — failures are logged as warnings, matching the
        `PersistenceMixin` discipline (spec §7: write failures must never
        fail or block a flow).
        """
        try:
            await self._store.put(checkpoint)
        except Exception as exc:  # noqa: BLE001 - checkpoint writes must never break the flow
            self.logger.warning(
                "FlowCheckpointer: ephemeral store put() failed for flow_id=%s "
                "checkpoint_id=%s: %s",
                checkpoint.flow_id,
                checkpoint.checkpoint_id,
                exc,
            )

        if self._durable and self._durable_store is not None:
            try:
                await self._durable_store.put(checkpoint)
            except Exception as exc:  # noqa: BLE001 - see above
                self.logger.warning(
                    "FlowCheckpointer: durable store put() failed for flow_id=%s "
                    "checkpoint_id=%s: %s",
                    checkpoint.flow_id,
                    checkpoint.checkpoint_id,
                    exc,
                )

    def _schedule_write(self, checkpoint: FlowCheckpoint) -> None:
        """Schedule `_write()` as a tracked, fire-and-forget task."""
        task = asyncio.ensure_future(self._write(checkpoint))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    def make_listener(
        self, ctx: FlowContext
    ) -> Callable[[str, str, dict[str, Any]], None]:
        """Build a listener compatible with `AgentsFlow.add_node_event_listener()`.

        Args:
            ctx: The `FlowContext` this checkpointer snapshots from (read
                at each triggering event — always the live, current state).

        Returns:
            A synchronous ``(event, node_id, info) -> None`` callback.
            Sync on purpose: `AgentsFlow._notify_node_event()` invokes
            listeners inline and only schedules a task itself when the
            callback *returns* a coroutine — this listener instead owns
            its own tracked pending-task set so `aclose()` can await it.
        """

        def listener(event: str, node_id: str, info: dict[str, Any]) -> None:
            if event not in _CHECKPOINT_EVENTS:
                return
            checkpoint = self._build_checkpoint(ctx, status="running")
            self._schedule_write(checkpoint)

        return listener

    # ── Suspend / dump ──────────────────────────────────────────────────────

    async def dump(self, ctx: FlowContext) -> FlowCheckpoint:
        """Copy retained ephemeral history to durable storage and suspend.

        Writes every checkpoint in the ephemeral store's retained history
        to the durable store, then assembles and writes (to both stores)
        a final checkpoint with ``status="suspended"``.

        Args:
            ctx: The live `FlowContext` to snapshot for the final checkpoint.

        Returns:
            The final ``status="suspended"`` `FlowCheckpoint`.

        Raises:
            ValueError: If no durable store is configured.
        """
        if self._durable_store is None:
            raise ValueError("dump() requires a durable store to be configured")

        history = await self._store.history(self._flow_id, limit=self._history_limit)
        for checkpoint in history:
            await self._durable_store.put(checkpoint)

        final_checkpoint = self._build_checkpoint(ctx, status="suspended")
        await self._durable_store.put(final_checkpoint)
        await self._store.put(final_checkpoint)
        return final_checkpoint

    # ── Resume lease ─────────────────────────────────────────────────────────

    async def acquire_lease(
        self, holder: str, ttl: int | None = None
    ) -> None:
        """Acquire the resume lease and start the heartbeat-renewal task.

        Args:
            holder: Opaque identifier of this lease holder.
            ttl: Lease TTL in seconds; defaults to `FLOW_CHECKPOINT_LEASE_TTL`.

        Raises:
            FlowLockedError: If another holder already holds the lease.
        """
        ttl = FLOW_CHECKPOINT_LEASE_TTL if ttl is None else ttl
        acquired = await self._store.acquire_lease(self._flow_id, holder, ttl=ttl)
        if not acquired:
            raise FlowLockedError(
                f"flow_id={self._flow_id!r} is already locked by another resume"
            )
        self._lease_holder = holder
        self._lease_heartbeat_task = asyncio.ensure_future(
            self._heartbeat_loop(holder, ttl)
        )

    async def _heartbeat_loop(self, holder: str, ttl: int) -> None:
        """Renew the lease every ``ttl/3`` seconds until cancelled."""
        interval = max(ttl / 3, 1)
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._store.renew_lease(self._flow_id, holder, ttl=ttl)
                except Exception as exc:  # noqa: BLE001 - heartbeat must never crash the flow
                    self.logger.warning(
                        "FlowCheckpointer: lease renewal failed for flow_id=%s: %s",
                        self._flow_id,
                        exc,
                    )
        except asyncio.CancelledError:
            pass

    async def release_lease(self) -> None:
        """Stop the heartbeat task and release the lease (no-op if not held)."""
        if self._lease_heartbeat_task is not None:
            self._lease_heartbeat_task.cancel()
            try:
                await self._lease_heartbeat_task
            except asyncio.CancelledError:
                pass
            self._lease_heartbeat_task = None

        if self._lease_holder is not None:
            try:
                await self._store.release_lease(self._flow_id, self._lease_holder)
            except Exception as exc:  # noqa: BLE001 - release must never crash the flow
                self.logger.warning(
                    "FlowCheckpointer: release_lease failed for flow_id=%s: %s",
                    self._flow_id,
                    exc,
                )
            self._lease_holder = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Await pending writes, then release the lease.

        Idempotent: safe to call multiple times and before any write has
        been scheduled. Does not close the stores it was given — it does
        not own their lifecycle.

        Order matters here: pending fire-and-forget checkpoint writes MUST
        land before the lease is released. Releasing first would open a
        window where a concurrent `resume()` (racing in right after the
        lease frees up) could acquire the lease and read a checkpoint that
        is missing the write still in flight — silently reintroducing the
        double-execution the lease exists to prevent (code review finding,
        FEAT-399).
        """
        pending = self._pending_tasks
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            pending.clear()

        await self.release_lease()
