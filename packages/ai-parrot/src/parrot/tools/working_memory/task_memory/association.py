"""Task association and hot Redis keys (FEAT-538).

A task lives in PostgreSQL (Delivery B) or in process memory (Delivery A).
What lives in Redis is only the *association*: which tasks are open in a
conversation, and which one is currently selected. That distinction is
the whole design, and two rules follow from it:

- **Task creation commits first, association second.** If the association
  write then fails, the caller gets the committed task id back together
  with an explicit degradation marker, so it can recover or select the
  task — never create a second one. Duplicating a task because a cache
  write failed would be far worse than a missing pointer.
- **A missing association never deletes a task.** The association is a
  pointer, not the record. Losing it costs a selection, not the work.

The association is stored inside
``ConversationHistory.metadata["task_memory"]`` so it shares the
conversation's lifecycle and its scoping, rather than inventing a second
source of truth about which conversation a task belongs to.

Concurrency
-----------

The association is written by task-memory code; ``metadata["compaction"]``
is written by the compaction layer, which knows nothing about tasks. They
share one Redis hash field. A task-scoped lock therefore cannot protect
it — **the other writer would not take the lock**. That is why the merge
is a server-side ``WATCH``/``MULTI``/``EXEC`` compare-and-swap
(:meth:`~parrot.memory.redis.RedisConversation.merge_metadata`): it is
enforced by Redis against *every* writer to that key, including ones that
have never heard of this module.

Hot keys
--------

Three families, all scoped by :meth:`TaskScope.cache_key`, which
percent-encodes its components so a value containing the separator cannot
forge another scope's key:

===================  =====  ================================================
family               TTL    purpose
===================  =====  ================================================
``_task_lease``      30 s   append ownership; renewed only by its owner
``_task_recall``     10 m   the recall cache
``_task_ctx``        24 h   turn-context cache — **never authoritative**
===================  =====  ================================================

The context cache is a convenience. Task state comes from the store; a
cached context that disagrees is stale, not a second opinion.

Call ownership vs. the append lease
-----------------------------------

``_task_lease`` carries **two different things**, and conflating them is
the specific bug this design exists to prevent:

``<prefix>_task_lease:<scope>:<task>``
    The *append* lease. Short, contended, and expected to expire
    constantly — it serialises journal appends, nothing more.

``<prefix>_task_lease:<scope>:<task>:call:<call_id>``
    *Per-call ownership*, heartbeated for as long as the call is actually
    running. A ten-minute tool call renews this for ten minutes.

An expired **append lease is not evidence that a call died** — a healthy
long-running call lets it lapse constantly, because it only needs it
while appending. Only expired *call ownership* is evidence, and even then
only when Redis was reachable enough to say so. :meth:`is_call_alive`
therefore returns a **tri-state**: ``True`` alive, ``False`` provably
gone, ``None`` unknown. Recovery must treat ``None`` as "leave it alone".
Reading "not alive" out of an unreachable cache is how a healthy call
gets declared dead and its external effect retried.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .config import TaskMemoryConfig
from .models import Limits, TaskScope

__all__ = (
    "ASSOCIATION_KEY",
    "LEASE_FAMILY",
    "RECALL_FAMILY",
    "CONTEXT_FAMILY",
    "TaskAssociation",
    "AssociationResult",
    "TaskSelection",
    "TaskAssociationStore",
)

logger = logging.getLogger(__name__)

#: Key under ``ConversationHistory.metadata`` holding the association.
#: Deliberately namespaced: everything else in that dict belongs to
#: someone else and must survive every write this module makes.
ASSOCIATION_KEY: str = "task_memory"

#: Redis key families, appended to the memory's configured prefix.
LEASE_FAMILY: str = "_task_lease"
RECALL_FAMILY: str = "_task_recall"
CONTEXT_FAMILY: str = "_task_ctx"

#: Renew a lease only if we still own it. Read-and-expire must be atomic:
#: between a GET and a PEXPIRE the lease can expire and be taken by
#: someone else, and we would then extend *their* lease.
_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""

#: Release a lease only if we still own it, for the same reason.
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    Returns:
        The timestamp.
    """
    return datetime.now(timezone.utc).isoformat()


