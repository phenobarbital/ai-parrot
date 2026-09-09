"""Shared machinery every task-memory store backend reuses (FEAT-538).

The in-memory and PostgreSQL stores must be *behaviourally identical*
(AC2), which is hard to achieve if each re-derives the rules. This module
owns the parts that have exactly one correct answer, so a backend
implements only genuine storage:

- **Scope enforcement** — :func:`ensure_scope`, and the deliberate
  choice to report a foreign task as absent rather than forbidden.
- **Opaque scoped cursors** — :func:`encode_cursor` /
  :func:`decode_cursor`. A cursor is signed to its scope and its query,
  so it cannot be replayed in another scope or against a different
  filter.
- **Idempotent redelivery classification** — :func:`classify_events`,
  which separates exact redeliveries (no-op, consume no sequence) from
  conflicting reuse of an ``event_id`` (rejected) and genuinely new
  events.
- **Bounded page sizes** — :func:`bounded_limit`.

None of this touches a database. The module stays leaf-safe so the
contract, the in-memory backend and the durable backend can all share
it.
"""

from __future__ import annotations

import base64
import hashlib
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import orjson

from ..models import CursorError, JournalEvent, Limits, ReducerError, ScopeViolation, TaskScope

__all__ = (
    "MAX_PAGE_LIMIT",
    "EventClassification",
    "bounded_limit",
    "ensure_scope",
    "encode_cursor",
    "decode_cursor",
    "classify_events",
    "goal_preview",
    "BaseTaskMemoryStore",
)

#: Hard ceiling on any page size, whatever a caller asks for.
MAX_PAGE_LIMIT: int = 200

#: Length of the cursor integrity tag. Not a security boundary — the
#: scope check is — but enough that a hand-edited cursor is rejected
#: rather than silently interpreted as some other query's position.
_TAG_BYTES: int = 8


def bounded_limit(limit: Optional[int], *, default: int, maximum: int = MAX_PAGE_LIMIT) -> int:
    """Clamp a requested page size into range.

    Args:
        limit: The caller's requested size, or ``None`` for the default.
        default: Size to use when ``limit`` is ``None``.
        maximum: Hard ceiling.

    Returns:
        The effective page size.

    Raises:
        CursorError: If ``limit`` is not positive. A zero or negative
            page is a caller bug, not an empty page.
    """
    if limit is None:
        return min(default, maximum)
    if limit < 1:
        raise CursorError(f"page limit must be >= 1, got {limit}")
    return min(limit, maximum)


def ensure_scope(expected: TaskScope, actual: TaskScope, *, subject: str) -> None:
    """Raise unless ``actual`` is exactly ``expected``.

    Args:
        expected: The trusted runtime scope of the caller.
        actual: The scope stored on the row being touched.
        subject: What is being accessed, for the message.

    Raises:
        ScopeViolation: If the scopes differ. The message deliberately
            names no identifiers from the foreign scope.
    """
    if not expected.matches(actual):
        raise ScopeViolation(f"{subject} belongs to a different scope")


def goal_preview(goal: str, *, chars: int) -> str:
    """Return a bounded preview of a task's goal for a listing.

    Args:
        goal: The full goal text.
        chars: Maximum characters to keep.

    Returns:
        The truncated goal. Truncation happens on characters, never on
        serialized JSON — this is display text, not a payload.
    """
    return goal[:chars]


def _tag(scope: TaskScope, query: Mapping[str, Any], position: Mapping[str, Any]) -> str:
    """Compute a cursor's integrity tag.

    Args:
        scope: The scope the cursor was issued in.
        query: The query parameters it belongs to.
        position: The position it encodes.

    Returns:
        A short hex digest binding all three together.
    """
    material = orjson.dumps(
        {"scope": scope.cache_key(), "query": dict(query), "position": dict(position)},
        option=orjson.OPT_SORT_KEYS,
        default=str,
    )
    return hashlib.blake2b(material, digest_size=_TAG_BYTES).hexdigest()


