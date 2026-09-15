"""Task-memory store backends (FEAT-538).

The contract lives in :mod:`parrot.interfaces.task_memory`; this package
holds the implementations plus the machinery they share.

Backends:

- ``memory`` — process-local. Used by tests and by single-process
  compatibility deployments. **Not durable** (D2): it is Delivery A's
  only backend, and nothing about it survives a restart.
- ``postgres`` — durable truth for Delivery B, via ``asyncpg``. Imported
  lazily so that installing without the PostgreSQL extra, or running the
  in-memory backend, never pays for the driver.

Both must pass the same conformance suite (AC2). The shared rules —
scope enforcement, opaque scoped cursors, redelivery classification,
page bounding — live in :mod:`._base` precisely so the two backends
cannot drift apart on the points where a difference would be a security
bug rather than a behaviour difference.
"""

from ._base import (
    MAX_PAGE_LIMIT,
    BaseTaskMemoryStore,
    EventClassification,
    bounded_limit,
    classify_events,
    decode_cursor,
    encode_cursor,
    ensure_scope,
    goal_preview,
)

__all__ = (
    "MAX_PAGE_LIMIT",
    "BaseTaskMemoryStore",
    "EventClassification",
    "bounded_limit",
    "classify_events",
    "decode_cursor",
    "encode_cursor",
    "ensure_scope",
    "goal_preview",
)
