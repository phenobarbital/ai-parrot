"""In-memory versioned artifact backend (FEAT-538, decision D1).

This is *the* pluggable backend of ``WorkingMemoryCatalog`` — not a
sibling index. It answers four questions the catalog alone cannot:

1. **Which exact bytes did a step prove something with?** Aliases are
   mutable; ``artifact_id@version`` is not. Overwriting an alias
   allocates a *new version* of the same identity and moves the alias to
   it, leaving the old version valid and resolvable. An overwrite is
   therefore never a mutation of prior evidence.
2. **Whose is it?** Every operation takes a trusted
   :class:`~parrot.tools.working_memory.task_memory.models.TaskScope`
   first and checks it. A globally unique ``artifact_id`` is an
   identifier, not a capability.
3. **Are we still holding the bytes?** Retention is byte-accounted
   against a bounded LRU. When bytes go, the descriptor says so —
   ``availability`` flips and, for *pinned* evidence, an explicit
   invalidation receipt is raised. Nothing is quietly presented as
   verified after its bytes are gone.
4. **Does the fingerprint mean anything?** That question belongs to
   :mod:`.snapshots`, and this module never second-guesses its answer:
   whatever it reports as unverifiable is recorded unverifiable.

.. warning::

   **Delivery A is not durable.** This backend is process-local. It is
   for tests and single-process compatibility; nothing here survives a
   restart. Durable multi-pod continuity arrives with Delivery B's
   PostgreSQL store and blob write-through.

Concurrency
-----------

Snapshotting and hashing dominate registration cost (Phase 0 measured
~9.5 s for a 256 MiB numeric frame) so they run on a worker thread
*outside* the mutation lock. Version allocation, alias movement, LRU
accounting and publication all happen on the owning event loop under a
single :class:`asyncio.Lock`. Two concurrent writers to the same alias
therefore serialize at allocation and receive distinct, monotonically
increasing versions — while neither blocks the other's hashing.

The lock is never held across snapshotting, and never across tool
execution.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, Sequence, Set, Tuple, runtime_checkable

from parrot.interfaces.artifact_store import ArtifactPage, PayloadRefusal, PayloadResult

from .config import TaskMemoryConfig
from .models import (
    ArtifactAvailability,
    ArtifactDescriptor,
    ArtifactKind,
    Attribution,
    CursorError,
    EvidenceRef,
    LimitExceeded,
    Limits,
    ScopeViolation,
    TaskScope,
    utc_now,
)
from .snapshots import ContentSnapshot, SnapshotOutcome, capture_snapshot_async
from .store._base import bounded_limit, decode_cursor, encode_cursor

__all__ = (
    "DEFAULT_ARTIFACT_PAGE",
    "EvictionReason",
    "InvalidationReceipt",
    "CapacityReport",
    "SpillReceipt",
    "SpillHandler",
    "InMemoryArtifactStore",
)

logger = logging.getLogger(__name__)

#: Default page size for artifact listings.
DEFAULT_ARTIFACT_PAGE: int = 50

#: Guidance handed back on an over-ceiling read. Points at the tool that
#: computes over the data in place instead of shipping it to the model.
_TOO_LARGE_GUIDANCE: str = (
    "payload exceeds the configured byte ceiling; use wm_compute_and_store to "
    "operate on it in place, or request a bounded page with offset/limit"
)


class EvictionReason(str):
    """Why a version's retained bytes were released."""

    #: Byte budget exhausted and the version was not pinned.
    CAPACITY = "capacity"
    #: Byte budget exhausted and *even pinned* evidence had to go.
    CAPACITY_PINNED = "capacity_pinned"
    #: An explicit :meth:`InMemoryArtifactStore.evict` call.
    EXPLICIT = "explicit"


@dataclass(frozen=True)
class InvalidationReceipt:
    """Record that pinned evidence could not be retained.

    Delivery A cannot promise retained bytes. When the byte budget forces
    out a version that a task still references as evidence, silently
    dropping it would leave a step labeled valid with nothing behind it.
    Instead the store invalidates the version, keeps a metadata
    tombstone, and raises one of these.

    The task service drains these and turns them into
    ``artifact_invalidated`` journal events. They are *receipts*, not
    events: this module has no journal and must not acquire one.

    Attributes:
        scope: Owning scope.
        ref: The exact version whose bytes were released.
        task_id: The task that owned the version.
        pinned_by: Every task that referenced it as evidence.
        reason: Why the bytes went.
        released_bytes: How many bytes were reclaimed.
        occurred_at: When.
    """

    scope: TaskScope
    ref: EvidenceRef
    task_id: Optional[str]
    pinned_by: Tuple[str, ...]
    reason: str
    released_bytes: int
    occurred_at: Any