class TaskAssociation(BaseModel):
    """Which tasks a conversation knows about, and which one is selected.

    Attributes:
        open_task_ids: Non-terminal tasks in this conversation, in the
            order they were opened.
        selected_task_id: The authoritative selection. An omitted task id
            resolves **only** from here — never by similarity.
        revision: Monotonic association revision, so a caller can detect
            that someone else changed the selection underneath it.
        updated_at: When the association last changed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    open_task_ids: Tuple[str, ...] = ()
    selected_task_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    revision: int = Field(default=0, ge=0)
    updated_at: Optional[str] = None

    @classmethod
    def from_metadata(cls, metadata: Optional[Dict[str, Any]]) -> "TaskAssociation":
        """Read the association out of a conversation's metadata.

        Tolerant by design: a malformed or absent block yields an empty
        association rather than raising. A conversation whose association
        is unreadable has simply lost a pointer, and refusing to talk to
        the user over it would be a worse outcome than re-selecting.

        Args:
            metadata: The conversation metadata, or ``None``.

        Returns:
            The association.
        """
        if not isinstance(metadata, dict):
            return cls()
        raw = metadata.get(ASSOCIATION_KEY)
        if not isinstance(raw, dict):
            return cls()
        try:
            open_ids = raw.get("open_task_ids") or []
            if not isinstance(open_ids, (list, tuple)):
                open_ids = []
            selected = raw.get("selected_task_id")
            return cls(
                open_task_ids=tuple(str(t) for t in open_ids)[: Limits.MAX_OPEN_TASKS_PER_SCOPE],
                selected_task_id=str(selected) if selected else None,
                revision=int(raw.get("revision", 0) or 0),
                updated_at=raw.get("updated_at"),
            )
        except (TypeError, ValueError):
            logger.warning("Unreadable task association block; treating the conversation as unassociated")
            return cls()

    def to_metadata_value(self) -> Dict[str, Any]:
        """Return the JSON-safe block stored under :data:`ASSOCIATION_KEY`.

        Returns:
            The serialized association.
        """
        return {
            "open_task_ids": list(self.open_task_ids),
            "selected_task_id": self.selected_task_id,
            "revision": self.revision,
            "updated_at": self.updated_at,
        }

    def with_task(self, task_id: str, *, select: bool = True) -> "TaskAssociation":
        """Return this association with ``task_id`` opened, optionally selected.

        Args:
            task_id: The task to register.
            select: Whether to make it the selected task.

        Returns:
            The new association.

        Raises:
            ValueError: If the scope already holds the maximum number of
                open tasks.
        """
        open_ids = list(self.open_task_ids)
        if task_id not in open_ids:
            if len(open_ids) >= Limits.MAX_OPEN_TASKS_PER_SCOPE:
                raise ValueError(f"cannot open more than {Limits.MAX_OPEN_TASKS_PER_SCOPE} tasks in one conversation")
            open_ids.append(task_id)
        return self.model_copy(
            update={
                "open_task_ids": tuple(open_ids),
                "selected_task_id": task_id if select else self.selected_task_id,
                "revision": self.revision + 1,
                "updated_at": _utc_now_iso(),
            }
        )

    def without_task(self, task_id: str) -> "TaskAssociation":
        """Return this association with ``task_id`` closed.

        Closing the selected task clears the selection rather than
        guessing a replacement — picking one would be exactly the
        similarity-style inference the specification forbids.

        Args:
            task_id: The task to close.

        Returns:
            The new association.
        """
        open_ids = tuple(t for t in self.open_task_ids if t != task_id)
        selected = None if self.selected_task_id == task_id else self.selected_task_id
        return self.model_copy(
            update={
                "open_task_ids": open_ids,
                "selected_task_id": selected,
                "revision": self.revision + 1,
                "updated_at": _utc_now_iso(),
            }
        )

    def selecting(self, task_id: str) -> "TaskAssociation":
        """Return this association with ``task_id`` selected.

        Args:
            task_id: The task to select. Registered as open if it was not
                already — this is how an explicit id repairs a lost
                association.

        Returns:
            The new association.

        Raises:
            ValueError: If the open-task ceiling would be exceeded.
        """
        return self.with_task(task_id, select=True)


class TaskSelection(BaseModel):
    """The answer to "which task are we talking about?".

    Attributes:
        task_id: The resolved task, when exactly one applies.
        needs_selection: Whether the caller must choose explicitly.
        candidates: Open task ids to choose between, when it must.
        association_revision: The revision this answer was read at.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: Optional[str] = None
    needs_selection: bool = False
    candidates: Tuple[str, ...] = ()
    association_revision: int = Field(default=0, ge=0)