def encode_cursor(scope: TaskScope, query: Mapping[str, Any], position: Mapping[str, Any]) -> str:
    """Encode an opaque cursor bound to its scope and query.

    Args:
        scope: The scope issuing the cursor.
        query: The query parameters it is valid for.
        position: The backend's position marker.

    Returns:
        A URL-safe base64 string.

    Raises:
        CursorError: If the encoded cursor would exceed
            :data:`Limits.MAX_CURSOR`.
    """
    body = orjson.dumps(
        {"p": dict(position), "t": _tag(scope, query, position)},
        option=orjson.OPT_SORT_KEYS,
        default=str,
    )
    cursor = base64.urlsafe_b64encode(body).decode("ascii")
    if len(cursor) > Limits.MAX_CURSOR:
        raise CursorError(f"cursor too large: {len(cursor)} > {Limits.MAX_CURSOR}")
    return cursor


def decode_cursor(cursor: str, scope: TaskScope, query: Mapping[str, Any]) -> Dict[str, Any]:
    """Decode and validate an opaque cursor.

    Args:
        cursor: The cursor from a previous page.
        scope: The scope presenting it.
        query: The query parameters it must belong to.

    Returns:
        The decoded position marker.

    Raises:
        CursorError: If the cursor is malformed, over-length, or was
            issued for a different scope or a different query. All three
            are the same answer to the caller: this cursor is not usable
            here.
    """
    if len(cursor) > Limits.MAX_CURSOR:
        raise CursorError("cursor too large")
    try:
        decoded = orjson.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
    except Exception as exc:  # noqa: BLE001 — any decode failure is one answer
        raise CursorError("malformed cursor") from exc
    if not isinstance(decoded, dict) or "p" not in decoded or "t" not in decoded:
        raise CursorError("malformed cursor")
    position = decoded["p"]
    if not isinstance(position, dict):
        raise CursorError("malformed cursor")
    if decoded["t"] != _tag(scope, query, position):
        raise CursorError("cursor is not valid for this scope or query")
    return position


class EventClassification:
    """How one batch of events splits against a task's existing journal.

    Attributes:
        fresh: Events that must consume new sequence numbers, in order.
        duplicates: Ids recognised as exact redeliveries. They consume no
            sequence number, which is what keeps sequences contiguous.
    """

    __slots__ = ("fresh", "duplicates")

    def __init__(self, fresh: Sequence[JournalEvent], duplicates: Sequence[str]) -> None:
        """Initialize a classification.

        Args:
            fresh: The genuinely new events.
            duplicates: Ids of exact redeliveries.
        """
        self.fresh: Tuple[JournalEvent, ...] = tuple(fresh)
        self.duplicates: Tuple[str, ...] = tuple(duplicates)

    @property
    def is_noop(self) -> bool:
        """Whether the whole batch was already applied."""
        return not self.fresh

    def __repr__(self) -> str:
        """Return a debug representation."""
        return f"EventClassification(fresh={len(self.fresh)}, duplicates={len(self.duplicates)})"


def _event_identity(event: JournalEvent) -> bytes:
    """Return the canonical bytes that decide whether two events are the same.

    Deliberately excludes ``seq`` (backend-assigned) so a redelivered
    event that has not yet been sequenced still compares equal to its
    committed twin.

    Args:
        event: The event to canonicalize.

    Returns:
        Canonical serialized bytes.
    """
    data = event.model_dump(mode="json")
    data.pop("seq", None)
    return orjson.dumps(data, option=orjson.OPT_SORT_KEYS)


