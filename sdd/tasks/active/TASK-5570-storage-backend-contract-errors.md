# TASK-5570: Backend contract — typed errors, ordered window, tombstones, index state

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 4)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 / §2 "Piece 1 — Backend failure contract" and "Piece 2 — Chronological query contract".
Today `put_turn` returns silently when a backend is disconnected and DynamoDB swallows `ClientError`; there is no
chronological query, no durable deletion guard and no index-readiness state. This task defines the CONTRACT every
backend must satisfy — it changes no concrete backend:

- `parrot/storage/errors.py` — the `StorageError` hierarchy.
- `ConversationBackend` — seven new `@abstractmethod`s (`query_turn_window`, `max_sequence`, `put_tombstone`, `is_deleted`,
  `get_index_state`, `backfill_batch`; plus the new contract text on `put_turn` / `query_turns`) and the `BackfillBatch` result type.
- `InstrumentedBackend` — delegates each new operation.
- `tests/storage/durable_contract.py` — shared async check functions (NOT collected by pytest) that
  TASK-5574..5577 run against SQLite / Postgres / Mongo / DynamoDB.

TASK-5573 (`InvalidTurnPayloadError`), TASK-5574..5578, 5579, 5582 all import from here.

---

## Scope

- Create `parrot/storage/errors.py` with the six error classes of spec §3 M4.
- Add the new abstract operations and `BackfillBatch` to `ConversationBackend`; update the `put_turn` / `query_turns` docstrings to the new failure contract.
- Delegate the new operations in `InstrumentedBackend` (thin `*a, **kw`, same `_measure` pattern).
- Export `StorageError` family + `BackfillBatch` from `parrot/storage/__init__.py`.
- Create `tests/storage/durable_contract.py` (a harness dataclass + one `check_*` coroutine per contract clause) and
  `tests/storage/test_storage_errors.py` (hierarchy, abstract surface, and a self-test of the checks against an in-file reference backend).
- Update `tests/storage/test_instrumented_backend.py`: its `_Stub` must implement every new abstract method and a new test must
  prove each new operation is delegated and measured.

**NOT in scope**: any concrete backend (`sqlite.py`, `postgres.py`, `mongodb.py`, `dynamodb.py` — TASK-5574..5577);
`ChatStorageTurn` and `InvalidTurnPayloadError` usage (TASK-5573); `ChatStorage` (TASK-5579); `backfill.py` (TASK-5578);
`parrot/clients/base.py`.

### Known decision to record (state it in the Completion Note)

