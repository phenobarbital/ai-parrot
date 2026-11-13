# TASK-5581: Turn bus setup — Streams bus, outbox, dead letters, ChatStorage subscriptions

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 10)
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5569, TASK-5579, TASK-5571
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 and §2 "Piece 1". TASK-5569 gives the bot a `BusTurnPublisher`; TASK-5579 gives `ChatStorage`
the handlers `handle_turn_completed` / `handle_conversation_deleted`. This task is the application-level glue:
build the dedicated **turn bus** (`EventBus` over Redis Streams with a durable `SqliteOutbox` and a DLQ),
subscribe the ChatStorage handlers, give `ChatStorage` a way to publish the deletion event, and tear it all down
on shutdown. It mirrors `observability/fanout.py` but is a **separate** bus instance and is **not** `publish_only`
(it consumes). TASK-5584 (`BotManager`) is the only caller.

Two facts about the installed library differ from what the spec assumed and shape this task (both verified
against `navigator-eventbus 0.4.1`, see "Library drift" below): a Streams `EventBus` ignores `channel_prefix`
(so isolation needs an explicit backend), and the library has **no dead-letter store in the outbox** (so the
"retain in the SQLite outbox" decision of spec §8 Q15 needs a small local store).

---

## Scope

- Add the four `PARROT_TURN_BUS_*` settings to `parrot/conf.py`.
- Create `parrot/storage/turn_bus.py`: `TurnPersistence`, `setup_turn_persistence`, `shutdown_turn_persistence`,
  `replay_dead_letters`, plus the private pieces they need (`_resolve_outbox_path`, `_build_bus`,
  `SqliteDeadLetterStore`, the `on_dlq` callback factory).
- Subscribe `ChatStorage.handle_turn_completed` to `TURN_COMPLETED_TOPIC` and
  `ChatStorage.handle_conversation_deleted` to `CONVERSATION_DELETED_TOPIC`; hand `ChatStorage` a deletion
  publisher (`attach_deletion_publisher`, added by TASK-5579).
- Unit tests (memory transport for wiring; no Redis required).

**NOT in scope**: `ChatStorage` handlers / `store_turn` / the deletion protocol (TASK-5579); `BusTurnPublisher`
and the topic constants (TASK-5569); `BotManager` startup/shutdown (TASK-5584); the Redis end-to-end,
crash-recovery and DLQ-with-Postgres tests (TASK-5585); the `REDIS_HISTORY_EXPLICIT` setting (TASK-5571).

### Library drift this task absorbs (verified, `navigator-eventbus 0.4.1`)
1. **`channel_prefix` is ignored for `transport="streams"`** (`evb.py` `_select_backend`: "`channel_prefix` applies to
   pub/sub alone"; it builds `RedisStreamsBackend(redis_url)` with the default `stream_prefix="evb:stream:"` and group
   `evb-bus`). `observability/fanout.py:97` passes `channel_prefix=` to a streams bus and gets the default — harmless
   for a publish-only fan-out, but a **consuming** bus on the default prefix would read the fan-out bus's streams and
   share its consumer group. Therefore build the backend explicitly:
   `RedisStreamsBackend(redis_url, stream_prefix=<PARROT_TURN_BUS_CHANNEL_PREFIX>, dedup_prefix=<prefix>+"dedup:", group="parrot-turns")`
   and pass it as `EventBus(backend=...)`. `PARROT_TURN_BUS_CHANNEL_PREFIX` therefore becomes the **stream prefix**.
2. **`SqliteOutbox` is a producer write-ahead log only** (`outbox.py`: `evb_outbox`, rows deleted on `ack`); it keeps
   no dead letters. `DLQHandler(bus, dsn=None)` without a DSN only republishes on the in-memory `bus.dlq` topic and
   persists nothing. So "retain exhausted envelopes as dead letters, never drop" (spec §8 Q15) is implemented here by
   `SqliteDeadLetterStore` (stdlib `sqlite3`, `asyncio.to_thread`), as the `on_dlq` callback when no DSN is set.
3. `EventBus.subscribe` hands handlers a legacy `Event`; **`bus.core.subscribe` hands them the `EventEnvelope`** that
   `ChatStorage.handle_turn_completed(envelope)` expects. Subscribe on `bus.core`.
4. The repo's own `.venv` currently resolves `navigator-eventbus 0.3.0` (no `outbox`, no `transport`); `pyproject.toml:201`
   pins `>=0.4.0`. Tests here skip with a clear reason on a stale environment; run `uv sync` in the feature worktree.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/turn_bus.py` | CREATE | bus setup/teardown, dead-letter store, replay |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `PARROT_TURN_BUS_*` settings |
| `packages/ai-parrot/tests/unit/storage/test_turn_bus_setup.py` | CREATE | outbox validation, wiring, dead-letter store, replay |

---

## Codebase Contract (Anti-Hallucination)

Re-verified against the tree at `6d564b36a2` (branch `dev`) and the installed `navigator_eventbus` 0.4.1
(`~/.parrot/venv/lib/python3.12/site-packages/navigator_eventbus/`). Paths relative to `packages/ai-parrot/`.

### Verified Imports
```python
from navigator_eventbus import EventBus, EventEnvelope, DLQHandler          # verified: navigator_eventbus/__init__.py:19-29
from navigator_eventbus.backends.redis_streams import RedisStreamsBackend    # verified: backends/redis_streams.py (class; ctor :205)
from navconfig.logging import logging                                        # verified: src/parrot/storage/backends/sqlite.py:27
from parrot import conf                                                      # verified: src/parrot/llm_defaults.py:16
from parrot.storage.chat import ChatStorage                                  # verified: src/parrot/storage/chat.py:25
```

### Provided by dependency tasks (NOT in the tree yet — re-grep after each lands)
```python
from parrot.memory.persistence import (                       # TASK-5569 (new module)
    BusTurnPublisher, TURN_COMPLETED_TOPIC, CONVERSATION_DELETED_TOPIC)
