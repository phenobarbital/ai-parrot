"""Versioned artifact-store contract (FEAT-538).

.. important::

   This is **not** :class:`parrot.storage.artifacts.ArtifactStore`. That
   pre-existing class is conversation-artifact CRUD and is unrelated to
   task memory. The name collision is deliberate and called out here
   because the specification's D1 names this contract ``ArtifactStore``:
   it *is* the pluggable backend of ``WorkingMemoryCatalog``, not a
   sibling of it. Always import it from this module by its full path.

Decision D1 in one sentence: there is **one** artifact store, it backs
the working-memory catalog, and :class:`~parrot.tools.working_memory.
task_memory.models.ArtifactDescriptor` is a read projection of a
versioned entry in it — not a second parallel index.

This is a **leaf contract module**: stdlib, ``pydantic`` and the
task-memory domain models only. It must not import ``pandas``, a REPL
worker, or a concrete database backend. In particular it never takes a
``DataFrame`` in a signature: payloads cross this boundary as ``Any``,
and the *backend* owns knowing which concrete types it supports.

Invariants the contract encodes:

- **Aliases are keyed by ``(scope, task_id, key)``.** A plain key never
  searches another task. Cross-task evidence requires an explicit,
  access-validated, pinned reference.
- **Versions are monotonic within an identity.** The first write of an
  alias allocates ``artifact_id, version=1``; an overwrite increments the
  same identity's version and moves the alias. Older versions stay valid
  and resolvable — an overwrite is not a mutation of the old version.
- **Version lookup is not authorization.** ``get_version`` takes a scope
  and must check it; a globally unique artifact id is not a capability.
- **A drop removes the live alias, not the pinned snapshot.** Evidence
  survives ``drop_stored``; only retention may remove it, and only when
  nothing pins it.
- **Reads are byte-bounded before materialization.** ``load_payload``
  takes a hard ``max_bytes``; an over-limit read returns a refusal
  carrying no payload rather than loading it and truncating afterwards.
  Truncating an object's ``repr`` after loading it does not make it safe.
"""

from __future__ import annotations

from typing import Any, AsyncContextManager, Optional, Protocol, Sequence, Tuple, runtime_checkable

from parrot.tools.working_memory.task_memory.models import (
    ArtifactDescriptor,
    ArtifactKind,
    Attribution,
    EvidenceRef,
    Limits,
    TaskScope,
)
from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "PayloadRefusal",
    "PayloadResult",
    "ArtifactPage",
    "ArtifactStore",
)


