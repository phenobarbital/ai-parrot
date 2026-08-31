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

Snapshot assembly delegates to `FlowContext.to_snapshot()` (added by
TASK-2052) — this module owns only the `FlowCheckpoint` wrapper
(checkpoint id/parent chain, definition, node states, memory refs).
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from navconfig.logging import logging

from parrot.bots.flows.core.checkpoint.errors import (
    CheckpointPersistenceError,
    FlowLockedError,
)
from parrot.bots.flows.core.checkpoint.model import (
    CheckpointInputMetadata,
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
        shared_data_projector: Optional ``(ctx) -> dict[str, Any]`` used
            instead of the raw ``ctx.shared_data`` mapping when building
            every checkpoint (spec §7: "never pass the complete live
            shared_data mapping to required persistence"). The projected
            dict is run through the same ``FlowStateSerializer`` type
            registry as node results — a registered type round-trips, an
            unregistered one degrades to a lossy repr rather than raising.
            ``None`` (default) keeps the historical behavior of embedding
            the full ``dict(ctx.shared_data)`` unmodified.
        input_metadata: Optional immutable input-fingerprint metadata
            (spec §2) embedded on every checkpoint this instance builds —
            both the fire-and-forget listener path and the awaited
            ``checkpoint()`` path. ``None`` (default, and the only value
            generic non-dev-workflow callers ever pass) leaves
            ``FlowCheckpoint.input_metadata`` unset.
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
        shared_data_projector: Callable[[FlowContext], dict[str, Any]] | None = None,
        input_metadata: CheckpointInputMetadata | None = None,
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
        self._shared_data_projector = shared_data_projector
        self._input_metadata = input_metadata

        self._last_checkpoint_id: int = starting_checkpoint_id
        self._parent_checkpoint_id: int | None = (
            starting_checkpoint_id if starting_checkpoint_id > 0 else None
        )
        self._pending_tasks: set[asyncio.Task] = set()

        self._lease_holder: str | None = None
        self._lease_heartbeat_task: asyncio.Task | None = None
        # Set by _heartbeat_loop() on a renewal failure/loss (spec §7:
        # "Lease heartbeat loss is a Redis failure. Required mode must
        # surface it to the active job rather than only logging from a
        # background task."). Generic (non-required) callers never read
        # this — logging-only behavior is unchanged for them.
        self._lease_lost: bool = False
        self._lease_lost_exc: BaseException | None = None

        self.logger = logging.getLogger("parrot.flows.checkpoint.checkpointer")

    @property
    def lease_lost(self) -> bool:
        """True if the background heartbeat lost or failed to renew the lease."""
        return self._lease_lost

    def raise_if_lease_lost(self) -> None:
        """Raise `CheckpointPersistenceError` if the heartbeat lost the lease.

        Required mode calls this at every checkpoint barrier (spec §7); a
        generic non-required caller never calls it, so the historical
        logging-only heartbeat behavior is unchanged for them.

        Raises:
            CheckpointPersistenceError: If ``lease_lost`` is True.
        """
        if self._lease_lost:
            raise CheckpointPersistenceError(
                f"FlowCheckpointer: lease for flow_id={self._flow_id!r} was "
                "lost or failed to renew"
            ) from self._lease_lost_exc

    # ── Snapshot assembly ──────────────────────────────────────────────────

    def _build_checkpoint(
        self, ctx: FlowContext, status: str
    ) -> FlowCheckpoint:
        """Assemble a `FlowCheckpoint` from the current `FlowContext` state.

        Delegates the `ContextSnapshot` assembly (results/responses
        encoding, completed-node bookkeeping, structured errors) to
        `FlowContext.to_snapshot()` (TASK-2052) — this method owns only
        the `FlowCheckpoint` wrapper: the monotonic checkpoint id/parent
        chain, the embedded `FlowDefinition`, per-node FSM states, and
        memory refs (post-review fix, FEAT-399: this used to duplicate
        `to_snapshot()`'s logic inline instead of calling it).

        Args:
            ctx: The live `FlowContext` (its non-serializable fields —
                `agent_registry`/`synthesis_client`/`trace_context` —
                are never included).
            status: Run status to embed (``running``/``suspended``/
                ``completed``/``failed``).

        Returns:
            The assembled `FlowCheckpoint` (not yet persisted).
        """
        lossy_out: list[bool] = []
        context_snapshot = ctx.to_snapshot(
            serializer=self._serializer,
            include_responses=self._include_responses,
            lossy_out=lossy_out,
        )

        if self._shared_data_projector is not None:
            # Replace the raw ctx.shared_data mapping with the caller's
            # allowlisted projection, encoded through the same type registry
            # as results/responses — a live object slipping into shared_data
            # (a SessionHost, a dispatcher, ...) must never reach the store,
            # and an unregistered-but-safe value degrades to a lossy repr
            # instead of breaking the write (spec §7).
            projected = self._shared_data_projector(ctx)
            safe_shared, shared_lossy = self._serializer.to_safe_with_meta(projected)
            context_snapshot.shared_data = safe_shared
            lossy_out.append(shared_lossy)

        lossy = any(lossy_out) if lossy_out else False

        node_states = [
            NodeStateSnapshot(
                node_id=node_id,
                fsm_state=getattr(info, "status", "unknown"),
                completed_at=None,
            )
            for node_id, info in ctx.node_metadata.items()
        ]

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
            lossy=lossy,
            input_metadata=self._input_metadata,
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

    # ── Awaited, required write path (spec §2/§7) ──────────────────────────

    async def checkpoint(self, ctx: FlowContext, *, status: str = "running") -> FlowCheckpoint:
        """Build and synchronously persist one required checkpoint.

        Unlike `make_listener()`'s fire-and-forget path — whose write
        failures are logged as warnings and swallowed by design — this
        method awaits the store write and propagates any encoding or
        persistence failure as `CheckpointPersistenceError`. Required mode
        exists precisely so a caller can refuse to route to a newly
        eligible downstream node until Redis durably confirms the upstream
        completion (spec §2 step 2 / step 6).

        Checkpoint numbering is monotonic only on success (spec §7: "do not
        advance the in-memory parent ID until the required store write
        succeeds") — on any failure the in-memory ``last_checkpoint_id``/
        ``parent_checkpoint_id`` are rolled back to their pre-call values,
        so a retried call reuses the same checkpoint id instead of
        skipping ahead of a write that never landed.

        Args:
            ctx: The live `FlowContext` to snapshot.
            status: Run status to embed (``running``/``suspended``/
                ``completed``/``failed``).

        Returns:
            The `FlowCheckpoint` that was successfully persisted.

        Raises:
            CheckpointPersistenceError: If assembling the snapshot or
                writing it to the store (ephemeral, or durable in
                write-through mode) fails for any reason, or if the resume
                lease was already lost/failed to renew (spec §7 — a lost
                lease means another process may already be resuming this
                same flow, a split-brain risk this write must not paper
                over).
        """
        self.raise_if_lease_lost()

        pre_last_id = self._last_checkpoint_id
        pre_parent_id = self._parent_checkpoint_id
        try:
            checkpoint = self._build_checkpoint(ctx, status=status)
        except Exception as exc:
            self._last_checkpoint_id = pre_last_id
            self._parent_checkpoint_id = pre_parent_id
            raise CheckpointPersistenceError(
                f"FlowCheckpointer.checkpoint(): failed to build snapshot for "
                f"flow_id={self._flow_id!r}: {exc}"
            ) from exc

        try:
            await self._store.put(checkpoint)
            if self._durable and self._durable_store is not None:
                await self._durable_store.put(checkpoint)
        except Exception as exc:
            self._last_checkpoint_id = pre_last_id
            self._parent_checkpoint_id = pre_parent_id
            raise CheckpointPersistenceError(
                f"FlowCheckpointer.checkpoint(): failed to persist flow_id="
                f"{self._flow_id!r} checkpoint_id={checkpoint.checkpoint_id}: {exc}"
            ) from exc

        return checkpoint

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
        """Renew the lease every ``ttl/3`` seconds until cancelled.

        A renewal exception, or a renewal that returns ``False`` (the lease
        expired and another holder may already have acquired it — a
        split-brain risk), both set ``self._lease_lost``. This method itself
        never raises: it stays a purely logging background task for generic
        (non-required-mode) callers, exactly as before. Required mode reads
        ``lease_lost`` from the scheduler's barrier instead (spec §7).
        """
        interval = max(ttl / 3, 1)
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    renewed = await self._store.renew_lease(self._flow_id, holder, ttl=ttl)
                    if not renewed:
                        raise FlowLockedError(
                            f"FlowCheckpointer: lease renewal for flow_id="
                            f"{self._flow_id!r} returned False — lease "
                            "expired or held by another holder"
                        )
                except Exception as exc:  # noqa: BLE001 - heartbeat must never crash the flow
                    self.logger.warning(
                        "FlowCheckpointer: lease renewal failed for flow_id=%s: %s",
                        self._flow_id,
                        exc,
                    )
                    self._lease_lost = True
                    self._lease_lost_exc = exc
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