The spec fixes the new operations as `@abstractmethod`. Between this task and TASK-5574..5577 the four concrete backends are
**uninstantiable**, so existing suites that build them are red INSIDE the feature branch until all four land. Affected files
that this task cannot edit (not in its table): `packages/ai-parrot/tests/storage/test_backend_contract.py` and
`tests/storage/conftest.py` (`any_backend` fixture), `tests/storage/backends/test_*_backend.py`,
(`tests/storage/backends/test_base_abc.py` is now IN this task's table and fixed here), and the root `tests/storage/test_dynamodb_backend.py`. Keep the abstract methods;
do NOT add default implementations to make them green.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/errors.py` | CREATE | `StorageError` hierarchy |
| `packages/ai-parrot/src/parrot/storage/backends/base.py` | MODIFY | new abstract operations + `BackfillBatch` |
| `packages/ai-parrot/src/parrot/storage/instrumented.py` | MODIFY | delegate the new operations |
| `packages/ai-parrot/src/parrot/storage/__init__.py` | MODIFY | export errors and `BackfillBatch` |
| `packages/ai-parrot/tests/storage/durable_contract.py` | CREATE | shared async check functions (no `test_` prefix, not collected) |
| `packages/ai-parrot/tests/storage/test_storage_errors.py` | CREATE | hierarchy, abstract surface, self-test of the shared checks |
| `packages/ai-parrot/tests/storage/test_instrumented_backend.py` | MODIFY | `_Stub` implements the new ops; delegation test |
| `packages/ai-parrot/tests/storage/backends/test_base_abc.py` | MODIFY | both in-file stubs implement the new abstract ops |

---

## Codebase Contract (Anti-Hallucination)

Re-verified against the tree at `6d564b36a2` (branch `dev`).

### Verified Imports
```python
from parrot.exceptions import ParrotError                           # verified: parrot/exceptions.py:12  (pure-Python class; __init__(self, message, *args, **kwargs))
from parrot.storage.backends.base import ConversationBackend        # verified: storage/backends/base.py:15; storage/__init__.py:18
from parrot.storage.metrics import NoopStorageMetrics, StorageMetrics   # verified: tests/storage/test_instrumented_backend.py:9
from parrot.storage.instrumented import InstrumentedBackend         # verified: storage/instrumented.py:16
from dataclasses import dataclass                                   # stdlib (NEW import in base.py)
from typing import List, Optional, Tuple                            # base.py currently: `from typing import List, Optional` (:12)
# tests only:
from parrot.storage.backends.sqlite import ConversationSQLiteBackend   # verified: storage/backends/sqlite.py:35 — NOT usable as the reference here (abstract until TASK-5574)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/storage/backends/base.py
class ConversationBackend(ABC):                                     # :15  ABC; `from abc import ABC, abstractmethod` :11
    async def put_turn(self, user_id, agent_id, session_id, turn_id, data: dict) -> None   # :82  docstring `"""Store a conversation turn."""` (1 occurrence)
    async def query_turns(self, user_id, agent_id, session_id, limit=10, newest_first=True) -> List[dict]  # :93  docstring `"""Query conversation turns for a session."""` (1 occurrence)
    async def delete_turn(self, user_id, agent_id, session_id, turn_id) -> bool           # :104  (signature stays)
    async def delete_thread_cascade(self, user_id, agent_id, session_id) -> int           # :118
    # section header comment `    # Artifacts` (1 occurrence) marks where the artifact methods start
    is_connected: property (abstract)                                                      # :36-39

# packages/ai-parrot/src/parrot/storage/instrumented.py
class InstrumentedBackend(ConversationBackend):                     # :16
    async def delete_thread_cascade(self, *a, **kw) -> int          # :89  (1 occurrence of this exact line)
    async def _measure(self, method: str, fn, *a, **kw)             # :123  records latency + error type, re-raises
    # `from typing import List, Optional` (:10, 1 occurrence)

# packages/ai-parrot/src/parrot/storage/__init__.py
from .backends.base import ConversationBackend                      # :18 (1 occurrence)
from .instrumented import InstrumentedBackend                       # :31 (1 occurrence)
"InstrumentedBackend",                                              # in __all__ (1 occurrence)

# packages/ai-parrot/tests/storage/test_instrumented_backend.py
class _Stub(ConversationBackend): ...                               # :22-41 — implements the 15 current abstract members only
class _CountingMetrics: record_latency / record_error              # :13-20
```

### Does NOT Exist
- ~~`parrot.storage.errors`~~ / ~~`StorageError`~~ (any type) — created by THIS task. The storage package today defines only `ExportError` and subclasses (`storage/exports.py:31`, an `Exception`, unrelated).
- ~~`ConversationBackend.query_turn_window` / `max_sequence` / `put_tombstone` / `is_deleted` / `get_index_state` / `backfill_batch`~~ — added here.
- ~~`BackfillBatch`~~ — added here (frozen dataclass, defined in `backends/base.py` per spec §3 M4).
- ~~`InvalidTurnPayloadError` raised anywhere~~ — defined here, first raised by TASK-5573.
- ~~Default (non-abstract) implementations of the new operations~~ — the spec makes them abstract on purpose (see "Known decision").
- ~~`ConversationBackend.put_turn` returning silently when disconnected~~ — this is the DEFECT being removed from the contract; the implementations change in TASK-5574..5577.
- ~~A `retryable` attribute on the errors~~ — the spec classifies by type; callers use `isinstance` (do not add one).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/storage/errors.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/storage/backends/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/storage/instrumented.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/storage/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/storage/durable_contract.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/storage/test_storage_errors.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/storage/test_instrumented_backend.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/storage/backends/test_base_abc.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/exceptions.py#ParrotError",
    "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend",
    "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend.put_turn",
    "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend.query_turns",
    "sym:packages/ai-parrot/src/parrot/storage/instrumented.py#InstrumentedBackend",
    "sym:packages/ai-parrot/src/parrot/storage/instrumented.py#InstrumentedBackend._measure"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Ordering key is `(timestamp, sequence, turn_id)`: `query_turn_window` applies `limit` DESCENDING at the backend and returns the window
  ASCENDING (spec §2 "Chronological query contract"). The docstrings must say so — TASK-5574..5577 implement from them.
- `is_deleted` NEVER returns `False` on failure; `put_tombstone` is idempotent and outside TTL / `delete_thread_cascade`.
- `get_index_state` returns exactly `'ready' | 'pending' | 'invalid'`; sessions created after FEAT-886 are `'ready'`.
- Error taxonomy (spec M4): `StorageUnavailableError` (disconnected / transport, retryable), `StorageWriteError` (durable write failed,
  retryable), `ConversationDeletedError` (tombstoned, terminal), `IndexNotReadyError` (not backfilled), `InvalidTurnPayloadError` (permanent payload defect, terminal).
- `ParrotError.__init__(message, ...)` takes a message; subclasses add nothing but a docstring (keep them trivially constructible: `StorageWriteError("...")`).
- `query_turns` raising `StorageUnavailableError` instead of returning `[]` when disconnected/failing is a CONTRACT statement here;
  the concrete change lands per backend.
- The shared checks must be pure `async def check_*(harness)` functions using only the ABC surface plus the harness hooks — no backend-specific imports.
- Complexity: each function ≤ 60 lines; `durable_contract.py` ≤ 500 lines. If the checks outgrow it, split into `durable_contract/` is NOT allowed (file list is fixed) — keep each check tight.

### References in Codebase
- `packages/ai-parrot/tests/storage/test_backend_contract.py` — the existing (non-durable) contract style; `conftest.py:55-` the `any_backend` parametrization.
- `packages/ai-parrot/tests/storage/backends/test_base_abc.py` — `EXPECTED_ABSTRACT_METHODS` pattern.
- `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py:276-313` — current silent-failure `put_turn` (the defect).

---

## Implementation Blueprint

### Steps (in order)
1. Create `errors.py` — *why*: `base.py` docstrings and tests import the names.
2. Edit `backends/base.py` — *why*: the contract itself.
3. Edit `instrumented.py` — *why*: it subclasses the ABC, so it is uninstantiable until it delegates every new method.
4. Edit `storage/__init__.py` — *why*: public exports.
5. Write `durable_contract.py`, then `test_storage_errors.py` (self-test against an in-file reference backend) — *why*: the checks are
   validated BEFORE four backends depend on them.
6. Update `test_instrumented_backend.py`.

### `packages/ai-parrot/src/parrot/storage/errors.py` (CREATE)
```python
"""Typed storage errors (FEAT-886).

Retry classification (used by ``ChatStorage.handle_turn_completed``):
retryable — :class:`StorageUnavailableError`, :class:`StorageWriteError`;
terminal — :class:`ConversationDeletedError`, :class:`InvalidTurnPayloadError`;
state — :class:`IndexNotReadyError` (the chronological index is not backfilled yet).
"""
from __future__ import annotations

from parrot.exceptions import ParrotError


class StorageError(ParrotError):
    """Base class for every failure raised by the conversation storage layer."""


class StorageUnavailableError(StorageError):
    """The backend is disconnected or the transport failed — retryable."""


class StorageWriteError(StorageError):
    """The durable write failed — retryable."""


class ConversationDeletedError(StorageError):
    """The session (or turn) identity is tombstoned — terminal."""


class IndexNotReadyError(StorageError):
    """The chronological index of the session is not backfilled (`pending` / `invalid`)."""


class InvalidTurnPayloadError(StorageError):
    """A permanent payload defect (missing identity or unparseable timestamp) — terminal."""
```
**Why this shape**: verbatim from spec §3 M4; `ParrotError` is the repo's single base (`exceptions.py:12`).

### `packages/ai-parrot/src/parrot/storage/backends/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from typing import List, Optional' base.py)  -> REPLACE with:
from dataclasses import dataclass
from typing import List, Optional, Tuple

# AFTER the imports and BEFORE `class ConversationBackend(ABC):` add:
@dataclass(frozen=True)
class BackfillBatch:
    """Result of one :meth:`ConversationBackend.backfill_batch` call."""

    processed: int
    next_cursor: Optional[str]      # None when the scan is complete
    invalid_sessions: Tuple[str, ...]

# occurrences: 1 (verified: grep -c '"""Store a conversation turn."""' base.py)  -> REPLACE the docstring with:
        """Idempotent upsert by ``turn_id``, atomic with the deletion guard and the chronological entry.

        Ordering fields (timestamp, sequence) of an existing turn are never changed.

        Raises:
            StorageUnavailableError: When the backend is disconnected.
            StorageWriteError: When the durable write fails.
            ConversationDeletedError: When the session or the turn is tombstoned.
        """

# occurrences: 1 (verified: grep -c '"""Query conversation turns for a session."""' base.py)  -> REPLACE with:
        """Query conversation turns for a session.

        Raises:
            StorageUnavailableError: When disconnected or the read fails — never returns ``[]`` for a failure.
        """

# occurrences: 1 (verified: grep -c '    # Artifacts' base.py)
# BEFORE — insert ABOVE the two-line section header whose second line is `    # Artifacts` (base.py:130), a new section:
    # ------------------------------------------------------------------
    # Durable conversation operations (FEAT-886)
    # ------------------------------------------------------------------

    @abstractmethod
    async def query_turn_window(
        self, user_id: str, agent_id: str, session_id: str, limit: int
    ) -> List[dict]:
        """The newest ``limit`` turns by ``(timestamp, sequence, turn_id)``, limit applied descending at the backend, returned ascending.

        Raises:
            StorageUnavailableError: Disconnected or the read failed.
            ConversationDeletedError: The session is tombstoned.
            IndexNotReadyError: The chronological index is not ready (no full scan is performed).

        An active session with no turns returns ``[]``.
        """

    @abstractmethod
    async def max_sequence(self, user_id: str, agent_id: str, session_id: str) -> int:
        """Highest stored ``sequence`` for the session, ``0`` when none."""

    @abstractmethod
    async def put_tombstone(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> None:
        """Durably record a session (``turn_id=None``) or turn deletion. Idempotent.

        Not subject to transcript TTL or :meth:`delete_thread_cascade`.
        """

    @abstractmethod
    async def is_deleted(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> bool:
        """Whether the identity is tombstoned.

        Raises:
            StorageUnavailableError: If it cannot be determined — never returns ``False`` on failure.
        """

    @abstractmethod
    async def get_index_state(self, user_id: str, agent_id: str, session_id: str) -> str:
        """``'ready'`` | ``'pending'`` | ``'invalid'``. Sessions created after FEAT-886 are ``'ready'``."""

    @abstractmethod
    async def backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch:
        """Index up to ``batch_size`` legacy turns after ``cursor``; resumable and safe alongside new writes.

        Marks a session ``'ready'`` once all its turns are indexed, ``'invalid'`` when a turn has a
        missing or unparseable timestamp.
        """
```
**Why**: signatures verbatim from spec §3 M4. `# occurrences: 1` for `    # Artifacts`; the dashed rule line above it belongs to the
same header — insert above the rule, not between rule and title. `query_turns` / `delete_turn` signatures do not change.

### `packages/ai-parrot/src/parrot/storage/instrumented.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def delete_thread_cascade(self, \*a, \*\*kw) -> int:' instrumented.py)
# AFTER the whole `delete_thread_cascade` method (instrumented.py:89-92), BEFORE the Artifacts section header (`    # Artifacts`, :95):
    # ------------------------------------------------------------------
    # Durable conversation operations (FEAT-886)
    # ------------------------------------------------------------------

    async def query_turn_window(self, *a, **kw) -> List[dict]:
        return await self._measure("query_turn_window", self._inner.query_turn_window, *a, **kw)

    async def max_sequence(self, *a, **kw) -> int:
        return await self._measure("max_sequence", self._inner.max_sequence, *a, **kw)

    async def put_tombstone(self, *a, **kw) -> None:
        return await self._measure("put_tombstone", self._inner.put_tombstone, *a, **kw)

    async def is_deleted(self, *a, **kw) -> bool:
        return await self._measure("is_deleted", self._inner.is_deleted, *a, **kw)

    async def get_index_state(self, *a, **kw) -> str:
        return await self._measure("get_index_state", self._inner.get_index_state, *a, **kw)

    async def backfill_batch(self, *a, **kw):
        return await self._measure("backfill_batch", self._inner.backfill_batch, *a, **kw)
```
**Why**: identical thin-delegate pattern as the existing methods; errors propagate unchanged through `_measure` (it re-raises), which the
new instrumented test asserts. No import of `BackfillBatch` is needed (no return annotation).

### `packages/ai-parrot/src/parrot/storage/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .backends.base import ConversationBackend' __init__.py)  -> REPLACE with:
from .backends.base import BackfillBatch, ConversationBackend         # FEAT-116 / FEAT-886
# occurrences: 1 (verified: grep -c 'from .instrumented import InstrumentedBackend' __init__.py)  -> add BELOW it:
from .errors import (                                                 # FEAT-886
    ConversationDeletedError,
    IndexNotReadyError,
    InvalidTurnPayloadError,
    StorageError,
    StorageUnavailableError,
    StorageWriteError,
)
# occurrences: 1 (verified: grep -c '    "InstrumentedBackend",' __init__.py)  -> add BELOW it, in __all__:
    # FEAT-886 durable backend contract
    "BackfillBatch",
    "StorageError",
    "StorageUnavailableError",
    "StorageWriteError",
    "ConversationDeletedError",
    "IndexNotReadyError",
    "InvalidTurnPayloadError",
```
**Why**: public surface; TASK-5573 later edits the same file at a different anchor (`from .chat import ChatStorage`).

### `packages/ai-parrot/tests/storage/durable_contract.py` (CREATE)
```python
"""Shared durable-contract checks (FEAT-886 M4). NOT a test module: no ``test_`` prefix, never collected.

Each ``check_*`` coroutine takes a :class:`DurableHarness` built by a backend's own test file
(TASK-5574 SQLite, 5575 Postgres, 5576 Mongo, 5577 DynamoDB) and asserts ONE clause of the
spec §4 "Backend contract suite". A clause that cannot run on a backend raises ``pytest.skip`` from the HARNESS hook, never here.
"""
from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional

import pytest

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    StorageUnavailableError,
    StorageWriteError,
)

USER, AGENT, SESSION = "u-durable", "agent-durable", "s-durable"


@dataclass
class DurableHarness:
    """Backend-specific hooks the shared checks need."""

    backend: ConversationBackend
    # FILL IN: hooks — each an async callable/context manager supplied by the backend test file:
    #   disconnect()          -> make backend.is_connected False (close())          [AC: disconnected raises]
    #   inject_write_failure()-> AbstractAsyncContextManager making the next durable write fail
    #   seed_legacy(session_id, rows: List[dict]) -> insert pre-FEAT-886 rows (random turn_id, no ts_utc/seq; a row may carry a bad timestamp)
    #   expire_transcript(session_id) -> simulate TTL expiry / transcript cleanup of turns (tombstones must survive)
    #   Bounded by spec §4 "Backend contract suite" and the abstract contract in backends/base.py.


def _turn(turn_id: str, ts: str, seq: int, text: str = "x") -> dict:
    """A turn payload with emitter-owned ordering fields (ISO-8601 UTC timestamp)."""
    return {"turn_id": turn_id, "timestamp": ts, "sequence": seq, "user_message": text, "assistant_response": text}


async def check_disconnected_raises(h: DurableHarness) -> None:
    """put_turn / query_turn_window / is_deleted raise StorageUnavailableError on a disconnected backend."""
    # FILL IN: await h.disconnect(); for each of the 3 calls: with pytest.raises(StorageUnavailableError). Bounded by AC-2.


async def check_failed_write_raises(h: DurableHarness) -> None:
    """A failed durable write raises StorageWriteError and stores nothing."""
    # FILL IN: async with h.inject_write_failure(): pytest.raises(StorageWriteError) on put_turn; then window is empty. AC-2.


async def check_put_turn_idempotent(h: DurableHarness) -> None:
    """Same turn_id twice -> one turn, ordering fields unchanged by the second write."""
    # FILL IN: put_turn(t1, ts=A, seq=1) then put_turn(t1, ts=B, seq=9); window has 1 row with ts==A, seq==1. AC-3.


async def check_window_newest_ascending(h: DurableHarness) -> None:
    """Random and reverse-lexical IDs, equal timestamps, rows > limit -> the same newest window, ascending."""
    # FILL IN: insert N>limit turns with shuffled/reverse-lexical turn_ids, some equal timestamps (tie-break: sequence, then
    #   turn_id); expected = sorted(all, key=(ts, seq, turn_id))[-limit:] ; assert [t["turn_id"] ...] == expected ids. AC-4.


async def check_tombstone_blocks_put(h: DurableHarness) -> None:
    """put_turn after put_tombstone raises ConversationDeletedError (session AND turn scoped); put_tombstone is idempotent."""
    # FILL IN: session tombstone -> put_turn raises, is_deleted True, query_turn_window raises ConversationDeletedError;
    #   turn tombstone -> only that turn_id is refused; repeat put_tombstone does not raise. AC-5.


async def check_tombstone_survives_cleanup(h: DurableHarness) -> None:
    """Tombstones survive delete_thread_cascade and transcript expiry."""
    # FILL IN: put_tombstone; await backend.delete_thread_cascade(...); await h.expire_transcript(SESSION); is_deleted still True. AC-5.


async def check_index_state(h: DurableHarness) -> None:
    """Legacy sessions report pending / invalid; new sessions ready; not-ready window raises IndexNotReadyError."""
    # FILL IN: seed_legacy a good session -> 'pending'; one with a bad timestamp -> 'invalid' after a backfill_batch run;
    #   query_turn_window on a non-ready session raises IndexNotReadyError; a session written via put_turn is 'ready'. AC-6.


async def check_max_sequence(h: DurableHarness) -> None:
    """max_sequence is the highest stored sequence, 0 when none."""
    # FILL IN: empty session -> 0; after turns with seq 3 and 8 -> 8. AC-4.


async def check_backfill_batch_resumable(h: DurableHarness) -> None:
    """backfill_batch pages with a cursor, returns BackfillBatch, and a second run is a no-op."""
    # FILL IN: seed >batch_size legacy rows; loop backfill_batch(cursor, size) until next_cursor is None; sum(processed) == seeded;
    #   re-run from None -> processed == 0 (already indexed); invalid_sessions lists the bad-timestamp session. AC-6.


ALL_CHECKS: List[Callable[[DurableHarness], Awaitable[None]]] = [
    check_disconnected_raises,
    check_failed_write_raises,
    check_put_turn_idempotent,
    check_window_newest_ascending,
    check_tombstone_blocks_put,
    check_tombstone_survives_cleanup,
    check_index_state,
    check_max_sequence,
    check_backfill_batch_resumable,
]
```
**Why this shape**: backends differ in how a failure is injected or a legacy row is seeded, so those are harness hooks; the ASSERTIONS are
shared so all four backends are held to one definition (spec §4: "one parametrized contract suite run against every backend").
Fixed names: `DurableHarness`, `ALL_CHECKS`, the `check_*` list above — TASK-5574..5577 import them. The `Optional` /
`AbstractAsyncContextManager` imports are for the harness field annotations; drop any import ruff reports unused.

### `packages/ai-parrot/tests/storage/test_storage_errors.py` (CREATE)
```python
"""FEAT-886 M4 — error hierarchy, abstract surface and a self-test of the shared durable checks."""
from __future__ import annotations

import pytest

from parrot.exceptions import ParrotError
from parrot.storage import (
    BackfillBatch,
    ConversationBackend,
    ConversationDeletedError,
    IndexNotReadyError,
    InvalidTurnPayloadError,
    StorageError,
    StorageUnavailableError,
    StorageWriteError,
)

NEW_ABSTRACT = {"query_turn_window", "max_sequence", "put_tombstone", "is_deleted", "get_index_state", "backfill_batch"}


def test_error_hierarchy():
    """Every storage error is a StorageError, which is a ParrotError."""
    # FILL IN: for each of the five subclasses: issubclass(.., StorageError) and issubclass(StorageError, ParrotError);
    #   StorageWriteError("boom") is constructible and str() == "boom". Bounded by AC-1.


def test_new_operations_are_abstract():
    """The six new operations are @abstractmethod; the ABC is still not instantiable."""
    # FILL IN: assert NEW_ABSTRACT <= set(ConversationBackend.__abstractmethods__). Mutation: drop one @abstractmethod -> RED. AC-1.


def test_backfill_batch_is_frozen():
    # FILL IN: BackfillBatch(1, None, ()) ; assigning .processed raises dataclasses.FrozenInstanceError. AC-1.


def test_durable_contract_is_not_collected():
    """durable_contract.py must not be a pytest module (no test_ prefix, no collectable test functions)."""
    # FILL IN: import tests.storage.durable_contract (or by path); assert no attribute name starts with "test_". AC-1.


# FILL IN: in-file `_ReferenceBackend(ConversationBackend)` — a complete in-memory implementation of the whole ABC
#   (<= ~120 lines; honest: it IS the executable definition of the contract: put_turn upserts keyed by turn_id and refuses tombstones,
#   query_turn_window sorts by (timestamp, sequence, turn_id) and honours limit descending, index state dict, backfill_batch
#   cursor over seeded legacy rows) plus a `_reference_harness()` building a DurableHarness for it; then
#   `@pytest.mark.parametrize("check", ALL_CHECKS)` test that every check PASSES against it, and ONE mutation test
#   (`_BrokenWindow` returning limit applied ascending) that `check_window_newest_ascending` FAILS against.
#   Bounded by AC-4 and the R6/mutation rule: a shared check that cannot fail is not a check.
```

### `packages/ai-parrot/tests/storage/test_instrumented_backend.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def delete_session_artifacts(self, \*a, \*\*kw): return 0' test_instrumented_backend.py)
# AFTER that last line of `class _Stub(ConversationBackend):` (test_instrumented_backend.py:41), add (still inside the class body):
    async def query_turn_window(self, *a, **kw): return []
    async def max_sequence(self, *a, **kw): return 0
    async def put_tombstone(self, *a, **kw): ...
    async def is_deleted(self, *a, **kw): raise RuntimeError("guard-boom")
    async def get_index_state(self, *a, **kw): return "ready"
    async def backfill_batch(self, *a, **kw): return BackfillBatch(0, None, ())

# add import at the top: `from parrot.storage.backends.base import BackfillBatch, ConversationBackend`  (replaces the existing ConversationBackend import line, :8)
# APPEND tests at the end of the file:
async def test_new_operations_are_delegated_and_measured():
    """Each FEAT-886 operation reaches the inner backend, is timed, and errors propagate + are counted."""
    # FILL IN: metrics=_CountingMetrics(); b=InstrumentedBackend(_Stub(), metrics=metrics);
    #   assert await b.query_turn_window("u","a","s",5) == [] ; await b.max_sequence(...) == 0 ; get_index_state == "ready";
    #   (await b.backfill_batch(None, 10)).next_cursor is None ; await b.put_tombstone(...) ;
    #   with pytest.raises(RuntimeError, match="guard-boom"): await b.is_deleted(...) and the error is recorded for method "is_deleted".
    #   The recorded latency method names == the six operation names. Bounded by AC-5.
```
**Why**: the `_Stub` is in-file by spec/brief ("must use its own in-file fake backend subclass implementing every abstract method"); it makes the
file green despite the four concrete backends being abstract-uninstantiable.

### `packages/ai-parrot/tests/storage/backends/test_base_abc.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '        async def delete_session_artifacts(self, \*a, \*\*kw): return 0' test_base_abc.py)
# Both are the LAST line of an in-file stub class: `_Stub` inside test_build_overflow_prefix_default_layout (:52) and
# `_MinimalStub` inside test_stub_subclass_can_be_instantiated (:83). Add, below EACH, at the same indentation:
        async def query_turn_window(self, *a, **kw): return []
        async def max_sequence(self, *a, **kw): return 0
        async def put_tombstone(self, *a, **kw): ...
        async def is_deleted(self, *a, **kw): return False
        async def get_index_state(self, *a, **kw): return "ready"
        async def backfill_batch(self, *a, **kw): return None
# Also extend EXPECTED_ABSTRACT_METHODS (:11-16) with the six new names.
```
**Why**: both stubs are instantiated, so both need the new abstract members; `test_stub_subclass_can_be_instantiated` stays green.

### FILL IN checklist
- [ ] `durable_contract.py::DurableHarness` hook set — bounded by what each backend can do (spec §4 clause list).
- [ ] Every `check_*` body — bounded by the ordering key `(timestamp, sequence, turn_id)` and AC-2..AC-6.
- [ ] `test_storage_errors.py` bodies + `_ReferenceBackend` + mutation test.
- [ ] `test_instrumented_backend.py::test_new_operations_are_delegated_and_measured`.
- [ ] `base.py`: exact insertion line above the `# Artifacts` header — keep the rule line attached to its title.

---

## Acceptance Criteria

- [ ] AC-1: `parrot.storage.errors` defines the six classes of spec §3 M4, all `StorageError` -> `ParrotError`; the six new operations are `@abstractmethod` on `ConversationBackend`; `BackfillBatch` is a frozen dataclass.
- [ ] AC-2 (spec §5 "No silent backend writes"): the contract text and `check_disconnected_raises` / `check_failed_write_raises` pin that a disconnected backend and a failed durable write RAISE (typed).
- [ ] AC-3: `check_put_turn_idempotent` pins "same `turn_id` leaves one turn and unchanged ordering fields".
- [ ] AC-4 (spec §5 "Chronological hydration"): `check_window_newest_ascending` / `check_max_sequence` pin newest-window-then-ascending with random + reverse-lexical IDs, equal timestamps, rows > limit.
- [ ] AC-5 (spec §5 "Deletion races", backend half): `check_tombstone_blocks_put` / `check_tombstone_survives_cleanup` pin fenced writes and tombstone survival of cascade/TTL; `InstrumentedBackend` delegates and measures every new op.
- [ ] AC-6 (spec §5 "Backfill"): `check_index_state` / `check_backfill_batch_resumable` pin pending/invalid/ready and `IndexNotReadyError` without a scan.
- [ ] Mutation checks (record evidence): (1) remove one `@abstractmethod` from `base.py` -> `test_new_operations_are_abstract` RED; (2) break the reference backend's window to apply `limit` ascending -> the self-test of `check_window_newest_ascending` RED; (3) drop a delegate in `InstrumentedBackend` -> `test_new_operations_are_delegated_and_measured` RED (class becomes abstract / TypeError).
- [ ] `durable_contract.py` is not collected by pytest.
- [ ] `parrot/clients/base.py` untouched. `ruff check` clean on all seven files.
- [ ] The Completion Note records the "Known decision" (concrete backends uninstantiable until TASK-5574..5577; list of expected-red existing suites).

---

## Validation Commands

> Only this task's own tests plus the instrumented-backend suite. The existing concrete-backend suites
> (`test_backend_contract.py`, `backends/test_*_backend.py`, `backends/test_base_abc.py`) are EXPECTED RED until TASK-5574..5577 land (see "Known decision") — do not list them.

- `pytest packages/ai-parrot/tests/storage/test_storage_errors.py -q`
- `pytest packages/ai-parrot/tests/storage/test_instrumented_backend.py -q`
- `pytest packages/ai-parrot/tests/storage/backends/test_base_abc.py -q`

---

## Test Specification

```python
# test_storage_errors.py
def test_error_hierarchy(): ...
def test_new_operations_are_abstract(): ...
def test_backfill_batch_is_frozen(): ...
def test_durable_contract_is_not_collected(): ...
@pytest.mark.parametrize("check", ALL_CHECKS)
async def test_reference_backend_satisfies_check(check): ...   # self-test: the shared checks are satisfiable
async def test_window_check_fails_on_ascending_limit(): ...     # mutation proof

# test_instrumented_backend.py
async def test_new_operations_are_delegated_and_measured(): ...
```
Fixtures (spec §4 "Test Data / Fixtures"): `failing_backend` is not needed here (the harness `inject_write_failure` covers it); `legacy_rows`
is a helper inside `durable_contract.py` (`_legacy_rows()`: random turn ids, no sequence, one invalid timestamp) — written in the file, no shared conftest edit.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-run every `grep -c` above; update the contract first if anything moved
5. **Update status** in `sdd/tasks/index/durable-conversation-memory.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** all acceptance criteria — run the Validation Commands and the mutation checks
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5570 durable-conversation-memory verified`
10. **Fill in the Completion Note** below (include the "Known decision"), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
