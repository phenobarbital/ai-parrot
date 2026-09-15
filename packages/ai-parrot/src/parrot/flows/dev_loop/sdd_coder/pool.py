"""Execution pool runtime with private state, reservations and suspensions (FEAT-559 M2).

Each execution owns its effective seats, assigner, generation counter, cached
plan, active attempt reservations and local suspensions. Server startup must
not perform a model probe before the execution's ledger exclusions are known.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Set
from uuid import UUID

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


class ExecutionPool:
    """Per-execution runtime, condition, reservations and views.

    Bound immutably to `(execution_id, feature_id, worktree_path)` for its
    whole lifetime. Owns one asyncio.Condition for admission coordination;
    never shares mutable state with other pools.
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
        """Initialize execution pool with explicit scope and roster.

        Args:
            execution_id: Caller-generated UUID identifying this execution.
            feature_id: Feature this execution operates on.
            worktree_path: Absolute path to the feature worktree.
            roster: Original roster configuration (immutable).
            seats: Effective available seats after probing.
            suspension_store: Durable suspension history store.
            initial_exclusions: Models suspended before this execution began.
        """
        # Validate execution_id is a proper UUID
        UUID(execution_id)  # Raises ValueError if invalid
        
        self._execution_id = execution_id
        self._feature_id = feature_id
        self._worktree_path = worktree_path
        self._roster = roster
        self._seats = list(seats)  # Copy to prevent external mutation
        self._suspension_store = suspension_store
        self._initial_exclusions = set(initial_exclusions)
        
        # Runtime state
        self._condition = asyncio.Condition()
        self._status: ExecutionStatus = "active"
        self._generation = 0
        self._local_exclusions: Set[ModelKey] = set()
        self._admitted_attempts: Dict[str, str] = {}  # attempt_uid -> task_id
        self._busy_seats: Set[ModelKey] = set()  # Currently reserved seats
        self._cached_assigner: Optional[ChunkAssigner] = None
        self._fallback_required = False
        self._fallback_reason = ""
        self._persistence_degraded = False
        
        # Build initial seat views
        self._seat_views: Dict[ModelKey, PoolSeatView] = {}
        for seat in self._seats:
            key = ModelKey(
                backend=seat.backend or "native" if seat.kind == "native" else seat.backend or "",
                model=seat.model
            )
            self._seat_views[key] = PoolSeatView(
                label=seat.label,
                kind=seat.kind,
                backend=seat.backend,
                configured_model=seat.model,
                available=True,
                suspended=key in self._initial_exclusions,
                reason="inherited_suspension" if key in self._initial_exclusions else "",
            )
            
        # Apply initial exclusions
        for key in self._initial_exclusions:
            if key in self._seat_views:
                view = self._seat_views[key]
                view.available = False
                view.suspended = True
                view.reason = "inherited_suspension"

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
        """Absolute path to the feature worktree."""
        return self._worktree_path

    @property
    def generation(self) -> int:
        """Current generation counter, incremented on every suspension."""
        return self._generation

    def view(self) -> ExecutionPoolView:
        """Return a snapshot view of the current pool state."""
        return ExecutionPoolView(
            execution_id=self._execution_id,
            feature_id=self._feature_id,
            worktree_path=self._worktree_path,
            status=self._status,
            generation=self._generation,
            seats=list(self._seat_views.values()),
            fallback_required=self._fallback_required,
            fallback_reason=self._fallback_reason,
            persisted=not self._persistence_degraded,
            persistence_degraded=self._persistence_degraded,
        )

    def snapshot(self) -> ExecutionSnapshot:
        """Return a durable snapshot for journaling/restoration."""
        return ExecutionSnapshot(
            execution_id=self._execution_id,
            feature_id=self._feature_id,
            worktree_path=self._worktree_path,
            roster_fingerprint="",  # TODO: Implement roster fingerprinting
            admitted_attempts=self._admitted_attempts.copy(),
            native_reservations={},  # TODO: Track native reservations
            outstanding_job_ids=[],  # TODO: Track job IDs
            local_exclusions=list(self._local_exclusions),
            inherited_exclusions=list(self._initial_exclusions),
            status=self._status,
            generation=self._generation,
        )

    async def admit(self, task_id: str, key: ModelKey) -> str:
        """Reserve a seat for a task attempt, returning the reservation UID.

        Admission rejects excluded keys and closed/degraded/recovery states
        atomically. Busy healthy keys await the condition.

        Args:
            task_id: The task being attempted.
            key: The model key to reserve.

        Returns:
            A unique attempt UID for this reservation.

        Raises:
            ValueError: If the pool is closed, degraded, or the key is excluded.
        """
        async with self._condition:
            # Check pool state
            if self._status in ("closed", "recovery_required"):
                raise ValueError(f"Cannot admit to {self._status} pool")
            
            # Check exclusions
            if key in self._initial_exclusions or key in self._local_exclusions:
                raise ValueError(f"Model {key} is excluded from this execution")
                
            # Check seat availability
            if key not in self._seat_views:
                raise ValueError(f"Model {key} not found in pool seats")
                
            seat_view = self._seat_views[key]
            if not seat_view.available or seat_view.suspended or seat_view.probe_unavailable:
                raise ValueError(f"Model {key} is not available")
                
            # Wait if seat is busy
            while key in self._busy_seats:
                await self._condition.wait()
                
            # Reserve the seat
            attempt_uid = str(UUID(int=hash((self._execution_id, task_id, key.backend, key.model)) & (1<<128)-1))
            self._admitted_attempts[attempt_uid] = task_id
            self._busy_seats.add(key)
            
            # Update seat view
            seat_view.busy = True
            
            return attempt_uid

    async def release(self, attempt_uid: str) -> None:
        """Release a completed attempt reservation and wake waiters.

        Args:
            attempt_uid: The reservation to release.
        """
        async with self._condition:
            if attempt_uid not in self._admitted_attempts:
                logger.warning("Attempt %s not found in admitted attempts", attempt_uid)
                return
                
            self._admitted_attempts.pop(attempt_uid, None)
            
            # Find the corresponding seat and release it
            for key, seat_view in self._seat_views.items():
                if seat_view.busy and key in self._busy_seats:
                    self._busy_seats.discard(key)
                    seat_view.busy = False
                    break
                    
            # Wake all waiters
            self._condition.notify_all()

    async def suspend(self, record: SuspensionRecord) -> SuspensionReceipt:
        """Suspend models locally and persist the incident.

        Suspension must not release a live reservation. All aliases of the
        blocked keys are excluded from future admission in this execution.

        Args:
            record: The suspension incident to record.

        Returns:
            The persistence receipt, with degraded status if append failed.
        """
        async with self._condition:
            # Add to local exclusions
            for key in record.blocked_keys:
                self._local_exclusions.add(key)
                if key in self._seat_views:
                    seat_view = self._seat_views[key]
                    seat_view.available = False
                    seat_view.suspended = True
                    seat_view.reason = record.reason
                    seat_view.suspension_id = record.suspension_id
                    # Format expires_at as ISO string
                    seat_view.suspended_until = record.expires_at.isoformat()
                    
            # Increment generation to invalidate cached plans
            self._generation += 1
            self._cached_assigner = None
            
            # Persist the suspension (off the condition lock)
            try:
                receipt = await self._suspension_store.record(record)
                receipt.pool_generation = self._generation
            except Exception as exc:
                logger.error("Failed to persist suspension: %s", exc, exc_info=True)
                self._persistence_degraded = True
                # Create a minimal receipt for local use
                receipt = SuspensionReceipt(
                    suspension_id=record.suspension_id,
                    execution_id=record.execution_id,
                    blocked_keys=record.blocked_keys,
                    persisted=False,
                    expires_at=record.expires_at,
                    pool_generation=self._generation,
                )
                
            # Wake all waiters since eligibility changed
            self._condition.notify_all()
            
            return receipt

    def assigner(self) -> ChunkAssigner:
        """Get or create a chunk assigner for eligible seats."""
        if self._cached_assigner is None:
            # Filter seats to only those that are available and not suspended
            eligible_seats = []
            for seat in self._seats:
                key = ModelKey(
                    backend=seat.backend or "native" if seat.kind == "native" else seat.backend or "",
                    model=seat.model
                )
                if key not in self._initial_exclusions and key not in self._local_exclusions:
                    seat_view = self._seat_views.get(key)
                    if seat_view and seat_view.available and not seat_view.suspended:
                        eligible_seats.append(seat)
                        
            self._cached_assigner = ChunkAssigner(eligible_seats)
        return self._cached_assigner

    def close(self) -> None:
        """Mark the pool as closed, preventing new admissions."""
        with self._condition:
            self._status = "closed"
            self._condition.notify_all()

    def mark_recovery_required(self) -> None:
        """Mark the pool as requiring recovery."""
        with self._condition:
            self._status = "recovery_required"
            self._condition.notify_all()

    def is_exhausted(self) -> bool:
        """Check if all seats are exhausted (no available seats)."""
        with self._condition:
            available_count = sum(
                1 for view in self._seat_views.values() 
                if view.available and not view.suspended and not view.probe_unavailable
            )
            return available_count == 0 and not self._fallback_required