# BusTurnPublisher(bus)  — duck-typed on bus.emit(...); publish(event) raises when the outbox rejects the write
# ChatStorage.handle_turn_completed(self, envelope)            # TASK-5579
# ChatStorage.handle_conversation_deleted(self, envelope)      # TASK-5579
# ChatStorage.attach_deletion_publisher(self, publisher)       # TASK-5579 (public read-only props cold_backend / hot_redis_client also exist; this task needs neither) — see "Cross-task contract" below
# parrot.conf.REDIS_HISTORY_EXPLICIT                           # TASK-5571 (conf.py is edited by 5568 -> 5571 -> THIS task, in that order)
```

### Existing Signatures to Use
```python
# navigator_eventbus 0.4.1
class EventBus:                                                              # evb.py:138
    def __init__(self, redis_url=None, use_redis=False, *, channel_prefix=None, backend=None,
                 transport=None, publish_only=False, outbox=None, **bus_options)       # :164  bus_options -> BusCore (workers, retry_attempts,
                                                                                       #   retry_base_delay, on_dlq, default_backpressure, ...)
    @property
    def core(self) -> BusCore                                                          # :205
    async def connect(self) -> None                                                    # :220 starts dispatcher + backend consumer (not publish_only)
    async def close(self) -> None                                                      # :226 drains, closes outbox (rows stay persisted)
class BusCore:                                                               # core.py
    def subscribe(self, pattern, handler: Callable[[EventEnvelope], Any], *, priority=0, filter_fn=None, min_severity=None) -> str   # :597
    def unsubscribe(self, subscriber_id: str) -> bool                                                                                  # :653
    async def publish(self, envelope: EventEnvelope) -> None                                                                           # :325
    # retry: retry_attempts=3, retry_base_delay=0.1 (exp backoff) then on_dlq(envelope, *, attempts, error, subscriber_id); `bus.*` topics never DLQ'd
class DLQHandler:                                                            # dlq.py:120
    def __init__(self, bus, *, dsn=None, driver="pg")
    async def ensure_table(self) -> None
    async def on_dlq(self, envelope, *, attempts, error, subscriber_id) -> None
    async def replay(self, event_id=None, since=None) -> int     # exactly one selector; raises ValueError without a DSN