def classify_events(
    events: Sequence[JournalEvent],
    existing: Mapping[str, JournalEvent],
) -> EventClassification:
    """Split a batch into genuinely new events and exact redeliveries.

    This runs **before** any sequence number is allocated, which is what
    makes redelivery a true no-op rather than a gap-producing skip. It
    also runs before the expected-revision check, because a caller
    retrying a batch that in fact committed has a legitimately stale
    revision — rejecting it as a conflict would be wrong.

    Args:
        events: The batch, in order.
        existing: Already-committed events for this task, by ``event_id``.

    Returns:
        The classification.

    Raises:
        ReducerError: If an ``event_id`` is reused with a *different*
            payload — that is a bug or an attack, not a retry — or if the
            batch itself repeats an id.
    """
    fresh: List[JournalEvent] = []
    duplicates: List[str] = []
    seen_in_batch: Dict[str, bytes] = {}

    for event in events:
        identity = _event_identity(event)

        previous = seen_in_batch.get(event.event_id)
        if previous is not None:
            if previous != identity:
                raise ReducerError(f"event_id {event.event_id} reused with a different payload within one batch")
            duplicates.append(event.event_id)
            continue
        seen_in_batch[event.event_id] = identity

        committed = existing.get(event.event_id)
        if committed is not None:
            if _event_identity(committed) != identity:
                raise ReducerError(
                    f"event_id {event.event_id} was already appended with a different payload; "
                    "an id may be redelivered, never rewritten"
                )
            duplicates.append(event.event_id)
            continue

        fresh.append(event)

    return EventClassification(fresh, duplicates)


class BaseTaskMemoryStore(ABC):
    """Base class carrying the rules both backends share.

    A backend subclasses this and implements only genuine storage. The
    shared helpers above are exposed as methods so a subclass never has
    to reimplement scope checks or cursor handling — the two places where
    an inconsistency between backends would be a security bug rather
    than a behaviour difference.
    """

    #: Default page size for task listings.
    default_task_page: int = 20
    #: Default page size for event listings.
    default_event_page: int = 50

    def _bounded(self, limit: Optional[int], *, default: int) -> int:
        """Clamp a page size (see :func:`bounded_limit`).

        Args:
            limit: Requested size.
            default: Default when ``None``.

        Returns:
            The effective size.
        """
        return bounded_limit(limit, default=default)

    def _ensure_scope(self, expected: TaskScope, actual: TaskScope, *, subject: str) -> None:
        """Enforce scope equality (see :func:`ensure_scope`).

        Args:
            expected: The caller's trusted scope.
            actual: The stored scope.
            subject: What is being accessed.
        """
        ensure_scope(expected, actual, subject=subject)

    def _encode_cursor(self, scope: TaskScope, query: Mapping[str, Any], position: Mapping[str, Any]) -> str:
        """Encode a scoped cursor (see :func:`encode_cursor`).

        Args:
            scope: Issuing scope.
            query: Query parameters.
            position: Position marker.

        Returns:
            The opaque cursor.
        """
        return encode_cursor(scope, query, position)

    def _decode_cursor(self, cursor: str, scope: TaskScope, query: Mapping[str, Any]) -> Dict[str, Any]:
        """Decode and validate a scoped cursor (see :func:`decode_cursor`).

        Args:
            cursor: The cursor.
            scope: Presenting scope.
            query: Query parameters.

        Returns:
            The position marker.
        """
        return decode_cursor(cursor, scope, query)

    def _classify(
        self,
        events: Sequence[JournalEvent],
        existing: Mapping[str, JournalEvent],
    ) -> EventClassification:
        """Classify a batch against committed events (see :func:`classify_events`).

        Args:
            events: The batch.
            existing: Committed events by id.

        Returns:
            The classification.
        """
        return classify_events(events, existing)

    @abstractmethod
    async def close(self) -> None:
        """Release any resources the store holds."""

    def _sequence_range(self, last_seq: int, count: int) -> Iterable[int]:
        """Yield the contiguous sequence numbers a batch will occupy.

        Args:
            last_seq: The task's current highest sequence.
            count: How many fresh events will be appended.

        Returns:
            The sequence numbers, ascending, starting at ``last_seq + 1``.
        """
        return range(last_seq + 1, last_seq + 1 + count)