class AssociationResult(BaseModel):
    """Outcome of an association write.

    ``degraded`` is the load-bearing field. A task that has been committed
    but not associated is still a real task: the caller must be told its
    id so it can select or recover it, and must **not** treat the failure
    as a reason to create another one.

    Attributes:
        association: The association as it now stands. On failure this is
            the last value that could be read.
        degraded: Whether the association could not be persisted.
        reason: Why, when it could not.
        task_id: The task the write concerned.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    association: TaskAssociation
    degraded: bool = False
    reason: Optional[str] = None
    task_id: Optional[str] = None


class TaskAssociationStore:
    """Reads and writes the association, and owns the hot Redis keys.

    Args:
        memory: The conversation memory holding the association. It must
            expose ``merge_metadata`` — that is,
            :class:`~parrot.memory.redis.RedisConversation` or something
            compatible. A memory without it is usable read-only.
        config: TTLs and capacity limits.
    """

    def __init__(self, memory: Any, config: Optional[TaskMemoryConfig] = None) -> None:
        """Initialize the store.

        Args:
            memory: The conversation memory.
            config: Configuration; defaults to :class:`TaskMemoryConfig`.
        """
        self._memory = memory
        self._config = config or TaskMemoryConfig()
        self.logger = logging.getLogger(f"{__name__}.{type(self).__name__}")

    # ── hot keys ─────────────────────────────────────────────────────

    def _prefix(self) -> str:
        """Return the memory's configured key prefix.

        Returns:
            The prefix, defaulting to ``"conversation"`` for a memory that
            does not expose one.
        """
        return getattr(self._memory, "key_prefix", "conversation")

    def key_for(self, family: str, scope: TaskScope, *, suffix: Optional[str] = None) -> str:
        """Build a scoped hot key.

        Args:
            family: One of :data:`LEASE_FAMILY`, :data:`RECALL_FAMILY`,
                :data:`CONTEXT_FAMILY`.
            scope: The trusted scope.
            suffix: Optional extra component (e.g. a task id).

        Returns:
            The key. Scope components are percent-encoded by
            :meth:`TaskScope.cache_key`, so a value containing ``:``
            cannot forge another scope's key.
        """
        from urllib.parse import quote

        key = f"{self._prefix()}{family}:{scope.cache_key()}"
        if suffix:
            key = f"{key}:{quote(str(suffix), safe='')}"
        return key

    def lease_key(self, scope: TaskScope, task_id: str) -> str:
        """Return the append-lease key for one task.

        Args:
            scope: The trusted scope.
            task_id: The task.

        Returns:
            The key.
        """
        return self.key_for(LEASE_FAMILY, scope, suffix=task_id)

    def call_lease_key(self, scope: TaskScope, task_id: str, call_id: str) -> str:
        """Return the per-call ownership key for one in-flight call.

        Deliberately a *sub-key* of the task's append lease rather than a
        fourth key family: the spec names three families, and ownership
        is a lease. Both components are percent-encoded, so the literal
        ``:call:`` separator cannot be forged by a task id or call id
        that happens to contain it.

        Args:
            scope: The trusted scope.
            task_id: The owning task.
            call_id: The physical attempt.

        Returns:
            The key.
        """
        from urllib.parse import quote

        return f"{self.lease_key(scope, task_id)}:call:{quote(str(call_id), safe='')}"

    def recall_key(self, scope: TaskScope, cache_digest: str) -> str:
        """Return the recall-cache key for one recall shape.

        Args:
            scope: The trusted scope.
            cache_digest: Digest of the recall's cache-key parts.

        Returns:
            The key.
        """
        return self.key_for(RECALL_FAMILY, scope, suffix=cache_digest)

    def context_key(self, scope: TaskScope) -> str:
        """Return the turn-context cache key.

        Args:
            scope: The trusted scope.

        Returns:
            The key. The context cache is never authoritative for task
            state.
        """
        return self.key_for(CONTEXT_FAMILY, scope)

    @property
    def _redis(self) -> Any:
        """Return the underlying Redis client, or ``None``."""
        return getattr(self._memory, "redis", None)

    # ── leases ───────────────────────────────────────────────────────

    async def acquire_lease(self, scope: TaskScope, task_id: str, owner: str) -> bool:
        """Take the append lease for a task, if it is free.

        Args:
            scope: The trusted scope.
            task_id: The task to lease.
            owner: Opaque identity of the acquirer.

        Returns:
            ``True`` when the lease was taken.
        """
        client = self._redis
        if client is None:
            return False
        acquired = await client.set(
            self.lease_key(scope, task_id), owner, nx=True, px=self._config.lease_ttl_seconds * 1000
        )
        return bool(acquired)

    async def renew_lease(self, scope: TaskScope, task_id: str, owner: str) -> bool:
        """Extend a lease we still own.

        Read-and-extend is done in one Lua call: between a separate GET
        and PEXPIRE the lease could expire and be taken by someone else,
        and we would then be extending *their* lease.

        Args:
            scope: The trusted scope.
            task_id: The leased task.
            owner: The identity that took the lease.

        Returns:
            ``True`` when the lease was still ours and was extended.
        """
        client = self._redis
        if client is None:
            return False
        result = await client.eval(
            _RENEW_SCRIPT, 1, self.lease_key(scope, task_id), owner, self._config.lease_ttl_seconds * 1000
        )
        return bool(result)

    async def release_lease(self, scope: TaskScope, task_id: str, owner: str) -> bool:
        """Release a lease we still own, and only that one.

        Args:
            scope: The trusted scope.
            task_id: The leased task.
            owner: The identity that took the lease.

        Returns:
            ``True`` when our lease was released; ``False`` when it had
            already expired and possibly belongs to someone else now.
        """
        client = self._redis
        if client is None:
            return False
        result = await client.eval(_RELEASE_SCRIPT, 1, self.lease_key(scope, task_id), owner)
        return bool(result)

    # ── per-call ownership (heartbeated) ─────────────────────────────

    def _call_ttl_ms(self, ttl_seconds: Optional[int]) -> int:
        """Resolve the call-ownership TTL in milliseconds.

        Args:
            ttl_seconds: Explicit override, or ``None`` for configured.

        Returns:
            The TTL in milliseconds.
        """
        seconds = self._config.lease_ttl_seconds if ttl_seconds is None else ttl_seconds
        return max(1, int(seconds * 1000))

    async def acquire_call(
        self, scope: TaskScope, task_id: str, call_id: str, owner: str, *, ttl_seconds: Optional[int] = None
    ) -> bool:
        """Claim ownership of one in-flight call.

        Args:
            scope: The trusted scope.
            task_id: The owning task.
            call_id: The physical attempt.
            owner: Opaque identity of this worker.
            ttl_seconds: TTL override; defaults to the configured lease
                TTL. Ownership must be heartbeated to outlive it.

        Returns:
            ``True`` when ownership was taken. ``False`` when someone
            else already holds it, or when there is no Redis to hold it
            in — the caller must not treat ``False`` as "the call is
            dead".
        """
        client = self._redis
        if client is None:
            return False
        taken = await client.set(
            self.call_lease_key(scope, task_id, call_id),
            owner,
            nx=True,
            px=self._call_ttl_ms(ttl_seconds),
        )
        return bool(taken)

    async def heartbeat_call(
        self, scope: TaskScope, task_id: str, call_id: str, owner: str, *, ttl_seconds: Optional[int] = None
    ) -> bool:
        """Extend ownership we still hold, by compare-owner semantics.

        This is what keeps a legitimately long call alive. It extends
        only our own ownership: between a separate GET and PEXPIRE the
        key could expire and be reclaimed, and we would then be renewing
        somebody else's claim.

        Args:
            scope: The trusted scope.
            task_id: The owning task.
            call_id: The physical attempt.
            owner: The identity that claimed it.
            ttl_seconds: TTL override.

        Returns:
            ``True`` when ownership was still ours and was extended.
            ``False`` means we have been fenced out — our terminal
            result is no longer authoritative.
        """
        client = self._redis
        if client is None:
            return False
        result = await client.eval(
            _RENEW_SCRIPT,
            1,
            self.call_lease_key(scope, task_id, call_id),
            owner,
            self._call_ttl_ms(ttl_seconds),
        )
        return bool(result)

    async def release_call(self, scope: TaskScope, task_id: str, call_id: str, owner: str) -> bool:
        """Release ownership we still hold, and only ours.

        Args:
            scope: The trusted scope.
            task_id: The owning task.
            call_id: The physical attempt.
            owner: The identity that claimed it.

        Returns:
            ``True`` when our ownership was released.
        """
        client = self._redis
        if client is None:
            return False
        result = await client.eval(_RELEASE_SCRIPT, 1, self.call_lease_key(scope, task_id, call_id), owner)
        return bool(result)

    async def call_owner(self, scope: TaskScope, task_id: str, call_id: str) -> Optional[str]:
        """Return the current owner of a call, if any.

        Args:
            scope: The trusted scope.
            task_id: The owning task.
            call_id: The physical attempt.

        Returns:
            The owner identity, or ``None`` when unowned or unreadable.
        """
        client = self._redis
        if client is None:
            return None
        try:
            value = await client.get(self.call_lease_key(scope, task_id, call_id))
        except Exception:  # noqa: BLE001 — unreadable is not unowned
            return None
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def is_call_alive(self, scope: TaskScope, task_id: str, call_id: str) -> Optional[bool]:
        """Report whether a call's owner still holds it — **tri-state**.

        The three answers are genuinely different and recovery depends on
        the distinction:

        ``True``
            Ownership is held and heartbeated. The call is running. Leave
            it alone however long it has been going.
        ``False``
            Redis answered, and nobody holds this call. Its owner is
            provably gone: ownership outlives a healthy call by design,
            so an absent key means the heartbeat stopped.
        ``None``
            We could not ask. **Not** evidence of anything. Treating this
            as ``False`` is how an unreachable cache gets a healthy call
            declared dead and its external effect retried.

        Args:
            scope: The trusted scope.
            task_id: The owning task.
            call_id: The physical attempt.

        Returns:
            The tri-state liveness.
        """
        client = self._redis
        if client is None:
            return None
        try:
            existing = await client.exists(self.call_lease_key(scope, task_id, call_id))
        except Exception:  # noqa: BLE001 — an unreachable cache knows nothing
            return None
        return bool(existing)

    # ── association ──────────────────────────────────────────────────

    async def read(self, scope: TaskScope) -> TaskAssociation:
        """Read the current association.

        Args:
            scope: The trusted scope.

        Returns:
            The association, or an empty one when the conversation has
            none or cannot be read.
        """
        metadata = await self._read_metadata(scope)
        return TaskAssociation.from_metadata(metadata)

    async def _read_metadata(self, scope: TaskScope) -> Optional[Dict[str, Any]]:
        """Read a conversation's whole metadata blob.

        Args:
            scope: The trusted scope.

        Returns:
            The metadata, or ``None``.
        """
        reader = getattr(self._memory, "read_metadata", None)
        if reader is not None:
            return await reader(scope.user_id, scope.session_id, scope.chatbot_id)
        history = await self._memory.get_history(scope.user_id, scope.session_id, scope.chatbot_id)
        return dict(history.metadata) if history is not None else None

    async def associate(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        select: bool = True,
    ) -> AssociationResult:
        """Register a task in the conversation, optionally selecting it.

        Call this **after** the task has been committed to its store. A
        failure here is reported, not raised: the task exists, and the
        caller must be able to recover it rather than create a second one.

        Args:
            scope: The trusted scope.
            task_id: The committed task's id.
            select: Whether to select it.

        Returns:
            The result, with ``degraded=True`` when the association could
            not be written.
        """
        return await self._mutate(scope, task_id, lambda a: a.with_task(task_id, select=select))

    async def select(self, scope: TaskScope, task_id: str) -> AssociationResult:
        """Select a task explicitly, repairing a lost association.

        An explicit, same-scope task id remains usable when the
        conversation metadata is gone. This is the repair path the
        specification requires: recall will not silently select such a
        task, but a caller may say so outright.

        Args:
            scope: The trusted scope.
            task_id: The task to select.

        Returns:
            The result.
        """
        return await self._mutate(scope, task_id, lambda a: a.selecting(task_id))

    async def close_task(self, scope: TaskScope, task_id: str) -> AssociationResult:
        """Remove a task from the open set.

        Args:
            scope: The trusted scope.
            task_id: The task to close.

        Returns:
            The result.
        """
        return await self._mutate(scope, task_id, lambda a: a.without_task(task_id))

    async def _mutate(self, scope: TaskScope, task_id: str, change) -> AssociationResult:
        """Apply a change to the association under compare-and-merge.

        Args:
            scope: The trusted scope.
            task_id: The task the change concerns, for reporting.
            change: A pure function from the current association to the
                next one.

        Returns:
            The result. Any failure is reported as ``degraded`` rather
            than raised — see the class docstring.
        """
        merge = getattr(self._memory, "merge_metadata", None)
        if merge is None:
            return AssociationResult(
                association=TaskAssociation(),
                degraded=True,
                reason="conversation memory does not support atomic metadata merge",
                task_id=task_id,
            )

        captured: Dict[str, TaskAssociation] = {}

        def _apply(metadata: Dict[str, Any]) -> Dict[str, Any]:
            """Merge the change into a freshly-read metadata blob.

            Runs INSIDE the compare-and-merge loop, against the metadata
            just read under WATCH — so a concurrent writer's changes are
            already visible here rather than being overwritten.

            Args:
                metadata: The current metadata.

            Returns:
                The metadata to write.
            """
            current = TaskAssociation.from_metadata(metadata)
            updated = change(current)
            captured["value"] = updated
            merged = dict(metadata)
            merged[ASSOCIATION_KEY] = updated.to_metadata_value()
            return merged

        try:
            await merge(
                scope.user_id,
                scope.session_id,
                scope.chatbot_id,
                mutate=_apply,
                ttl=self._config.context_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001 — a cache failure must not lose a committed task
            self.logger.warning(
                "Task association write failed for task %s (%s); the task IS committed — "
                "select it explicitly rather than creating another",
                task_id,
                exc,
            )
            fallback = captured.get("value") or await self._safe_read(scope)
            return AssociationResult(association=fallback, degraded=True, reason=str(exc), task_id=task_id)

        return AssociationResult(association=captured.get("value", TaskAssociation()), degraded=False, task_id=task_id)

    async def _safe_read(self, scope: TaskScope) -> TaskAssociation:
        """Read the association, returning an empty one on any failure.

        Args:
            scope: The trusted scope.

        Returns:
            The association.
        """
        try:
            return await self.read(scope)
        except Exception:  # noqa: BLE001 — already on a degraded path
            return TaskAssociation()

    async def resolve(self, scope: TaskScope, explicit_task_id: Optional[str] = None) -> TaskSelection:
        """Decide which task a command without an explicit id refers to.

        The rules, in order:

        1. An explicit id wins — but only within this scope. Scope is
           enforced by the caller's store on the very next read; this
           method never widens it.
        2. Otherwise the **authoritative selection** is used.
        3. Otherwise, with exactly one open task, that one.
        4. Otherwise ``needs_selection`` with the candidates. Never a
           similarity guess.

        Args:
            scope: The trusted scope.
            explicit_task_id: An id the caller supplied outright.

        Returns:
            The selection.
        """
        association = await self._safe_read(scope)

        if explicit_task_id:
            return TaskSelection(task_id=explicit_task_id, association_revision=association.revision)
        if association.selected_task_id:
            return TaskSelection(task_id=association.selected_task_id, association_revision=association.revision)
        if len(association.open_task_ids) == 1:
            return TaskSelection(task_id=association.open_task_ids[0], association_revision=association.revision)
        return TaskSelection(
            needs_selection=bool(association.open_task_ids),
            candidates=association.open_task_ids,
            association_revision=association.revision,
        )