class EventEnvelope:   to_dict() -> JSON-safe dict ; from_dict(data) -> EventEnvelope ; fields topic, payload, event_id, timestamp(tz-aware), ...   # envelope.py:106,164,188
class SqliteOutbox:    # one live store per file (flock on <path>.lock) -> one outbox file per <hostname>-<pid>
# packages/ai-parrot/src/parrot/observability/fanout.py
def _outbox_path() -> Path        # :62 — pattern: validate dir is a writable directory, return <dir>/<hostname>-<pid>.db
# packages/ai-parrot/src/parrot/conf.py
PARROT_STORAGE_METRICS = config.get("PARROT_STORAGE_METRICS", fallback=None)   # :603 (anchor; 1 occurrence)
```

### Cross-task contract (written identically in TASK-5579)
The spec gives `ChatStorage` no route to the bus for `CONVERSATION_DELETED_TOPIC` (`BusTurnPublisher` only publishes
turn events). TASK-5579 adds `ChatStorage.attach_deletion_publisher(publisher: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]]) -> None`;
`delete_conversation` / `delete_turn` call `await publisher(CONVERSATION_DELETED_TOPIC, payload)` after the tombstone
is committed (a failure is logged, never raised). This task supplies that callable:
`async def _publish_deletion(topic, payload): await bus.core.publish(EventEnvelope(topic=topic, payload=payload, source="chat-storage"))`.

### Does NOT Exist
- ~~`parrot.storage.turn_bus`~~ — created by THIS task.
- ~~`PARROT_TURN_BUS_*` in `parrot.conf`~~ — added by THIS task (grep confirms none today).
- ~~A dead-letter table or API on `SqliteOutbox` / `OutboxStore`~~ — only `append/ack/nack/due/stats/close`.
- ~~`EventBus(transport="streams", channel_prefix=...)` honouring the prefix~~ — ignored; build the backend explicitly.
- ~~`DLQHandler.replay()` with neither selector~~ — raises `ValueError`; pass `since=`.
- ~~A global/module-level singleton for the turn bus~~ — the handle is returned and stored by the caller (spec §5 / ARCH note: per-app state, no module global).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/storage/turn_bus.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/conf.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/storage/test_turn_bus_setup.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage",
    "sym:packages/ai-parrot/src/parrot/observability/fanout.py#_outbox_path"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`observability/fanout.py`: `_config_value` / `_outbox_path` (validate, fail with a precise `RuntimeError`), idempotent
setup, teardown that preserves the outbox. Differences (deliberate): not `publish_only`; no module-level `_BUS` global
(the handle is returned); settings read from `parrot.conf` at CALL time via `getattr(conf, NAME, None)` so tests can
`monkeypatch.setattr(conf, ...)` (spec §7 "Settings: read through `parrot.conf`, never `os.environ`").

### Key Constraints
- **Fail fast, precise messages**: unset/missing/not-a-directory/not-writable outbox dir -> `RuntimeError` naming the
  setting (spec §3 M10); unset `PARROT_TURN_BUS_REDIS_URL` -> `RuntimeError` (no inference from `REDIS_HISTORY_URL`).
- The outbox file is `<dir>/<hostname>-<pid>.db` (one live `SqliteOutbox` per file). The dead-letter store is a
  **different** file, `<dir>/<hostname>-dead-letters.db`, shared by every pid on the host, so a restarted process can
  replay what a previous one exhausted. (`SqliteOutbox` is not used for it — it would raise `OutboxLockedError`.)
- `default_backpressure="block"` (spec §2): `block` applies to the relay; the request path writes the outbox first.
- `DLQHandler` needs the bus, but `on_dlq` must be passed INTO the bus constructor: use a late-bound closure
  (`holder["dlq"]`) — the standard chicken-and-egg resolution.
- With `PARROT_TURN_BUS_DLQ_DSN` set: `DLQHandler(bus, dsn=dsn)` + `await handler.ensure_table()`. Without: log at INFO
  that exhausted envelopes are retained in `SqliteDeadLetterStore` (never dropped), and use it. `TurnPersistence.dlq`
  holds whichever is active; `replay_dead_letters` handles both.
- Deletion wins on replay: `replay_dead_letters` only republishes; `ChatStorage.store_turn` (TASK-5579) re-checks the
  tombstone, so a tombstoned identity is acknowledged-and-dropped, never resurrected.
- `shutdown_turn_persistence` unsubscribes, closes the bus (outbox rows stay on disk) and is safe to call twice.
- Never log envelope payloads (conversation content); log `event_id` / topic / counts only.
- Modules <= 500 lines, functions <= 60 lines, cyclomatic <= 10; `SqliteDeadLetterStore` stays under ~90 lines.

### References in Codebase
- `packages/ai-parrot/src/parrot/observability/fanout.py:62-120` — outbox path validation and bus construction.
- `~/.parrot/venv/.../navigator_eventbus/dlq.py:120-340` — `DLQHandler` semantics to mirror in the SQLite store.

---

## Implementation Blueprint

### Steps (in order)
1. Re-grep the "Provided by dependency tasks" names (`BusTurnPublisher`, topics, the three `ChatStorage` methods) —
   *why*: this task is glue; a renamed symbol is drift to fix in the task file first.
2. Add the four settings to `conf.py` — *why*: `turn_bus.py` reads them.
3. Create `turn_bus.py` in this order: `SqliteDeadLetterStore` -> `_resolve_outbox_path` / `_build_bus` ->
   `setup_turn_persistence` -> `shutdown_turn_persistence` -> `replay_dead_letters` — *why*: each layer is testable
   without the next.
4. Write tests, run the mutation checks — *why*: wiring bugs (a missing subscription, a dropped dead letter) are
   silent in production.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'PARROT_STORAGE_METRICS = config.get("PARROT_STORAGE_METRICS", fallback=None)' packages/ai-parrot/src/parrot/conf.py)
# AFTER — insert below `PARROT_STORAGE_METRICS = config.get("PARROT_STORAGE_METRICS", fallback=None)` (verified: conf.py:603)

# --- Durable conversation memory: turn bus (FEAT-886 M10) ---
# Redis Streams bus that carries conversation.turn.completed to ChatStorage. Separate from the
# observability fan-out bus. The outbox directory is REQUIRED (writable; one SQLite file per pod/pid).
# PARROT_TURN_BUS_CHANNEL_PREFIX is the Redis STREAM prefix (a Streams EventBus ignores channel_prefix).
# PARROT_TURN_BUS_DLQ_DSN is optional: without it, exhausted envelopes are retained as dead letters in a
# local SQLite store next to the outbox (never dropped).
PARROT_TURN_BUS_REDIS_URL = config.get("PARROT_TURN_BUS_REDIS_URL", fallback=None)
PARROT_TURN_BUS_OUTBOX_DIR = config.get("PARROT_TURN_BUS_OUTBOX_DIR", fallback=None)
PARROT_TURN_BUS_CHANNEL_PREFIX = config.get("PARROT_TURN_BUS_CHANNEL_PREFIX", fallback="parrot:turns:")
PARROT_TURN_BUS_DLQ_DSN = config.get("PARROT_TURN_BUS_DLQ_DSN", fallback=None)
```
**Why**: spec §3 M10 settings, defaults exactly as specified; anchored away from the `REDIS_*` lines TASK-5568/5571 edit.