@dataclass(frozen=True)
class CapacityReport:
    """What the store is currently holding.

    Both retained *snapshots* and retained *live references* count, which
    is what makes this an honest figure: an unverifiable value is not
    copied, but keeping a reference to it keeps it alive just the same.

    Attributes:
        retained_bytes: Bytes currently accounted against the budget.
        limit: The configured ceiling.
        version_count: Versions with bytes still retained.
        pinned_bytes: Of ``retained_bytes``, how much is pinned evidence
            and therefore only evictable as a last resort.
        tombstone_count: Versions whose metadata survives without bytes.
    """

    retained_bytes: int
    limit: int
    version_count: int
    pinned_bytes: int
    tombstone_count: int

    @property
    def available_bytes(self) -> int:
        """Headroom left before eviction begins (never negative)."""
        return max(0, self.limit - self.retained_bytes)


@dataclass(frozen=True)
class SpillReceipt:
    """What a durable tier returns after accepting an oversized value.

    Attributes:
        storage_ref: Backend reference to the written bytes. Never
            published before the bytes exist.
        byte_size: Size of what was written.
        fingerprint: Canonical content fingerprint, when the tier
            computed one. ``None`` leaves the version unverifiable rather
            than inventing an integrity claim.
        fingerprint_algorithm: Identity and version of that algorithm.
    """

    storage_ref: str
    byte_size: int
    fingerprint: Optional[str] = None
    fingerprint_algorithm: Optional[str] = None


@runtime_checkable
class SpillHandler(Protocol):
    """Optional durable tier for values above the RAM snapshot cap.

    Delivery A ships **no implementation**: without a handler an
    oversized supported value is recorded with bounded metadata and
    ``evidence_verifiable=False``, because nothing is retaining it.
    Delivery B's blob adapter implements this.
    """

    async def spill(
        self,
        scope: TaskScope,
        ref: EvidenceRef,
        kind: ArtifactKind,
        value: Any,
    ) -> SpillReceipt:
        """Write a value to durable storage and return its reference.

        Args:
            scope: Trusted runtime scope.
            ref: The version being written.
            kind: Its evidence type.
            value: The value to write.

        Returns:
            The receipt describing what was written.
        """
        ...

    async def load(self, scope: TaskScope, ref: EvidenceRef, storage_ref: str, *, max_bytes: int) -> Any:
        """Read spilled bytes back under a hard ceiling.

        Args:
            scope: Trusted runtime scope.
            ref: The version to read.
            storage_ref: Reference returned by :meth:`spill`.
            max_bytes: Hard byte ceiling.

        Returns:
            The materialized value.
        """
        ...


# ─────────────────────────────────────────────────────────────
# Internal records
# ─────────────────────────────────────────────────────────────


@dataclass
class _Identity:
    """One artifact identity: a stable id and its version counter.

    The counter survives an alias drop. That is the whole point of the
    tombstone: after ``drop`` then re-``put`` under the same key, the
    next version is ``latest + 1``, never ``1`` again, so a still-pinned
    old ``artifact_id@1`` can never be shadowed by a fresh unrelated
    ``artifact_id@1``.

    Attributes:
        artifact_id: The stable identity.
        latest_version: Highest version ever allocated, alias or not.
        alias_live: Whether an alias currently points at this identity.
    """

    artifact_id: str
    latest_version: int = 0
    alias_live: bool = True


@dataclass
class _VersionRecord:
    """One immutable version plus whatever the store still holds for it.

    Attributes:
        descriptor: The read projection. Replaced wholesale on change —
            :class:`ArtifactDescriptor` is frozen.
        payload: The retained snapshot, the retained live reference, or
            ``None`` once the bytes are gone.
        retained_bytes: Bytes accounted against the LRU budget.
        is_snapshot: Whether ``payload`` is an independent copy. ``False``
            means it is a reference to the caller's object, which may
            mutate — such a version is never verifiable evidence.
        pins: Task ids referencing this version as evidence.
        sequence: Monotonic insertion order, for stable listing.
    """

    descriptor: ArtifactDescriptor
    payload: Any
    retained_bytes: int
    is_snapshot: bool
    pins: Set[str] = field(default_factory=set)
    sequence: int = 0


_AliasKey = Tuple[str, Optional[str], str]
_VersionKey = Tuple[str, str, int]


