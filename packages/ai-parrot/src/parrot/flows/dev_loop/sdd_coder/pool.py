"""Execution pool runtime with private state, reservations and suspensions (FEAT-559 M2).

Each execution owns its effective seats, assigner, generation counter, cached
plan, active attempt reservations and local suspensions. Server startup must
not perform a model probe before the execution's ledger exclusions are known.
"""

from __future__ import annotations

import hashlib
import logging
from asyncio import Condition
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from parrot.flows.dev_loop.sdd_coder.models import (
    ExecutionPoolView,
    ExecutionSnapshot,
    ExecutionStatus,
    ModelKey,
    PoolSeatView,
    RosterConfig,
    RosterSeat,
)
from parrot.flows.dev_loop.sdd_coder.roster import ChunkAssigner
from parrot.knowledge.wiki.ledger.coder_suspensions import (
    CoderSuspensionStore,
    SuspensionReceipt,
    SuspensionRecord,
)

logger = logging.getLogger(__name__)


def _effective_key(seat: RosterSeat) -> Optional[ModelKey]:
    """Compute the exact `ModelKey` for a roster seat.

    Mirrors `RosterProbe._is_excluded`'s native-default normalization
    (`roster.py`): a native seat's identity is always `("native", model or
    "haiku")`. Returns `None` for an mcp seat with no configured model --
    that seat can never be admitted and is excluded from the pool's seat
    views rather than raising (the empty-model exclusion itself is the
    probe's job, spec: `model_identity_required`).
    """
    if seat.kind == "native":
        return ModelKey(backend="native", model=seat.model or "haiku")
    if not seat.model:
        return None
    return ModelKey(backend=seat.backend or "", model=seat.model)