### `packages/ai-parrot/src/parrot/storage/turn_bus.py` (CREATE) — settings, outbox path, dead-letter store
```python
"""Application-level turn bus: Redis Streams + durable outbox + dead letters (FEAT-886 M10).

Builds the dedicated bus that carries ``conversation.turn.completed`` to ``ChatStorage``,
subscribes the storage handlers and tears everything down. Mirrors ``observability/fanout.py``
but is a SEPARATE bus and is not publish-only: it consumes.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from navconfig.logging import logging
from navigator_eventbus import DLQHandler, EventBus, EventEnvelope
from navigator_eventbus.backends.redis_streams import RedisStreamsBackend

from parrot import conf
from parrot.memory.persistence import CONVERSATION_DELETED_TOPIC, TURN_COMPLETED_TOPIC, BusTurnPublisher
from parrot.storage.chat import ChatStorage

logger = logging.getLogger("parrot.storage.turn_bus")


@dataclass
class TurnPersistence:
    """Handle returned by :func:`setup_turn_persistence`.

    Attributes:
        bus: The turn ``EventBus``.
        publisher: The ``BusTurnPublisher`` bots publish through.
        subscription_ids: ``bus.core`` subscription ids (turn + deletion handlers).
        dlq: A ``DLQHandler`` (Postgres) or a ``SqliteDeadLetterStore``; ``None`` for an injected bus.
    """

    bus: Any
    publisher: BusTurnPublisher
    subscription_ids: List[str]
    dlq: Optional[Any] = None


def _setting(name: str) -> Optional[str]:
    """Read a ``parrot.conf`` setting at call time (tests monkeypatch the module attribute)."""
    value = getattr(conf, name, None)
    return str(value) if value not in (None, "") else None


def _resolve_outbox_dir() -> Path:
    """Return the validated writable outbox directory.

    Raises:
        RuntimeError: ``PARROT_TURN_BUS_OUTBOX_DIR`` is unset, not a directory or not writable.
    """
    configured = _setting("PARROT_TURN_BUS_OUTBOX_DIR")
    if not configured:
        raise RuntimeError("PARROT_TURN_BUS_OUTBOX_DIR is required when turn persistence is enabled")
    directory = Path(configured).expanduser()
    if not directory.is_dir() or not os.access(directory, os.W_OK):
        raise RuntimeError(f"PARROT_TURN_BUS_OUTBOX_DIR is not a writable directory: {directory}")
    return directory


class SqliteDeadLetterStore:
    """Local, durable dead-letter store for retry-exhausted envelopes (spec §8 Q15).

    ``SqliteOutbox`` keeps no dead letters, and ``DLQHandler`` without a DSN persists nothing, so
    envelopes whose handler exhausted its retries are kept here until replayed. One file per host.
    """

    _DDL = (
        "CREATE TABLE IF NOT EXISTS turn_dead_letters ("
        " event_id TEXT PRIMARY KEY, topic TEXT NOT NULL, envelope TEXT NOT NULL, attempts INTEGER NOT NULL,"
        " error TEXT NOT NULL, subscriber_id TEXT, failed_at REAL NOT NULL, replayed_at REAL)"
    )

    def __init__(self, path: Path) -> None:
        self._path = path
        # FILL IN: create the file and run self._DDL plus `PRAGMA journal_mode=WAL` once (sync, in __init__ is fine:
        #   it runs at startup) — bounded by "no dead letter is ever dropped".

    async def add(self, envelope: EventEnvelope, *, attempts: int, error: BaseException, subscriber_id: str) -> None:
        """Persist (or re-open) a dead letter; a replayed envelope that fails again becomes pending again."""
        # FILL IN: asyncio.to_thread of an INSERT ... ON CONFLICT(event_id) DO UPDATE SET attempts, error, failed_at,
        #   replayed_at=NULL, with envelope=json.dumps(envelope.to_dict(), default=str) and error=f"{type(error).__name__}: {error}".
        raise NotImplementedError

    async def pending(self, since: Optional[datetime] = None) -> List[EventEnvelope]:
        """Un-replayed envelopes (optionally ``failed_at >= since``), oldest first."""
        # FILL IN: asyncio.to_thread SELECT ... WHERE replayed_at IS NULL [AND failed_at >= ?] ORDER BY failed_at; rebuild with
        #   EventEnvelope.from_dict; skip + log (event_id only) a row that fails to rebuild — bounded by DLQHandler.replay semantics.
        raise NotImplementedError

    async def mark_replayed(self, event_id: str) -> None:
        """Mark a dead letter as replayed (kept for audit, not deleted)."""
        # FILL IN: UPDATE turn_dead_letters SET replayed_at=? WHERE event_id=? via asyncio.to_thread.
        raise NotImplementedError

    async def close(self) -> None:
        """No persistent connection is held; present for handle symmetry."""
```