class InMemoryArtifactStore:
    """Process-local :class:`ArtifactStore` with scoped versioned aliases.

    Satisfies the full :class:`parrot.interfaces.artifact_store.ArtifactStore`
    protocol and passes ``ArtifactStoreConformance``.

    Args:
        config: Task-memory configuration. Supplies the RAM snapshot cap
            (64 MiB) and the retained-bytes budget (512 MiB).
        spill_handler: Optional durable tier for oversized supported
            values. Delivery A supplies none.
    """

    def __init__(
        self,
        config: Optional[TaskMemoryConfig] = None,
        *,
        spill_handler: Optional[SpillHandler] = None,
    ) -> None:
        """Initialize an empty store."""
        self._config = config or TaskMemoryConfig()
        self._spill = spill_handler
        self.logger = logger

        self._aliases: Dict[_AliasKey, str] = {}
        self._identities: Dict[Tuple[str, str], _Identity] = {}
        self._versions: Dict[_VersionKey, _VersionRecord] = {}
        #: Access-ordered keys of versions that still hold bytes.
        self._lru: "OrderedDict[_VersionKey, None]" = OrderedDict()

        self._retained_bytes: int = 0
        self._generation: int = 0
        self._counter: int = 0
        self._sequence: int = 0
        self._receipts: List[InvalidationReceipt] = []
        self._lock = asyncio.Lock()

    # ── identity helpers ────────────────────────────────────────────

    @staticmethod
    def _alias_key(scope: TaskScope, task_id: Optional[str], key: str) -> _AliasKey:
        """Return the namespace key an alias lives in.

        The task id is part of the key, which is what stops a plain key
        from ever searching another task's namespace.

        Args:
            scope: Owning scope.
            task_id: Owning task, or ``None`` for unassociated entries.
            key: The alias.

        Returns:
            The composite alias key.
        """
        return (scope.cache_key(), task_id, key)

    @staticmethod
    def _version_key(scope: TaskScope, ref: EvidenceRef) -> _VersionKey:
        """Return the storage key for one exact version.

        Args:
            scope: Owning scope.
            ref: The version.

        Returns:
            The composite version key.
        """
        return (scope.cache_key(), ref.artifact_id, ref.version)

    def _lookup(self, scope: TaskScope, ref: EvidenceRef) -> Optional[_VersionRecord]:
        """Return a version record after enforcing scope.

        A version in another scope reads as **absent**, not forbidden: a
        "this exists but you may not see it" answer is an existence
        oracle.

        Args:
            scope: Caller's trusted scope.
            ref: The version to find.

        Returns:
            The record, or ``None``.
        """
        return self._versions.get(self._version_key(scope, ref))

    # ── registration ────────────────────────────────────────────────

    async def put(
        self,
        scope: TaskScope,
        key: str,
        value: Any,
        *,
        task_id: Optional[str] = None,
        kind: Optional[ArtifactKind] = None,
        description: str = "",
        producer_call_id: Optional[str] = None,
        attribution: Attribution = Attribution.NONE,
        turn_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        transaction: Optional[Any] = None,
        pin_for: Optional[str] = None,
    ) -> ArtifactDescriptor:
        """Register a value, allocating or incrementing its version.

        Snapshotting and fingerprinting run on a worker thread **before**
        the lock is taken; only allocation and publication are
        serialized. See the module docstring.

        ``pin_for`` registers and pins in **one** act, and that matters
        for more than convenience. Capacity is enforced at the end of
        this call, and a version that is not yet pinned is an ordinary
        eviction candidate — so a value pinned only afterwards can be
        evicted *at birth*, before its pin ever applies. Passing
        ``pin_for`` is the only way a newly registered version competes
        for retention on equal terms with existing pinned evidence.

        Args:
            scope: Trusted runtime scope.
            key: Working-memory alias to publish under.
            value: The value to register.
            task_id: Owning task, when one is selected.
            kind: Explicit evidence type; inferred when ``None``.
            description: Human-readable description (retained by the
                caller's catalog, not stored in the descriptor).
            producer_call_id: The physical attempt that produced it.
            attribution: How that attempt was attributed.
            turn_id: The conversation turn.
            metadata: Caller metadata. Unused here; the catalog owns it.
            transaction: Shared transaction. In-memory storage has
                nothing to enlist, so this is accepted and ignored.
            pin_for: Task id to pin this version for, atomically with
                registration. See above.

        Returns:
            The read projection of the newly registered version.

        Raises:
            LimitExceeded: If the alias key is longer than
                :data:`Limits.MAX_IDENTIFIER`.
        """
        if len(key) > Limits.MAX_IDENTIFIER:
            raise LimitExceeded("artifact alias", Limits.MAX_IDENTIFIER, len(key))

        # Heavy work first, off the loop and outside the lock.
        snapshot = await capture_snapshot_async(value, max_bytes=self._config.snapshot_max_bytes, kind=kind)

        spill: Optional[SpillReceipt] = None
        if snapshot.outcome is SnapshotOutcome.SPILL_REQUIRED and self._spill is not None:
            provisional = EvidenceRef(artifact_id="pending", version=1)
            spill = await self._spill.spill(scope, provisional, snapshot.kind, value)

        async with self._lock:
            ref = self._allocate(scope, task_id, key)
            record = self._build_record(
                scope=scope,
                ref=ref,
                key=key,
                value=value,
                task_id=task_id,
                producer_call_id=producer_call_id,
                attribution=attribution,
                snapshot=snapshot,
                spill=spill,
            )
            if pin_for is not None:
                record.pins.add(pin_for)
            self._versions[self._version_key(scope, ref)] = record
            if record.retained_bytes:
                self._lru[self._version_key(scope, ref)] = None
                self._retained_bytes += record.retained_bytes
            self._generation += 1
            self._enforce_budget()
            return self._versions[self._version_key(scope, ref)].descriptor

    def _allocate(self, scope: TaskScope, task_id: Optional[str], key: str) -> EvidenceRef:
        """Allocate the next version for an alias, creating its identity if new.

        Called under the lock. This is the only place version numbers are
        minted, which is what makes them unique and monotonic under
        concurrent writers.

        Args:
            scope: Owning scope.
            task_id: Owning task namespace.
            key: The alias.

        Returns:
            The freshly allocated reference.
        """
        alias_key = self._alias_key(scope, task_id, key)
        scope_key = scope.cache_key()
        artifact_id = self._aliases.get(alias_key)

        if artifact_id is None:
            self._counter += 1
            artifact_id = f"art_{self._counter:08d}"
            self._identities[(scope_key, artifact_id)] = _Identity(artifact_id=artifact_id)
            self._aliases[alias_key] = artifact_id

        identity = self._identities[(scope_key, artifact_id)]
        identity.latest_version += 1
        identity.alias_live = True
        return EvidenceRef(artifact_id=artifact_id, version=identity.latest_version)

    def _build_record(
        self,
        *,
        scope: TaskScope,
        ref: EvidenceRef,
        key: str,
        value: Any,
        task_id: Optional[str],
        producer_call_id: Optional[str],
        attribution: Attribution,
        snapshot: ContentSnapshot,
        spill: Optional[SpillReceipt],
    ) -> _VersionRecord:
        """Turn a snapshot outcome into a stored version record.

        The three outcomes are handled differently and deliberately:

        - ``CAPTURED`` — an independent copy is retained and accounted.
          Only this path can be verifiable evidence.
        - ``SPILL_REQUIRED`` — with a durable tier, the bytes live there
          and availability is ``persisted``. Without one, nothing is
          retaining it: availability is ``missing`` and the version is
          unverifiable. Delivery A cannot promise retained bytes.
        - ``UNVERIFIABLE`` — the value has no meaningful fingerprint, so
          it is kept as a **live reference** rather than a copy. It stays
          usable as working memory but is never evidence, and its bytes
          are still accounted because holding the reference keeps the
          object alive.

        Args:
            scope: Owning scope.
            ref: The allocated version.
            key: The alias it was published under.
            value: The caller's original value.
            task_id: Owning task.
            producer_call_id: Producing attempt.
            attribution: How that attempt was attributed.
            snapshot: The snapshot outcome.
            spill: Durable receipt, when the value was spilled.

        Returns:
            The record to store.
        """
        self._sequence += 1
        payload: Any = None
        retained = 0
        is_snapshot = False
        storage_ref: Optional[str] = None
        availability = ArtifactAvailability.MISSING
        fingerprint = snapshot.fingerprint
        algorithm = snapshot.fingerprint_algorithm
        verifiable = snapshot.evidence_verifiable
        byte_size: Optional[int] = snapshot.account.live_bytes

        if snapshot.outcome is SnapshotOutcome.CAPTURED:
            payload = snapshot.payload
            retained = snapshot.account.snapshot_bytes
            is_snapshot = True
            availability = ArtifactAvailability.MEMORY
            byte_size = snapshot.account.snapshot_bytes
        elif snapshot.outcome is SnapshotOutcome.SPILL_REQUIRED and spill is not None:
            availability = ArtifactAvailability.PERSISTED
            storage_ref = spill.storage_ref
            byte_size = spill.byte_size
            fingerprint = spill.fingerprint
            algorithm = spill.fingerprint_algorithm
            verifiable = bool(spill.fingerprint) and snapshot.kind.is_supported_evidence
        elif snapshot.outcome is SnapshotOutcome.UNVERIFIABLE:
            # Kept usable, never claimed as evidence. The reference may
            # mutate under us — that is exactly why it is unverifiable.
            payload = value
            retained = snapshot.account.live_bytes or 0
            availability = ArtifactAvailability.MEMORY

        descriptor = ArtifactDescriptor(
            ref=ref,
            alias=key,
            scope=scope,
            task_id=task_id,
            producer_call_id=producer_call_id,
            attribution=attribution,
            kind=snapshot.kind,
            availability=availability,
            fingerprint=fingerprint,
            fingerprint_algorithm=algorithm,
            evidence_verifiable=verifiable,
            byte_size=byte_size,
            shape=snapshot.shape,
            schema_summary=snapshot.schema_summary,
            storage_ref=storage_ref,
            created_at=utc_now(),
        )
        return _VersionRecord(
            descriptor=descriptor,
            payload=payload,
            retained_bytes=retained,
            is_snapshot=is_snapshot,
            sequence=self._sequence,
        )

    # ── capacity ────────────────────────────────────────────────────

    def _enforce_budget(self) -> None:
        """Evict retained bytes until the store is within its budget.

        Called under the lock. Unpinned versions go first, in LRU order.
        Only when nothing unpinned is left does pinned evidence go — and
        then an :class:`InvalidationReceipt` is raised for each, because
        no eviction may silently remove evidence while leaving a step
        labeled valid.

        The second pass is reachable only because :meth:`put` can pin
        atomically via ``pin_for``. Without that, the version being
        registered would always be the unpinned newcomer, evicting it
        would always restore the (already within-budget) prior state, and
        pinned evidence could never be reached — the sacrifice path would
        be dead code pretending to be a safeguard.
        """
        limit = self._config.memory_cache_max_bytes

        for allow_pinned in (False, True):
            while self._retained_bytes > limit:
                victim = self._next_victim(allow_pinned=allow_pinned)
                if victim is None:
                    break
                reason = EvictionReason.CAPACITY_PINNED if allow_pinned else EvictionReason.CAPACITY
                self._release(victim, reason=reason, invalidate=allow_pinned)
            if self._retained_bytes <= limit:
                return

    def _next_victim(self, *, allow_pinned: bool) -> Optional[_VersionKey]:
        """Return the least recently used evictable version key.

        Args:
            allow_pinned: Whether pinned evidence may be chosen.

        Returns:
            The victim's key, or ``None`` when nothing qualifies.
        """
        for version_key in self._lru:
            record = self._versions.get(version_key)
            if record is None or not record.retained_bytes:
                continue
            if record.pins and not allow_pinned:
                continue
            return version_key
        return None

    def _release(self, version_key: _VersionKey, *, reason: str, invalidate: bool) -> int:
        """Drop one version's bytes, keeping its metadata tombstone.

        Called under the lock.

        Args:
            version_key: The version to release.
            reason: Why, for the receipt.
            invalidate: Whether to also mark the evidence invalid. True
                only when pinned evidence had to go.

        Returns:
            Bytes reclaimed.
        """
        record = self._versions.get(version_key)
        if record is None or not record.retained_bytes:
            return 0

        released = record.retained_bytes
        self._retained_bytes -= released
        self._lru.pop(version_key, None)

        update: Dict[str, Any] = {"availability": ArtifactAvailability.MISSING}
        if record.descriptor.storage_ref:
            # Durable bytes still exist; only the RAM copy went.
            update["availability"] = ArtifactAvailability.PERSISTED
        if invalidate:
            update["invalidated"] = True
            update["invalidated_at"] = utc_now()

        record.payload = None
        record.retained_bytes = 0
        record.descriptor = record.descriptor.model_copy(update=update)
        self._generation += 1

        if invalidate:
            self._receipts.append(
                InvalidationReceipt(
                    scope=record.descriptor.scope,
                    ref=record.descriptor.ref,
                    task_id=record.descriptor.task_id,
                    pinned_by=tuple(sorted(record.pins)),
                    reason=reason,
                    released_bytes=released,
                    occurred_at=utc_now(),
                )
            )
            self.logger.warning(
                "[TaskMemory] pinned evidence %s released under memory pressure (%d bytes); "
                "recorded invalidation receipt",
                record.descriptor.ref,
                released,
            )
        return released

    def capacity(self) -> CapacityReport:
        """Return what the store is currently holding.

        Returns:
            The :class:`CapacityReport`.
        """
        pinned = sum(r.retained_bytes for r in self._versions.values() if r.pins)
        return CapacityReport(
            retained_bytes=self._retained_bytes,
            limit=self._config.memory_cache_max_bytes,
            version_count=sum(1 for r in self._versions.values() if r.retained_bytes),
            pinned_bytes=pinned,
            tombstone_count=sum(1 for r in self._versions.values() if not r.retained_bytes),
        )

    def drain_receipts(self) -> Tuple[InvalidationReceipt, ...]:
        """Take and clear the pending invalidation receipts.

        The task service converts these into ``artifact_invalidated``
        journal events. This module deliberately owns no journal.

        Returns:
            The receipts, oldest first.
        """
        drained = tuple(self._receipts)
        self._receipts.clear()
        return drained

    # ── pins ────────────────────────────────────────────────────────

    async def pin_evidence(self, scope: TaskScope, ref: EvidenceRef, task_id: str) -> bool:
        """Record that ``task_id`` references this version as evidence.

        Pinning is what keeps a version out of ordinary LRU eviction.
        Several tasks may pin the same version — cross-task evidence
        references defer deletion until *every* pin is gone.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version to pin.
            task_id: The task referencing it.

        Returns:
            ``True`` when the pin was recorded, ``False`` when the
            version does not exist in this scope.
        """
        async with self._lock:
            record = self._lookup(scope, ref)
            if record is None:
                return False
            record.pins.add(task_id)
            return True

    async def unpin_evidence(self, scope: TaskScope, ref: EvidenceRef, task_id: str) -> bool:
        """Remove one task's evidence reference to a version.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version.
            task_id: The task releasing it.

        Returns:
            ``True`` when a pin was removed.
        """
        async with self._lock:
            record = self._lookup(scope, ref)
            if record is None or task_id not in record.pins:
                return False
            record.pins.discard(task_id)
            return True

    async def pins_for(self, scope: TaskScope, ref: EvidenceRef) -> Tuple[str, ...]:
        """Return the task ids pinning a version.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version.

        Returns:
            The pinning task ids, sorted. Empty when unknown or unpinned.
        """
        async with self._lock:
            record = self._lookup(scope, ref)
            return tuple(sorted(record.pins)) if record is not None else ()

    # ── reads ───────────────────────────────────────────────────────

    async def get_current(
        self,
        scope: TaskScope,
        key: str,
        *,
        task_id: Optional[str] = None,
    ) -> Optional[ArtifactDescriptor]:
        """Resolve an alias to the version it currently points at.

        Args:
            scope: Trusted runtime scope.
            key: The alias.
            task_id: Owning task namespace.

        Returns:
            The current descriptor, or ``None`` when the alias is unknown
            in this namespace.
        """
        async with self._lock:
            artifact_id = self._aliases.get(self._alias_key(scope, task_id, key))
            if artifact_id is None:
                return None
            identity = self._identities.get((scope.cache_key(), artifact_id))
            if identity is None or not identity.alias_live:
                return None
            record = self._versions.get((scope.cache_key(), artifact_id, identity.latest_version))
            return record.descriptor if record is not None else None

    async def get_version(
        self,
        scope: TaskScope,
        ref: EvidenceRef,
        *,
        task_id: Optional[str] = None,
    ) -> Optional[ArtifactDescriptor]:
        """Resolve one exact version, checking scope.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version.
            task_id: Owning task, when validating a same-scope cross-task
                evidence reference. A mismatch is reported as absent.

        Returns:
            The descriptor, or ``None``.
        """
        async with self._lock:
            record = self._lookup(scope, ref)
            if record is None:
                return None
            if task_id is not None and record.descriptor.task_id not in (None, task_id):
                # A same-scope cross-task reference must be explicit and
                # validated; it is never resolved implicitly here.
                return None
            version_key = self._version_key(scope, ref)
            if version_key in self._lru:
                self._lru.move_to_end(version_key, last=True)
            return record.descriptor

    async def load_payload(
        self,
        scope: TaskScope,
        ref: EvidenceRef,
        *,
        max_bytes: int,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> PayloadResult:
        """Materialize a version's payload under a hard byte ceiling.

        The ceiling is checked **before** anything is handed back; an
        over-limit read carries no payload at all. For tabular values a
        bounded page may be returned without the whole table ever being
        measured against the ceiling — the page is measured instead.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version to read.
            max_bytes: Hard byte ceiling. ``0`` means never materialize.
            offset: Row offset, for tabular values.
            limit: Row count, for tabular values.

        Returns:
            Either the payload or a refusal reason.

        Raises:
            ValueError: If ``max_bytes`` is negative.
        """
        if max_bytes < 0:
            raise ValueError(f"max_bytes must be >= 0, got {max_bytes}")

        async with self._lock:
            record = self._lookup(scope, ref)
            if record is None:
                return PayloadResult(
                    ref=ref,
                    kind=ArtifactKind.OBJECT,
                    refusal=PayloadRefusal.MISSING,
                    guidance="no such artifact version in this scope",
                )

            descriptor = record.descriptor
            version_key = self._version_key(scope, ref)
            if version_key in self._lru:
                self._lru.move_to_end(version_key, last=True)

            if record.payload is None:
                refusal = PayloadRefusal.INVALIDATED if descriptor.invalidated else PayloadRefusal.MISSING
                if descriptor.availability is ArtifactAvailability.EXPIRED:
                    refusal = PayloadRefusal.EXPIRED
                return PayloadResult(
                    ref=ref,
                    kind=descriptor.kind,
                    refusal=refusal,
                    byte_size=descriptor.byte_size,
                    guidance=(
                        "the retained bytes are gone; the descriptor and fingerprint remain, "
                        "but the content must be regenerated to be read"
                    ),
                )

            if max_bytes == 0:
                return PayloadResult(
                    ref=ref,
                    kind=descriptor.kind,
                    refusal=PayloadRefusal.TOO_LARGE,
                    byte_size=descriptor.byte_size,
                    guidance="raw reads are disabled (max_bytes=0); " + _TOO_LARGE_GUIDANCE,
                )

            if descriptor.kind is ArtifactKind.DATAFRAME and (offset is not None or limit is not None):
                return self._page_dataframe(record, ref, max_bytes=max_bytes, offset=offset, limit=limit)

            size = record.retained_bytes or descriptor.byte_size or 0
            if size > max_bytes:
                return PayloadResult(
                    ref=ref,
                    kind=descriptor.kind,
                    refusal=PayloadRefusal.TOO_LARGE,
                    byte_size=size,
                    guidance=_TOO_LARGE_GUIDANCE,
                )

            total_rows = descriptor.shape[0] if descriptor.kind is ArtifactKind.DATAFRAME and descriptor.shape else None
            return PayloadResult(
                ref=ref,
                kind=descriptor.kind,
                payload=record.payload,
                byte_size=size,
                returned_bytes=size,
                total_rows=total_rows,
            )

    def _page_dataframe(
        self,
        record: _VersionRecord,
        ref: EvidenceRef,
        *,
        max_bytes: int,
        offset: Optional[int],
        limit: Optional[int],
    ) -> PayloadResult:
        """Return a bounded row page of a tabular version.

        A page is sliced and measured on its own, so a small page is
        readable from a table far larger than the ceiling — the point of
        pagination is that the whole table is never materialized for the
        caller.

        Args:
            record: The stored version.
            ref: Its reference.
            max_bytes: Hard byte ceiling for the page.
            offset: Row offset.
            limit: Row count.

        Returns:
            The page, or a refusal when even the page is too large.
        """
        frame = record.payload
        start = offset or 0
        if start < 0:
            raise ValueError(f"offset must be >= 0, got {start}")
        page_rows = self._config.resolve_page_limit(limit)
        total_rows = int(frame.shape[0])
        page = frame.iloc[start : start + page_rows]
        page_bytes = int(page.memory_usage(deep=True).sum())

        if page_bytes > max_bytes:
            return PayloadResult(
                ref=ref,
                kind=ArtifactKind.DATAFRAME,
                refusal=PayloadRefusal.TOO_LARGE,
                byte_size=page_bytes,
                offset=start,
                limit=page_rows,
                total_rows=total_rows,
                guidance="even the requested page exceeds the ceiling; request fewer rows",
            )

        return PayloadResult(
            ref=ref,
            kind=ArtifactKind.DATAFRAME,
            payload=page,
            byte_size=record.retained_bytes,
            returned_bytes=page_bytes,
            offset=start,
            limit=page_rows,
            total_rows=total_rows,
            truncated=(start + page_rows) < total_rows or start > 0,
        )

    async def list(
        self,
        scope: TaskScope,
        *,
        task_id: Optional[str] = None,
        kinds: Optional[Sequence[ArtifactKind]] = None,
        limit: int = DEFAULT_ARTIFACT_PAGE,
        cursor: Optional[str] = None,
        as_of_seq: Optional[int] = None,
    ) -> ArtifactPage:
        """Page artifact descriptors in a scope.

        Descriptors are metadata only; building the page touches no
        payload, calls no ``repr()`` and computes no summary.

        Args:
            scope: Trusted runtime scope.
            task_id: Restrict to one task's namespace.
            kinds: Restrict to these evidence types.
            limit: Bounded page size.
            cursor: Opaque cursor from a previous page.
            as_of_seq: Accepted for contract symmetry. The in-memory
                store has no journal fence, so it is recorded in the
                cursor query and otherwise unused.

        Returns:
            A bounded page of descriptors.

        Raises:
            CursorError: If the cursor is malformed, out of bounds, or
                was issued for a different scope or query.
        """
        async with self._lock:
            size = bounded_limit(limit, default=DEFAULT_ARTIFACT_PAGE)
            wanted = tuple(k.value for k in kinds) if kinds else None
            query = {"task_id": task_id, "kinds": wanted, "as_of_seq": as_of_seq}

            scope_key = scope.cache_key()
            rows = [r for (s, _, _), r in self._versions.items() if s == scope_key]
            if task_id is not None:
                rows = [r for r in rows if r.descriptor.task_id == task_id]
            if kinds is not None:
                allowed = set(kinds)
                rows = [r for r in rows if r.descriptor.kind in allowed]
            rows.sort(key=lambda r: (r.descriptor.ref.artifact_id, r.descriptor.ref.version))

            start = 0
            if cursor is not None:
                start = int(decode_cursor(cursor, scope, query)["offset"])
                if start > len(rows):
                    raise CursorError("cursor is out of bounds")

            window = rows[start : start + size]
            next_cursor = encode_cursor(scope, query, {"offset": start + size}) if start + size < len(rows) else None
            return ArtifactPage(
                items=tuple(r.descriptor for r in window),
                next_cursor=next_cursor,
                availability_generation=self._generation,
            )

    # ── mutation ────────────────────────────────────────────────────

    async def invalidate(
        self,
        scope: TaskScope,
        ref: EvidenceRef,
        *,
        reason: str,
        transaction: Optional[Any] = None,
    ) -> ArtifactDescriptor:
        """Mark one version's content as no longer valid evidence.

        Bytes are left alone: invalidation is a statement about evidence,
        not about storage, and a persisted payload remains loadable.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version.
            reason: Why.
            transaction: Accepted and ignored by the in-memory store.

        Returns:
            The updated descriptor.

        Raises:
            ScopeViolation: If the version does not exist in this scope.
        """
        async with self._lock:
            record = self._lookup(scope, ref)
            if record is None:
                raise ScopeViolation("artifact version does not exist in this scope")
            record.descriptor = record.descriptor.model_copy(
                update={
                    "invalidated": True,
                    "invalidated_at": utc_now(),
                    "evidence_verifiable": False,
                }
            )
            self._generation += 1
            self.logger.info("[TaskMemory] invalidated %s: %s", ref, reason)
            return record.descriptor

    async def evict(self, scope: TaskScope, ref: EvidenceRef) -> bool:
        """Release a version's retained bytes, keeping its metadata.

        Explicit eviction does **not** invalidate: the caller asked for
        the bytes back and the fingerprint still describes what the
        version contained. Pinned evidence is still evicted on request —
        but a receipt is raised so the caller cannot lose track of it.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version.

        Returns:
            ``True`` when bytes were released.
        """
        async with self._lock:
            record = self._lookup(scope, ref)
            if record is None:
                return False
            if not record.retained_bytes:
                # Still move the generation: an already-empty version is
                # not a state change, so it must not pretend to be one.
                return False
            pinned = bool(record.pins)
            released = self._release(
                self._version_key(scope, ref),
                reason=EvictionReason.EXPLICIT,
                invalidate=pinned,
            )
            return released > 0

    async def drop_alias(self, scope: TaskScope, key: str, *, task_id: Optional[str] = None) -> bool:
        """Remove a live alias without deleting the versions behind it.

        The identity and its version counter survive as a tombstone, so a
        later re-``put`` under the same key continues at ``latest + 1``.
        Restarting at ``1`` would let a fresh unrelated version shadow
        still-pinned evidence.

        Args:
            scope: Trusted runtime scope.
            key: The alias to remove.
            task_id: Owning task namespace.

        Returns:
            ``True`` when the alias existed.
        """
        async with self._lock:
            alias_key = self._alias_key(scope, task_id, key)
            artifact_id = self._aliases.get(alias_key)
            if artifact_id is None:
                return False
            identity = self._identities.get((scope.cache_key(), artifact_id))
            if identity is not None:
                identity.alias_live = False
            self._generation += 1
            return True

    # ── lifecycle ───────────────────────────────────────────────────

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["_MemoryTransaction"]:
        """Yield a transaction handle this store and a task store can share.

        In-memory storage has nothing to commit or roll back; the handle
        exists so the same call sites work against both backends.

        Yields:
            The transaction handle.
        """
        tx = _MemoryTransaction()
        try:
            yield tx
        except Exception:
            await tx.rollback()
            raise

    async def close(self) -> None:
        """Drop everything held in memory."""
        async with self._lock:
            self._aliases.clear()
            self._identities.clear()
            self._versions.clear()
            self._lru.clear()
            self._receipts.clear()
            self._retained_bytes = 0


class _MemoryTransaction:
    """No-op transaction handle for the in-memory backend."""

    def __init__(self) -> None:
        """Initialize an active transaction."""
        self._active = True

    @property
    def is_active(self) -> bool:
        """Whether this transaction is still open."""
        return self._active

    async def rollback(self) -> None:
        """Close the transaction without committing."""
        self._active = False