def roster_fingerprint(roster: RosterConfig) -> str:
    """Deterministic, stable fingerprint of a roster's configuration.

    Used to detect `execution_config_mismatch` on resume (a caller reusing an
    `execution_id` with a roster that has since changed) -- computed once at
    pool construction, never recomputed from mutable runtime state. Public
    (not `_`-prefixed): the engine's `begin_execution` resume path needs the
    CURRENT roster's fingerprint to compare against an existing pool's, without
    constructing a throwaway `ExecutionPool` just to read the property.
    """
    canonical = roster.model_dump_json()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class ExecutionPool:
    """Per-execution runtime, condition, reservations and views.

    Bound immutably to `(execution_id, feature_id, worktree_path)` for its
    whole lifetime. Owns one `asyncio.Condition` for admission coordination;
    never shares mutable state (seats, rotation, exclusions, cached plan)
    with any other pool instance.
    """

    def __init__(
        self,
        *,
        execution_id: str,
        feature_id: str,
        worktree_path: str,
        roster: RosterConfig,
        seats: List[RosterSeat],
        suspension_store: CoderSuspensionStore,
        initial_exclusions: List[ModelKey],
    ) -> None:
        """Initialize one execution's private pool.

        Args:
            execution_id: Caller-generated UUID identifying this execution.
            feature_id: Feature this execution operates on.
            worktree_path: Absolute path to the canonical feature worktree.
            roster: Original roster configuration (read-only; never mutated).
            seats: Effective seats after probing -- this pool copies the list,
                it never mutates the caller's.
            suspension_store: Durable suspension history store.
            initial_exclusions: Models already suspended (from durable
                history) before this execution began; immutable for this
                execution's lifetime -- only `suspend()` adds further,
                execution-local exclusions on top of these.
        """
        UUID(execution_id)  # Raises ValueError if not a valid UUID string.

        self._execution_id = execution_id
        self._feature_id = feature_id
        self._worktree_path = worktree_path
        self._roster_fingerprint = roster_fingerprint(roster)
        self._seats: List[RosterSeat] = list(seats)
        self._suspension_store = suspension_store
        self._initial_exclusions: Set[ModelKey] = set(initial_exclusions)

        self._condition = Condition()
        self._status: ExecutionStatus = "active"
        self._generation = 0
        self._local_exclusions: Set[ModelKey] = set()
        # attempt_uid -> (task_id, ModelKey): the exact reservation `release()`
        # must free -- an attempt_uid alone does not identify which seat it holds.
        self._admitted: Dict[str, Tuple[str, ModelKey]] = {}
        self._busy_seats: Set[ModelKey] = set()
        self._cached_assigner: Optional[ChunkAssigner] = None
        self._fallback_required = False
        self._fallback_reason = ""
        self._persistence_degraded = False

        self._seat_views: Dict[ModelKey, PoolSeatView] = {}
        for seat in self._seats:
            key = _effective_key(seat)
            if key is None:
                logger.warning("Seat %r has no configured model; excluded from this pool's admission set", seat.label)
                continue
            suspended = key in self._initial_exclusions
            self._seat_views[key] = PoolSeatView(
                label=seat.label,
                kind=seat.kind,
                backend=seat.backend,
                configured_model=seat.model,
                resolved_key=key,
                available=True,
                suspended=suspended,
                reason="inherited_suspension" if suspended else "",
            )

    @property
    def execution_id(self) -> str:
        """The execution UUID this pool is bound to."""
        return self._execution_id

    @property
    def feature_id(self) -> str:
        """The feature ID this pool operates on."""
        return self._feature_id

    @property
    def worktree_path(self) -> str:
        """Absolute path to the canonical feature worktree."""
        return self._worktree_path

    @property
    def roster_fingerprint(self) -> str:
        """Fingerprint of the roster this pool was constructed with (resume validation)."""
        return self._roster_fingerprint

    @property
    def generation(self) -> int:
        """Current generation counter; increments on every suspension, invalidating cached plans."""
        return self._generation

    def view(self) -> ExecutionPoolView:
        """Return a read-only snapshot of the current pool state."""
        return ExecutionPoolView(
            execution_id=self._execution_id,
            feature_id=self._feature_id,
            worktree_path=self._worktree_path,
            status=self._status,
            generation=self._generation,
            seats=[view.model_copy() for view in self._seat_views.values()],
            fallback_required=self._fallback_required,
            fallback_reason=self._fallback_reason,
            persisted=not self._persistence_degraded,
            persistence_degraded=self._persistence_degraded,
        )

    def snapshot(self) -> ExecutionSnapshot:
        """Return a durable snapshot for journaling/restoration (TASK-3282 owns the filesystem side).

        `native_reservations`/`outstanding_job_ids` are intentionally empty
        here: this pool tracks MCP admission reservations only -- the engine
        (out of this task's scope) enriches those two fields from its own
        native-prep/job bookkeeping before journaling to disk.
        """
        return ExecutionSnapshot(
            execution_id=self._execution_id,
            feature_id=self._feature_id,
            worktree_path=self._worktree_path,
            roster_fingerprint=self._roster_fingerprint,
            admitted_attempts={uid: task_id for uid, (task_id, _key) in self._admitted.items()},
            native_reservations={},
            outstanding_job_ids=[],
            local_exclusions=list(self._local_exclusions),
            inherited_exclusions=list(self._initial_exclusions),
            status=self._status,
            generation=self._generation,
        )

    async def admit(self, task_id: str, key: ModelKey) -> str:
        """Reserve `key` for one attempt of `task_id`, returning its reservation UID.

        Blocks (releasing the condition) while `key` is busy with a healthy,
        non-excluded seat. Every wake-up re-checks status/exclusion from
        scratch -- a key suspended while something waits on it raises
        `ValueError` instead of looping or hanging forever.

        Raises:
            ValueError: the pool is closed/recovering, `key` is excluded
                (initial or local), unknown to this pool, or probe-failed.
        """
        async with self._condition:
            while True:
                if self._status in ("closed", "recovery_required"):
                    raise ValueError(f"cannot admit to a {self._status!r} execution pool")
                if key in self._initial_exclusions or key in self._local_exclusions:
                    raise ValueError(f"model {key.backend}/{key.model} is excluded from this execution")
                seat_view = self._seat_views.get(key)
                if seat_view is None:
                    raise ValueError(f"model {key.backend}/{key.model} is not a seat of this pool")
                if seat_view.probe_unavailable:
                    raise ValueError(f"model {key.backend}/{key.model} failed its probe and is unavailable")
                if key not in self._busy_seats:
                    break
                await self._condition.wait()

            attempt_uid = uuid4().hex
            self._admitted[attempt_uid] = (task_id, key)
            self._busy_seats.add(key)
            seat_view.busy = True
            return attempt_uid

    async def release(self, attempt_uid: str) -> None:
        """Release a settled attempt's reservation and wake every waiter.

        Unknown `attempt_uid` is a no-op (logged): a duplicate/late release
        must never raise into an already-finished caller.
        """
        async with self._condition:
            entry = self._admitted.pop(attempt_uid, None)
            if entry is None:
                logger.warning("release(): unknown attempt_uid=%s (already released or never admitted)", attempt_uid)
                return
            _task_id, key = entry
            self._busy_seats.discard(key)
            seat_view = self._seat_views.get(key)
            if seat_view is not None:
                seat_view.busy = False
            self._condition.notify_all()

    async def suspend(self, record: SuspensionRecord) -> SuspensionReceipt:
        """Exclude every alias in `record.blocked_keys` for the rest of this execution, then persist.

        Local state changes (and the `generation` bump that invalidates any
        cached plan) happen under the condition, BEFORE the durable append --
        no later admission can select a just-suspended model even if the
        ledger write is slow. Disk I/O never holds the condition. Does not
        release a live reservation: a suspended-but-busy seat keeps running
        until its own `release()`.
        """
        async with self._condition:
            for key in record.blocked_keys:
                self._local_exclusions.add(key)
                seat_view = self._seat_views.get(key)
                if seat_view is not None:
                    seat_view.available = False
                    seat_view.suspended = True
                    seat_view.reason = record.reason
                    seat_view.suspension_id = record.suspension_id
                    seat_view.suspended_until = record.expires_at.isoformat()
            self._generation += 1
            self._cached_assigner = None
            # Spec §2: state is active|exhausted|recovery_required|closed --
            # this suspension may have been the last eligible seat. Only ever
            # transition FROM "active": never downgrade a "closed" or already
            # "recovery_required" pool back to "exhausted".
            if self._status == "active" and self.is_exhausted():
                self._status = "exhausted"
            # Wake every admit() waiter now: eligibility already changed under
            # this lock, so a waiter for a just-suspended key raises instead
            # of looping forever waiting for a `release()` that would not help.
            self._condition.notify_all()

        persisted = True
        try:
            receipt = await self._suspension_store.record(record)
        except Exception as exc:  # noqa: BLE001 -- persistence failure must be explicit, never silently OK
            logger.error("Failed to persist suspension %s: %s", record.suspension_id, exc, exc_info=True)
            persisted = False
            receipt = SuspensionReceipt(
                suspension_id=record.suspension_id,
                execution_id=record.execution_id,
                blocked_keys=record.blocked_keys,
                persisted=False,
                expires_at=record.expires_at,
            )

        async with self._condition:
            receipt.pool_generation = self._generation
            if not persisted:
                self._persistence_degraded = True
        return receipt

    def assigner(self) -> Optional[ChunkAssigner]:
        """Return the cached `ChunkAssigner` over currently eligible seats, or `None` when exhausted.

        Never constructs a `ChunkAssigner` over an empty seat list (its
        constructor rejects that) -- an exhausted/all-suspended-or-busy pool
        is represented as `None`, not as an empty assigner or a raised error.
        """
        if self._cached_assigner is not None:
            return self._cached_assigner
        eligible = [
            seat
            for seat in self._seats
            for key in (_effective_key(seat),)
            if key is not None
            and key not in self._busy_seats
            and (view := self._seat_views.get(key)) is not None
            and view.available
            and not view.suspended
            and not view.probe_unavailable
        ]
        if not eligible:
            return None
        self._cached_assigner = ChunkAssigner(eligible)
        return self._cached_assigner

    def is_exhausted(self) -> bool:
        """True when no seat remains that could ever be selected right now.

        A busy-but-healthy seat is NOT exhausted -- it becomes eligible again
        once its holder releases; only suspended/unavailable/probe-failed
        seats count against eligibility here.
        """
        return not any(
            view.available and not view.suspended and not view.probe_unavailable for view in self._seat_views.values()
        )

    async def close(self) -> None:
        """Mark the pool closed: no new admissions; wakes every waiter to fail fast instead of hanging."""
        async with self._condition:
            self._status = "closed"
            self._condition.notify_all()

    async def mark_recovery_required(self) -> None:
        """Mark the pool as requiring reconciliation after a restart; wakes waiters to fail fast."""
        async with self._condition:
            self._status = "recovery_required"
            self._condition.notify_all()