### `packages/ai-parrot/src/parrot/storage/turn_bus.py` (CREATE — bus construction and public API, same file)
```python
def _make_dlq_callback(holder: Dict[str, Any]) -> Callable[..., Any]:
    """Late-bound ``on_dlq`` for ``BusCore``: the DLQ object only exists after the bus does."""
    async def _on_dlq(envelope: EventEnvelope, *, attempts: int, error: BaseException, subscriber_id: str) -> None:
        # FILL IN: dlq = holder.get("dlq"); if dlq is a DLQHandler -> await dlq.on_dlq(envelope, attempts=..., error=..., subscriber_id=...);
        #   elif it has `.add` -> await dlq.add(...); ALWAYS log ERROR with event_id/topic/attempts (never the payload); if no DLQ yet
        #   (bus still starting) log ERROR with event_id — bounded by "dead letters are never silently dropped".
        raise NotImplementedError
    return _on_dlq


def _build_bus(holder: Dict[str, Any]) -> EventBus:
    """Build the consuming Streams bus with its durable outbox (explicit backend: see Library drift 1)."""
    redis_url = _setting("PARROT_TURN_BUS_REDIS_URL")
    if not redis_url:
        raise RuntimeError("PARROT_TURN_BUS_REDIS_URL is required when turn persistence is enabled")
    outbox = _resolve_outbox_dir() / f"{socket.gethostname()}-{os.getpid()}.db"
    prefix = _setting("PARROT_TURN_BUS_CHANNEL_PREFIX") or "parrot:turns:"
    backend = RedisStreamsBackend(redis_url, stream_prefix=prefix, dedup_prefix=f"{prefix}dedup:", group="parrot-turns")
    return EventBus(
        backend=backend,
        outbox=str(outbox),
        default_backpressure="block",
        on_dlq=_make_dlq_callback(holder),
    )


async def setup_turn_persistence(chat_storage: ChatStorage, *, bus: Any = None) -> TurnPersistence:
    """Build (or accept) the turn bus and subscribe ``ChatStorage``.

    Args:
        chat_storage: The initialised ``ChatStorage``.
        bus: An existing ``EventBus`` (tests / hosts that own their bus); its DLQ is then the caller's.

    Returns:
        A :class:`TurnPersistence` handle.

    Raises:
        RuntimeError: Redis URL or outbox directory is unset / unusable (bus not built).
    """
    holder: Dict[str, Any] = {}
    owns_bus = bus is None
    bus = bus if bus is not None else _build_bus(holder)
    dlq = await _attach_dlq(bus, holder) if owns_bus else None
    ids = [
        bus.core.subscribe(TURN_COMPLETED_TOPIC, chat_storage.handle_turn_completed),
        bus.core.subscribe(CONVERSATION_DELETED_TOPIC, chat_storage.handle_conversation_deleted),
    ]
    # FILL IN: chat_storage.attach_deletion_publisher(<closure publishing EventEnvelope(topic=..., payload=..., source="chat-storage")
    #   via bus.core.publish>) — bounded by "Cross-task contract"; then `await bus.connect()` to start dispatcher + consumer.
    return TurnPersistence(bus=bus, publisher=BusTurnPublisher(bus), subscription_ids=ids, dlq=dlq)


async def _attach_dlq(bus: Any, holder: Dict[str, Any]) -> Any:
    """Choose Postgres ``DLQHandler`` (DSN set) or the local ``SqliteDeadLetterStore`` and bind it to the callback."""
    # FILL IN: dsn = _setting("PARROT_TURN_BUS_DLQ_DSN"); with a DSN -> DLQHandler(bus, dsn=dsn) + await ensure_table();
    #   without -> SqliteDeadLetterStore(_resolve_outbox_dir() / f"{socket.gethostname()}-dead-letters.db") and log INFO that
    #   exhausted envelopes are retained locally. Set holder["dlq"] and return it — bounded by spec §8 Q15.
    raise NotImplementedError


async def shutdown_turn_persistence(handle: TurnPersistence) -> None:
    """Unsubscribe and close the bus, preserving the outbox. Safe to call twice."""
    # FILL IN: for each id -> handle.bus.core.unsubscribe(id) (ignore False); handle.subscription_ids.clear(); await handle.bus.close();
    #   close handle.dlq if it has `close`; swallow-and-log (DEBUG) teardown errors like fanout.shutdown_event_fanout — bounded by
    #   "preserving the outbox" (never delete outbox files).
    raise NotImplementedError


async def replay_dead_letters(handle: TurnPersistence, *, since: Optional[datetime] = None) -> int:
    """Replay dead letters through the same handlers; ``store_turn`` re-checks tombstones.

    Returns:
        Number of envelopes re-published.

    Raises:
        RuntimeError: The handle has no DLQ (an injected bus).
    """
    # FILL IN: DLQHandler -> `await dlq.replay(since=since or datetime.fromtimestamp(0, timezone.utc))`;
    #   SqliteDeadLetterStore -> for env in await dlq.pending(since): await handle.bus.core.publish(env); await dlq.mark_replayed(env.event_id);
    #   count publishes — bounded by "replay reads from whichever store holds them" (spec §8 Q15).
    raise NotImplementedError
```
**Why this shape**: the public names and signatures are fixed by spec §3 M10. The explicit `RedisStreamsBackend` is the only
way to honour `PARROT_TURN_BUS_CHANNEL_PREFIX` and to keep this consuming bus off the fan-out bus's streams/group. Subscribing on
`bus.core` delivers the `EventEnvelope` the ChatStorage handlers take. The `holder` closure lets `on_dlq` be passed to the bus
constructor before the DLQ object (which needs the bus) exists. Do NOT add a module-level bus singleton; do NOT call
`EventBus.subscribe` (wrong handler arity); do NOT use `SqliteOutbox` for dead letters.