class _Result(BaseModel):
    """Shared configuration for contract return models."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)


class PayloadRefusal(str):
    """Why a payload read returned nothing.

    A plain ``str`` subclass so the reason travels intact through JSON
    and into a tool result without a second enum to keep in sync.
    """

    #: The payload's bytes exceed the caller's or the configuration's ceiling.
    TOO_LARGE = "too_large"
    #: The artifact version is known but its bytes are gone.
    MISSING = "missing"
    #: The artifact version's retention expired.
    EXPIRED = "expired"
    #: The value's type has no safe materialization path.
    UNSUPPORTED = "unsupported"
    #: The version was invalidated; its content is no longer evidence.
    INVALIDATED = "invalidated"


class PayloadResult(_Result):
    """Outcome of a bounded payload read.

    Either ``payload`` is present, or ``refusal`` explains why it is not.
    Both are never set: a refusal that also carried data would defeat the
    byte ceiling it exists to enforce.

    Attributes:
        ref: The exact artifact version read.
        kind: Evidence type of that version.
        payload: The materialized value, when the read succeeded.
        refusal: A :class:`PayloadRefusal` reason, when it did not.
        byte_size: Size of the full payload, reported even on refusal so
            a caller can tell how far over the ceiling it was.
        returned_bytes: Size actually materialized.
        offset: Row offset of the returned page, for tabular reads.
        limit: Row count of the returned page, for tabular reads.
        total_rows: Total rows available, for tabular reads.
        truncated: Whether a page was returned rather than the whole
            value. A page may be read *without* rehydrating the whole
            table.
        guidance: What the caller should do instead, on refusal.
    """

    ref: EvidenceRef
    kind: ArtifactKind
    payload: Optional[Any] = None
    refusal: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    byte_size: Optional[int] = Field(default=None, ge=0)
    returned_bytes: int = Field(default=0, ge=0)
    offset: Optional[int] = Field(default=None, ge=0)
    limit: Optional[int] = Field(default=None, ge=1)
    total_rows: Optional[int] = Field(default=None, ge=0)
    truncated: bool = False
    guidance: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)

    @property
    def ok(self) -> bool:
        """Whether the read produced a payload."""
        return self.refusal is None


class ArtifactPage(_Result):
    """A bounded page of artifact descriptors.

    Attributes:
        items: The descriptors, in stable order.
        next_cursor: Opaque scoped cursor for the following page, or
            ``None`` at the end.
        availability_generation: Monotonic marker that changes whenever
            availability changes without a task event — an eviction, an
            expiry, a worker restart. Recall folds this into its cache
            key, because "deterministic" cannot mean "expired content
            stays available forever at the same task sequence".
    """

    items: Tuple[ArtifactDescriptor, ...] = ()
    next_cursor: Optional[str] = Field(default=None, max_length=Limits.MAX_CURSOR)
    availability_generation: int = Field(default=0, ge=0)


@runtime_checkable
class ArtifactStore(Protocol):
    """Scoped, versioned, byte-bounded storage behind the catalog (D1).

    Every method takes ``scope`` first and must check it before touching
    anything. Implementations run CPU-heavy snapshotting, hashing and
    serialization off the event loop, and never hold the catalog lock
    across tool execution.
    """

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
    ) -> ArtifactDescriptor:
        """Register a value, allocating or incrementing its version.

        Within the ``(scope, task_id, key)`` namespace the first write
        allocates ``artifact_id`` at ``version=1``; a later write to the
        same key atomically increments **that same identity's** version
        and moves the alias to it. The previous version remains valid and
        resolvable.

        The implementation captures structural metadata and, under the
        configured cap, an independent snapshot. When it cannot prove the
        snapshot is detached and reproducible — nested mutable cells, an
        unsupported type, a copy or hash failure — it must return a
        descriptor with ``evidence_verifiable=False`` rather than claim
        integrity it cannot demonstrate.

        In durable mode the bytes are written and verified **before**
        registration succeeds, and the in-process cache is published only
        after commit. A storage reference is never published before its
        bytes exist.

        Args:
            scope: Trusted runtime scope.
            key: Working-memory alias to publish under.
            value: The value to register.
            task_id: Owning task, when one is selected.
            kind: Explicit evidence type; inferred when ``None``.
            description: Human-readable description.
            producer_call_id: The physical attempt that produced it.
            attribution: How that attempt was attributed.
            turn_id: The conversation turn.
            metadata: Caller metadata to retain.
            transaction: Shared transaction to enlist in, so the alias
                index, evidence metadata and ``artifact_registered``
                event commit together.

        Returns:
            The read projection of the newly registered version.

        Raises:
            LimitExceeded: If a bounded field or byte budget is exceeded.
            ScopeViolation: If the alias belongs to a different scope.
        """
        ...

    async def get_current(
        self,
        scope: TaskScope,
        key: str,
        *,
        task_id: Optional[str] = None,
    ) -> Optional[ArtifactDescriptor]:
        """Resolve an alias to the version it currently points at.

        A plain key never searches another task's namespace.

        Args:
            scope: Trusted runtime scope.
            key: The alias.
            task_id: Owning task namespace.

        Returns:
            The current version's descriptor, or ``None`` when the alias
            is unknown in this namespace.
        """
        ...

    async def get_version(
        self,
        scope: TaskScope,
        ref: EvidenceRef,
        *,
        task_id: Optional[str] = None,
    ) -> Optional[ArtifactDescriptor]:
        """Resolve one exact version.

        The scope check is not optional: a globally unique artifact id is
        an identifier, not a capability.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version to resolve.
            task_id: Owning task, when validating a same-scope
                cross-task evidence reference.

        Returns:
            The descriptor, or ``None`` when the version does not exist
            in this scope.
        """
        ...

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

        ``max_bytes`` is enforced **while** serializing and **before**
        materialization, not by truncating afterwards. ``0`` means never
        materialize. For tabular values, ``offset``/``limit`` return a
        bounded page that may be read without rehydrating the whole
        table; both the decoded page size and the serialized returned
        bytes are enforced.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version to read.
            max_bytes: Hard byte ceiling for this read.
            offset: Row offset, for tabular values.
            limit: Row count, for tabular values.

        Returns:
            A :class:`PayloadResult` carrying either the payload or a
            refusal reason. An over-limit read carries **no** payload.
        """
        ...

    async def invalidate(
        self,
        scope: TaskScope,
        ref: EvidenceRef,
        *,
        reason: str,
        transaction: Optional[Any] = None,
    ) -> ArtifactDescriptor:
        """Mark one version's content as no longer valid evidence.

        Invalidation is a statement about *evidence*, not about bytes: a
        persisted payload may still exist and remain loadable. It is also
        distinct from a stale REPL binding, which sets
        ``binding_invalid`` instead.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version to invalidate.
            reason: Why.
            transaction: Shared transaction to enlist in.

        Returns:
            The updated descriptor.

        Raises:
            ScopeViolation: If the version belongs to a different scope.
        """
        ...

    async def list(
        self,
        scope: TaskScope,
        *,
        task_id: Optional[str] = None,
        kinds: Optional[Sequence[ArtifactKind]] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
        as_of_seq: Optional[int] = None,
    ) -> ArtifactPage:
        """Page artifact descriptors in a scope.

        Descriptors are metadata only. Building one must not call
        ``compact_summary()``, ``describe()`` or an arbitrary object's
        ``repr()``: listing is on recall's hot path and must stay cheap
        and leak-free.

        Args:
            scope: Trusted runtime scope.
            task_id: Restrict to one task's namespace.
            kinds: Restrict to these evidence types.
            limit: Bounded page size.
            cursor: Opaque cursor from a previous page.
            as_of_seq: Fence the read at a journal sequence.

        Returns:
            A bounded page of descriptors.

        Raises:
            CursorError: If the cursor is malformed, out of bounds, or
                was issued for a different scope.
        """
        ...

    async def evict(self, scope: TaskScope, ref: EvidenceRef) -> bool:
        """Release a version's retained bytes, keeping its metadata.

        Eviction never silently removes evidence while leaving a step
        labeled valid: the caller records an invalidation event when the
        version was pinned, and a metadata tombstone always remains.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version to evict.

        Returns:
            ``True`` when bytes were released, ``False`` when there were
            none to release.
        """
        ...

    async def drop_alias(self, scope: TaskScope, key: str, *, task_id: Optional[str] = None) -> bool:
        """Remove a live alias without deleting the versions behind it.

        A tombstone is retained for the identity so that a later
        drop/recreate cycle cannot accidentally reuse a version number.

        Args:
            scope: Trusted runtime scope.
            key: The alias to remove.
            task_id: Owning task namespace.

        Returns:
            ``True`` when the alias existed.
        """
        ...

    def transaction(self) -> AsyncContextManager[Any]:
        """Open a transaction this store and a task store can share.

        Returns:
            An async context manager yielding a ``Transaction``.
        """
        ...

    async def close(self) -> None:
        """Release any resources the store holds."""
        ...