### FILL IN checklist
- [ ] `turn_bus.py::SqliteDeadLetterStore.__init__/add/pending/mark_replayed` — bounded by "no dead letter is ever dropped" (spec §8 Q15).
- [ ] `turn_bus.py::_make_dlq_callback` — dispatch to `DLQHandler.on_dlq` or `store.add`, always log; bounded by Q15.
- [ ] `turn_bus.py::_attach_dlq` — DSN vs local store; bounded by Q15.
- [ ] `turn_bus.py::setup_turn_persistence` — deletion publisher closure + `await bus.connect()`; bounded by "Cross-task contract".
- [ ] `turn_bus.py::shutdown_turn_persistence` — idempotent teardown; bounded by "preserving the outbox".
- [ ] `turn_bus.py::replay_dead_letters` — both stores; bounded by Q15.
- [ ] tests: how to build a `TurnCompletedEvent` / payload — bounded by TASK-5569's `TurnCompletedEvent.to_dict()`; read it after it lands.

---

## Acceptance Criteria

- [ ] An unset, missing, non-directory or non-writable outbox directory raises `RuntimeError` naming `PARROT_TURN_BUS_OUTBOX_DIR`; an unset Redis URL raises `RuntimeError` naming `PARROT_TURN_BUS_REDIS_URL` (spec §4 `test_setup_requires_writable_outbox`).
- [ ] `setup_turn_persistence(chat_storage, bus=<memory EventBus>)` subscribes exactly two handlers; a `TurnCompletedEvent` published through `handle.publisher` ends up stored in the cold tier (spec §5 "Failure propagation and retries" wiring half; round trip is TASK-5585).
- [ ] The built bus is a Streams bus on an explicit `RedisStreamsBackend` whose `stream_prefix` equals `PARROT_TURN_BUS_CHANNEL_PREFIX`, with an outbox file under the configured directory, not publish-only (inspect `bus.core._backend` / `_outbox` the way `fanout._validate_bus` does).
- [ ] A handler failing 3 times routes the envelope to the dead-letter store (retry then DLQ wiring); it is NOT dropped (spec §5 "exhaustion lands in the DLQ").
- [ ] `replay_dead_letters` re-publishes pending dead letters exactly once (a second call returns 0) and never resurrects a tombstoned identity (spec §5 "Deletion races … replay its DLQ entry").
- [ ] `delete_conversation` publishes the deletion event through the attached publisher and the registered `handle_conversation_deleted` runs (spec §2 "Deletion").
- [ ] `shutdown_turn_persistence` is idempotent and leaves outbox / dead-letter files on disk.
- [ ] **Mutation checks** (revert, see RED, restore by re-applying — never `git checkout`): (1) drop the deletion-topic `subscribe` line -> `test_deletion_event_reaches_cleanup_handler` goes RED; (2) make `_make_dlq_callback` a no-op -> `test_retry_exhaustion_lands_in_dead_letters` goes RED; (3) remove the `os.access(..., os.W_OK)` check -> `test_setup_requires_writable_outbox` (read-only case) goes RED; (4) pass `channel_prefix=` to `EventBus` instead of building the backend -> `test_bus_uses_isolated_stream_prefix` goes RED.
- [ ] `ruff check` is clean on the three touched files; `from parrot.storage.turn_bus import setup_turn_persistence, shutdown_turn_persistence, replay_dead_letters, TurnPersistence` works.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/storage/test_turn_bus_setup.py -q`
- `pytest packages/ai-parrot/tests/unit/storage/test_turn_bus_setup.py::test_setup_requires_writable_outbox -q`

---

## Test Specification

Real objects: `EventBus(transport="memory", ...)` (the `memory_bus` fixture of spec §4), a real `ChatStorage` over a real
SQLite backend, real files under `tmp_path`. Failure injection uses a small **real subclass** of
`ConversationSQLiteBackend` that raises a real `StorageUnavailableError`. No `Mock` for the bus or storage.

```python
# packages/ai-parrot/tests/unit/storage/test_turn_bus_setup.py
import asyncio
import os
from datetime import datetime, timezone

import navigator_eventbus
import pytest
from navigator_eventbus import EventBus, EventEnvelope

from parrot import conf
from parrot.memory.persistence import CONVERSATION_DELETED_TOPIC, TURN_COMPLETED_TOPIC
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.chat import ChatStorage
from parrot.storage.errors import ConversationDeletedError, StorageUnavailableError
from parrot.storage.turn_bus import (
    SqliteDeadLetterStore, TurnPersistence, replay_dead_letters, setup_turn_persistence, shutdown_turn_persistence)

pytestmark = pytest.mark.skipif(
    not hasattr(navigator_eventbus, "SqliteOutbox"),
    reason="navigator-eventbus >= 0.4.0 required (stale environment: run `uv sync`)")

USER, AGENT = "u1", "agent-a"


@pytest.fixture
def memory_bus(tmp_path):
    return EventBus(transport="memory", outbox=str(tmp_path / "outbox.db"), retry_attempts=3, retry_base_delay=0.0)


@pytest.fixture
async def backend(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "cold.db"))
    await b.initialize()
    yield b
    await b.close()


@pytest.fixture
def chat_storage(backend):
    storage = ChatStorage(redis_conversation=None, dynamodb=backend)   # hot tier absent: store_turn skips it (TASK-5579)
    storage._initialized = True
    return storage


def _payload(turn_id="t1", session="s1"):
    # FILL IN: build the payload via TASK-5569's TurnCompletedEvent(...).to_dict() for a minimal turn
    #   (agent_name=AGENT, user_id=USER, session_id=session, turn=ConversationTurn(...).to_dict() with a UTC timestamp and sequence=1)
    #   — bounded by TASK-5569's event shape; this helper is the only place that knows it.
    raise NotImplementedError


async def _eventually(predicate, timeout=3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.02)
    return False


def test_setup_requires_writable_outbox(monkeypatch, tmp_path):
    from parrot.storage import turn_bus
    monkeypatch.setattr(conf, "PARROT_TURN_BUS_REDIS_URL", "redis://localhost:6399/0", raising=False)
    for bad in (None, str(tmp_path / "missing"), str(tmp_path / "a-file")):
        if bad and bad.endswith("a-file"):
            (tmp_path / "a-file").write_text("x")
        monkeypatch.setattr(conf, "PARROT_TURN_BUS_OUTBOX_DIR", bad, raising=False)
        with pytest.raises(RuntimeError, match="PARROT_TURN_BUS_OUTBOX_DIR"):
            turn_bus._build_bus({})
    # FILL IN: read-only directory (os.chmod 0o500; skip when os.geteuid() == 0) -> RuntimeError — bounded by AC 1.


def test_setup_requires_redis_url(monkeypatch, tmp_path):
    from parrot.storage import turn_bus
    monkeypatch.setattr(conf, "PARROT_TURN_BUS_REDIS_URL", None, raising=False)
    monkeypatch.setattr(conf, "PARROT_TURN_BUS_OUTBOX_DIR", str(tmp_path), raising=False)
    with pytest.raises(RuntimeError, match="PARROT_TURN_BUS_REDIS_URL"):
        turn_bus._build_bus({})


async def test_bus_uses_isolated_stream_prefix(monkeypatch, tmp_path):
    from parrot.storage import turn_bus
    monkeypatch.setattr(conf, "PARROT_TURN_BUS_REDIS_URL", "redis://localhost:6399/0", raising=False)
    monkeypatch.setattr(conf, "PARROT_TURN_BUS_OUTBOX_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(conf, "PARROT_TURN_BUS_CHANNEL_PREFIX", "test:turns:", raising=False)
    bus = turn_bus._build_bus({})
    try:
        backend = bus.core._backend
        assert type(backend).__name__ == "RedisStreamsBackend"
        assert backend.stream_prefix == "test:turns:"            # NOT the library default "evb:stream:"
        assert bus.core._publish_only is False
        assert bus.core._outbox is not None
    finally:
        await bus.close()


async def test_setup_subscribes_and_stores_a_turn(memory_bus, chat_storage, backend):
    handle = await setup_turn_persistence(chat_storage, bus=memory_bus)
    try:
        assert isinstance(handle, TurnPersistence) and len(handle.subscription_ids) == 2
        # FILL IN: await handle.publisher.publish(<TurnCompletedEvent from _payload()>) then
        #   assert await _eventually(lambda: stored(backend, "s1")) — bounded by AC 2.
    finally:
        await shutdown_turn_persistence(handle)


async def test_retry_exhaustion_lands_in_dead_letters(tmp_path, backend):
    from parrot.storage import turn_bus
    store = SqliteDeadLetterStore(tmp_path / "host-dead-letters.db")
    bus = EventBus(transport="memory", retry_attempts=3, retry_base_delay=0.0,
                   on_dlq=turn_bus._make_dlq_callback({"dlq": store}))

    class Down(ConversationSQLiteBackend):
        async def put_turn(self, *a, **k):
            raise StorageUnavailableError("down")
    down = Down(path=str(tmp_path / "down.db"))
    await down.initialize()
    storage = ChatStorage(redis_conversation=None, dynamodb=down)
    storage._initialized = True
    handle = await setup_turn_persistence(storage, bus=bus)
    try:
        await bus.core.publish(EventEnvelope(topic=TURN_COMPLETED_TOPIC, payload=_payload("t-dead"), event_id="t-dead"))
        assert await _eventually(lambda: _has_pending(store, "t-dead"))
    finally:
        await shutdown_turn_persistence(handle)
        await down.close()


async def _has_pending(store, event_id):
    return any(e.event_id == event_id for e in await store.pending())


async def test_dead_letter_store_round_trip_and_reopen(tmp_path):
    path = tmp_path / "dl.db"
    env = EventEnvelope(topic=TURN_COMPLETED_TOPIC, payload={"k": "v"}, event_id="e1")
    store = SqliteDeadLetterStore(path)
    await store.add(env, attempts=3, error=RuntimeError("boom"), subscriber_id="sub")
    reopened = SqliteDeadLetterStore(path)                          # a restarted process sees it
    assert [e.event_id for e in await reopened.pending()] == ["e1"]
    await reopened.mark_replayed("e1")
    assert await reopened.pending() == []
    await reopened.add(env, attempts=3, error=RuntimeError("again"), subscriber_id="sub")
    assert [e.event_id for e in await reopened.pending()] == ["e1"]  # fails again -> pending again


async def test_replay_republishes_once_and_never_resurrects_tombstoned(memory_bus, chat_storage, backend, tmp_path):
    store = SqliteDeadLetterStore(tmp_path / "dl.db")
    handle = await setup_turn_persistence(chat_storage, bus=memory_bus)
    handle.dlq = store
    try:
        await store.add(EventEnvelope(topic=TURN_COMPLETED_TOPIC, payload=_payload("t-ok", "s1"), event_id="t-ok"),
                        attempts=3, error=RuntimeError("x"), subscriber_id="s")
        assert await replay_dead_letters(handle) == 1
        assert await replay_dead_letters(handle) == 0
        # FILL IN: tombstone session "s2" (backend.put_tombstone), add a dead letter for it, replay, then assert
        #   backend.query_turn_window(USER, AGENT, "s2", 5) raises ConversationDeletedError and no turn is visible —
        #   bounded by spec §5 "Deletion races".
    finally:
        await shutdown_turn_persistence(handle)


async def test_replay_without_dlq_raises(memory_bus, chat_storage):
    handle = await setup_turn_persistence(chat_storage, bus=memory_bus)
    try:
        with pytest.raises(RuntimeError):
            await replay_dead_letters(handle)
    finally:
        await shutdown_turn_persistence(handle)


async def test_deletion_event_reaches_cleanup_handler(memory_bus, chat_storage):
    calls = []

    async def cleaner(user_id, agent_id, session_id):
        calls.append((user_id, agent_id, session_id))
    chat_storage.register_memory_cleaner(cleaner)
    handle = await setup_turn_persistence(chat_storage, bus=memory_bus)
    try:
        await chat_storage.delete_conversation(USER, "s1", agent_id=AGENT)
        # delete runs the cleaners once itself and publishes the event; the handler runs them again (idempotent retry path)
        assert await _eventually(lambda: _async_true(len(calls) >= 2))
    finally:
        await shutdown_turn_persistence(handle)


async def _async_true(value):
    return value


async def test_shutdown_is_idempotent_and_keeps_outbox(memory_bus, chat_storage, tmp_path):
    handle = await setup_turn_persistence(chat_storage, bus=memory_bus)
    await shutdown_turn_persistence(handle)
    await shutdown_turn_persistence(handle)
    assert (tmp_path / "outbox.db").exists()
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`). Run `uv sync` there so
   `navigator-eventbus >= 0.4.0` is installed (the main checkout's `.venv` has 0.3.0).
2. **Read the spec** (`sdd/specs/durable-conversation-memory.spec.md`, Modules 2, 9, 10 and §8 Q11, Q15, Q16).
3. **Check dependencies** — TASK-5569, TASK-5579, TASK-5571 must be `"done"` in
   `sdd/tasks/index/durable-conversation-memory.json`.
4. **Verify the Codebase Contract** — re-grep the dependency symbols and re-read `navigator_eventbus` `evb.py` /
   `outbox.py` / `dlq.py` in the INSTALLED version; if `EventBus` started honouring `channel_prefix` for streams, update
   "Library drift 1" first.
5. **Update status** in the per-spec index -> `"in-progress"` and commit only that file.
6. **Implement** from the blueprint, complete every `# FILL IN:`, run the Validation Commands and the four mutation checks.
7. **Commit only the three listed files**; close with
   `parrot sdd task close TASK-5581 durable-conversation-memory verified`; fill the Completion Note.

---

## Completion Note

Added PARROT_TURN_BUS_* settings and parrot/storage/turn_bus.py (TurnPersistence, setup/shutdown/replay, SqliteDeadLetterStore, late-bound on_dlq, explicit RedisStreamsBackend so PARROT_TURN_BUS_CHANNEL_PREFIX is honoured, deletion publisher via bus.core.publish).

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-11-13
**Tests**: test_turn_bus_setup 9 passed — navigator-eventbus 0.4.1 memory transport + real ChatStorage over real SQLite, real files. ruff clean. NOT covered here (by the task's own scope): the Redis Streams end-to-end / crash recovery (TASK-5585); the Postgres DLQHandler path (needs a server) — only the local SQLite dead-letter path is exercised; the explicit RedisStreamsBackend is only constructed (no live Redis in these tests).
**Mutation evidence**: no deletion-topic subscription / no-op DLQ callback / no W_OK check / channel_prefix instead of explicit backend / replay without mark_replayed -> each RED. Restored by re-applying.
**Notes**: the installed library (0.4.1) ignores channel_prefix for streams and keeps no dead letters in the outbox, hence the explicit backend and the local SqliteDeadLetterStore (task "Library drift").

**Deviations from spec**: none
