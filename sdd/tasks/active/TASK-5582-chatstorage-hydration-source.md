# TASK-5582: `ChatStorageHydrationSource` — backend errors to hydration errors, rows to turns

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 14)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5573, TASK-5570, TASK-5580, TASK-5574
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 14 and §2 "Piece 2". The bot never imports `ChatStorage` (spec §5 "Stores separate"); it
consults an injected `HydrationSource` (TASK-5580). This task is the one implementation of that interface
over a `ConversationBackend`: a **pure translation layer**. It maps the TASK-5570 storage errors to the
TASK-5580 hydration errors, turns stored rows into `ConversationTurn` through the tolerant reader
(`ChatStorageTurn.from_row(...).to_conversation_turn()`, TASK-5573) and never converts a failure, a deleted
session or an unready index into `None` or `[]`. TASK-5584 injects an instance of this class into every bot
the `BotManager` registers.

---

## Scope

- Create `parrot/storage/hydration.py` with `ChatStorageHydrationSource(HydrationSource)`.
- Implement `load_turns`, `is_deleted`, `max_sequence` per the mapping table below.
- Unit tests against the real SQLite backend, plus small real backend subclasses that raise specific
  `StorageError`s.

**NOT in scope**: the `HydrationSource` ABC and its error types (TASK-5580); `ChatStorageTurn` (TASK-5573);
backend operations (TASK-5570/5574..5577); exporting the class from `parrot/storage/__init__.py` (that file is
owned by TASK-5570/5573 — import it as `parrot.storage.hydration.ChatStorageHydrationSource`);
installing the source on bots (TASK-5583/5584).

**Mapping table (spec §3 M14, authoritative)**

| Backend outcome | Hydration outcome |
|---|---|
| `get_index_state(...) != "ready"` | `HydrationNotReadyError` (but `SessionDeletedError` if the identity is tombstoned — deletion wins) |
| `IndexNotReadyError` from `query_turn_window` | `HydrationNotReadyError` |
| `ConversationDeletedError` (any call) | `SessionDeletedError` |
| `StorageUnavailableError` / any other `StorageError` (any call) | `HydrationUnavailableError` |
| `query_turn_window` returns `[]` | `None` ("active session, no retained turns") |
| rows | `[ChatStorageTurn.from_row(r).to_conversation_turn() ...]`, ascending, newest `max_turns` |

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/hydration.py` | CREATE | `ChatStorageHydrationSource` |
| `packages/ai-parrot/tests/unit/storage/test_chat_storage_hydration_source.py` | CREATE | error mapping, `[]` to `None`, key alignment, window |

---

## Codebase Contract (Anti-Hallucination)

Re-verified against the tree at `6d564b36a2` (branch `dev`). Paths relative to `packages/ai-parrot/`
unless they start with `packages/`.

### Verified Imports
```python
from navconfig.logging import logging                                  # verified: src/parrot/storage/backends/sqlite.py:27
from parrot.storage.backends.base import ConversationBackend           # verified: src/parrot/storage/backends/base.py:15
from parrot.memory.abstract import ConversationTurn                    # verified: src/parrot/memory/abstract.py:102
from parrot.storage.backends.sqlite import ConversationSQLiteBackend   # verified: src/parrot/storage/backends/sqlite.py:35  (tests)
```

### Provided by dependency tasks (NOT in the tree yet — re-grep after each lands)
```python
from parrot.memory.hydration import (                    # TASK-5580 (new module)
    HydrationSource, HydrationError, HydrationUnavailableError, HydrationNotReadyError, SessionDeletedError)
from parrot.storage.errors import (                      # TASK-5570 (new module; ParrotError subclasses)
    StorageError, StorageUnavailableError, StorageWriteError,
    ConversationDeletedError, IndexNotReadyError, InvalidTurnPayloadError)
from parrot.storage.models import ChatStorageTurn        # TASK-5573: .from_row(dict) / .to_row() / .to_conversation_turn()
# ConversationBackend (TASK-5570):
#   query_turn_window(user_id, agent_id, session_id, limit) -> List[dict]   # newest `limit`, ascending
#   max_sequence(user_id, agent_id, session_id) -> int
#   is_deleted(user_id, agent_id, session_id, turn_id=None) -> bool
#   get_index_state(user_id, agent_id, session_id) -> 'ready'|'pending'|'invalid'
# HydrationSource abstract methods (TASK-5580), NOTE the argument order:
#   load_turns(agent_name, user_id, session_id, max_turns) -> Optional[List[ConversationTurn]]
#   is_deleted(agent_name, user_id, session_id) -> bool
#   max_sequence(agent_name, user_id, session_id) -> int
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/abstract.py
@dataclass
class ConversationTurn:                      # :102  turn_id, user_id, user_message, assistant_response, chatbot_id, ... (+ `sequence` from TASK-5569)
```

### Does NOT Exist
- ~~`parrot.storage.hydration`~~ — created by THIS task.
- ~~`ChatStorage.get_context_for_agent` as a hydration path~~ — no callers; never use it here (spec §1.1).
- ~~An import of `parrot.storage.chat` in this module~~ — the source talks to the BACKEND directly, not through `ChatStorage`.
- ~~An import of this module from `parrot/bots/`~~ — the bot package must not import `parrot.storage.*` (spec §5).

### Obtaining the backend (coordinator requirement)
The source takes a `ConversationBackend` in its constructor and never reads `ChatStorage` private attributes. Callers (TASK-5584) build it as
`ChatStorageHydrationSource(chat_storage.cold_backend)` using the public read-only property added by TASK-5579 (`ChatStorage.cold_backend`,
today `_dynamo`); when it is `None` no source is attached. This module must not import `parrot.storage.chat`.

### Gotchas (verified)
- **Argument order differs** between the two interfaces: `HydrationSource` is `(agent_name, user_id, session_id)`;
  `ConversationBackend` is `(user_id, agent_id, session_id)`. The agent NAME is the ChatStorage key (spec §2
  "Identity"); pass `agent_name` as the backend's `agent_id`. A swapped call silently queries another partition and
  returns `None` — the key-alignment test below guards it.
- The stored row carries `chatbot_id` (the bot's `memory_key_id`); `to_conversation_turn()` keeps it so
  `render_history(current_chatbot_id=...)` attributes hydrated turns correctly. The cold KEY is still the agent name.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/storage/hydration.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/storage/test_chat_storage_hydration_source.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend",
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationTurn",
    "sym:packages/ai-parrot/src/parrot/storage/backends/sqlite.py#ConversationSQLiteBackend"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Translate at the boundary, chain the cause (`raise ... from exc`), never log-and-swallow. Same "typed errors, never a
silent empty" stance as the M4 backend contract.

### Key Constraints
- Every `except` maps to a TYPED hydration error; there is no `except Exception: return None` anywhere (spec §2:
  "never converted to `None` or an empty list").
- The `except` order matters: `ConversationDeletedError` and `IndexNotReadyError` are `StorageError` subclasses, so
  catch them BEFORE the generic `StorageError`.
- Deletion wins (spec G7): when the index is not ready, probe `is_deleted` before raising `HydrationNotReadyError`, so
  a tombstoned legacy session reports `SessionDeletedError`, not "retry later". The extra call happens only on the
  not-ready path.
- `max_turns < 1` raises `ValueError` (the bot passes the budget; a bad value is a caller bug, not an empty history).
- A row the tolerant reader rejects (`InvalidTurnPayloadError`, a `StorageError`) surfaces as `HydrationUnavailableError`
  with the cause chained — a corrupt window must not be served silently truncated.
- Complexity: each method <= 60 lines, cyclomatic <= 10; keep the error translation in one private helper.
- `self.logger` calls at DEBUG for the outcome (agent, session, count); never log message content.

### References in Codebase
- `packages/ai-parrot/src/parrot/storage/instrumented.py` — a thin delegating wrapper over `ConversationBackend`
  (shape reference only).

---

## Implementation Blueprint

### Steps (in order)
1. Re-grep the "Provided by dependency tasks" imports and confirm the argument orders above — *why*: four tasks feed
   this one; a rename is drift to fix in this file first.
2. Create `storage/hydration.py` — *why*: single translation module.
3. Write the tests (real SQLite + raising subclasses), run the mutation checks — *why*: the mapping is the whole
   value of this module.

### `packages/ai-parrot/src/parrot/storage/hydration.py` (CREATE)
```python
"""``HydrationSource`` over a ``ConversationBackend`` (FEAT-886 M14).

A pure translation layer: backend (storage) errors become hydration errors, stored rows become
``ConversationTurn`` through the tolerant reader. It never converts a failure, a deleted session or an
unready index into ``None`` / ``[]``.
"""
from __future__ import annotations

from typing import List, Optional

from navconfig.logging import logging

from parrot.memory.abstract import ConversationTurn
from parrot.memory.hydration import (
    HydrationNotReadyError,
    HydrationSource,
    HydrationUnavailableError,
    SessionDeletedError,
)
from parrot.storage.backends.base import ConversationBackend
from parrot.storage.errors import ConversationDeletedError, IndexNotReadyError, StorageError
from parrot.storage.models import ChatStorageTurn


class ChatStorageHydrationSource(HydrationSource):
    """Hydration source backed by the ChatStorage cold tier.

    Args:
        backend: The initialised cold-tier backend (the same one ``ChatStorage`` writes to).
    """

    def __init__(self, backend: ConversationBackend) -> None:
        self._backend = backend
        self.logger = logging.getLogger("parrot.storage.ChatStorageHydrationSource")

    async def load_turns(
        self, agent_name: str, user_id: str, session_id: str, max_turns: int
    ) -> Optional[List[ConversationTurn]]:
        """Newest ``max_turns`` turns, ascending; ``None`` when the session has none.

        Raises:
            ValueError: ``max_turns < 1``.
            HydrationNotReadyError: the chronological index is not ready.
            SessionDeletedError: the session is tombstoned.
            HydrationUnavailableError: the backend failed or a row could not be read.
        """
        if max_turns < 1:
            raise ValueError("max_turns must be >= 1")
        try:
            await self._require_ready(agent_name, user_id, session_id)
            rows = await self._backend.query_turn_window(user_id, agent_name, session_id, max_turns)
            if not rows:
                return None
            return [ChatStorageTurn.from_row(row).to_conversation_turn() for row in rows]
        except (ConversationDeletedError, IndexNotReadyError, StorageError) as exc:
            raise self._translate(exc, agent_name, session_id) from exc

    async def is_deleted(self, agent_name: str, user_id: str, session_id: str) -> bool:
        """Authoritative deletion guard. Raises ``HydrationUnavailableError`` if it cannot be determined."""
        # FILL IN: `await self._backend.is_deleted(user_id, agent_name, session_id)`; wrap StorageError via
        #   self._translate(...) — bounded by spec §3 M13 ("raises HydrationUnavailableError if unknown", never False).
        raise NotImplementedError

    async def max_sequence(self, agent_name: str, user_id: str, session_id: str) -> int:
        """Durable maximum sequence for allocator recovery (0 when none)."""
        # FILL IN: delegate to `self._backend.max_sequence(user_id, agent_name, session_id)`; translate StorageError —
        #   bounded by the mapping table.
        raise NotImplementedError

    async def _require_ready(self, agent_name: str, user_id: str, session_id: str) -> None:
        """Raise unless the session's chronological index is ``ready`` (deletion wins over not-ready)."""
        state = await self._backend.get_index_state(user_id, agent_name, session_id)
        if state == "ready":
            return
        if await self._backend.is_deleted(user_id, agent_name, session_id):
            raise ConversationDeletedError(f"session {session_id} is deleted")
        raise IndexNotReadyError(f"index for session {session_id} is {state!r}")

    def _translate(self, exc: Exception, agent_name: str, session_id: str) -> Exception:
        """Map a storage error to its hydration error (order matters: subclasses first)."""
        # FILL IN: ConversationDeletedError -> SessionDeletedError; IndexNotReadyError -> HydrationNotReadyError;
        #   any other StorageError -> HydrationUnavailableError; each message names agent_name and session_id but
        #   never message content — bounded by the mapping table in Scope.
        raise NotImplementedError
```
**Why this shape**: `_require_ready` raises the *storage* errors so one `except` clause and one `_translate` own the
whole mapping (single place to audit). `load_turns` stays under the complexity budget. The `is_deleted` probe on the
not-ready path implements "deletion wins" without adding a call to the hot (ready) path. Do NOT widen the `except` to
`Exception`, and do NOT return `[]`.

### FILL IN checklist
- [ ] `hydration.py::_translate` — the three-way mapping; bounded by the Scope table.
- [ ] `hydration.py::is_deleted` / `max_sequence` — delegate with translation; bounded by spec §3 M13.
- [ ] tests: the "corrupt row" case — bounded by TASK-5573's `from_row` failure mode (read it after it lands; if
      `from_row` never raises, drop that test and say so in the Completion Note).
- [ ] tests: how to seed a legacy (`pending`) session — bounded by TASK-5574's schema (raw `INSERT` into
      `conversations` without the new columns, as in `test_backfill.py`).

---

## Acceptance Criteria

- [ ] Each backend error maps to its hydration error; `[]` maps to `None` (spec §4 `test_hydration_source_error_mapping`).
- [ ] A not-ready index never yields `None` or `[]`; a tombstoned not-ready session reports `SessionDeletedError`
      (spec §5 "not-ready is never reported as an empty history"; "Deletion races").
- [ ] The newest `max_turns` turns come back ascending with random / equal-timestamp IDs and more rows than the limit
      (spec §5 "Chronological hydration").
- [ ] **Key alignment**: turns stored under agent name `agent-a` with `chatbot_id="uuid-1"` load via
      `load_turns("agent-a", ...)`; each hydrated turn keeps `chatbot_id == "uuid-1"` (spec §5 "Key alignment").
- [ ] `max_turns < 1` raises `ValueError`; a corrupt row raises `HydrationUnavailableError` with `__cause__` set.
- [ ] `parrot.bots` does not import `parrot.storage.hydration` (grep clean).
- [ ] **Mutation checks**: (1) change `_translate` so `StorageUnavailableError` returns `None` from `load_turns` →
      `test_unavailable_is_never_none` goes RED; (2) swap `user_id`/`agent_name` in the `query_turn_window` call →
      `test_key_alignment_agent_name_vs_chatbot_id` goes RED; (3) remove the `is_deleted` probe in `_require_ready` →
      `test_tombstoned_unready_session_reports_deleted` goes RED. Restore by re-applying the edit, never `git checkout`.
- [ ] `ruff check packages/ai-parrot/src/parrot/storage/hydration.py packages/ai-parrot/tests/unit/storage/test_chat_storage_hydration_source.py` is clean.
- [ ] Imports work: `from parrot.storage.hydration import ChatStorageHydrationSource`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/storage/test_chat_storage_hydration_source.py -q`
- `pytest packages/ai-parrot/tests/unit/storage/test_chat_storage_hydration_source.py::test_hydration_source_error_mapping -q`

---

## Test Specification

Real SQLite backend on `tmp_path`; error injection uses tiny **real subclasses** of `ConversationSQLiteBackend`
that override one method to raise a real `StorageError` (no `Mock`/`AsyncMock`).

```python
# packages/ai-parrot/tests/unit/storage/test_chat_storage_hydration_source.py
import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from parrot.memory.abstract import ConversationTurn
from parrot.memory.hydration import (
    HydrationNotReadyError, HydrationUnavailableError, SessionDeletedError)
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.errors import (
    ConversationDeletedError, IndexNotReadyError, StorageUnavailableError, StorageWriteError)
from parrot.storage.hydration import ChatStorageHydrationSource
from parrot.storage.models import ChatStorageTurn

USER, AGENT, BOT_ID = "u1", "agent-a", "uuid-1"
T0 = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _turn(i: int, *, ts=None, session="s1") -> ChatStorageTurn:
    return ChatStorageTurn(
        turn_id=f"{random.getrandbits(64):016x}", user_id=USER, session_id=session, agent_id=AGENT,
        chatbot_id=BOT_ID, timestamp=ts or (T0 + timedelta(minutes=i)), sequence=i,
        user_message=f"q{i}", assistant_response=f"a{i}")


@pytest.fixture
async def backend(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "h.db"))
    await b.initialize()
    yield b
    await b.close()


async def _store(backend, turns, session="s1"):
    for t in turns:
        await backend.put_turn(USER, AGENT, session, t.turn_id, t.to_row())


async def test_returns_newest_window_ascending(backend):
    turns = [_turn(i) for i in range(6)]
    random.shuffle(turns)                                   # insertion order != chronology
    await _store(backend, turns)
    out = await ChatStorageHydrationSource(backend).load_turns(AGENT, USER, "s1", 3)
    assert [t.user_message for t in out] == ["q3", "q4", "q5"]
    assert all(isinstance(t, ConversationTurn) for t in out)


async def test_equal_timestamps_use_sequence_then_turn_id(backend):
    same = [_turn(i, ts=T0) for i in range(4)]
    await _store(backend, same)
    out = await ChatStorageHydrationSource(backend).load_turns(AGENT, USER, "s1", 4)
    assert [t.user_message for t in out] == ["q0", "q1", "q2", "q3"]   # sequence is the tie-breaker


async def test_empty_session_is_none_not_empty_list(backend):
    assert await ChatStorageHydrationSource(backend).load_turns(AGENT, USER, "nope", 5) is None


async def test_key_alignment_agent_name_vs_chatbot_id(backend):
    await _store(backend, [_turn(0)])
    src = ChatStorageHydrationSource(backend)
    out = await src.load_turns(AGENT, USER, "s1", 5)         # keyed by agent NAME ...
    assert out and out[0].chatbot_id == BOT_ID               # ... carries the bot's memory_key_id
    assert await src.load_turns(BOT_ID, USER, "s1", 5) is None   # the chatbot_id is NOT the cold key


async def test_hydration_source_error_mapping(backend, tmp_path):
    cases = [
        ("query_turn_window", ConversationDeletedError("x"), SessionDeletedError),
        ("query_turn_window", IndexNotReadyError("x"), HydrationNotReadyError),
        ("query_turn_window", StorageUnavailableError("x"), HydrationUnavailableError),
        ("query_turn_window", StorageWriteError("x"), HydrationUnavailableError),
        ("get_index_state", StorageUnavailableError("x"), HydrationUnavailableError),
    ]
    for method, error, expected in cases:
        class Failing(ConversationSQLiteBackend):
            async def _boom(self, *a, **k):
                raise error
        setattr(Failing, method, Failing._boom)
        b = Failing(path=str(tmp_path / f"{method}-{type(error).__name__}.db"))
        await b.initialize()
        try:
            with pytest.raises(expected) as info:
                await ChatStorageHydrationSource(b).load_turns(AGENT, USER, "s1", 5)
            assert info.value.__cause__ is error
        finally:
            await b.close()


async def test_unavailable_is_never_none(backend):
    # FILL IN: closed backend (`await backend.close()`) -> load_turns / is_deleted / max_sequence all raise
    #   HydrationUnavailableError, none return None / False / 0 — bounded by spec §3 M14 and AC "No silent backend writes".
    ...


async def test_unready_index_is_not_none(backend):
    legacy = {"turn_id": "z" * 16, "user_message": "q", "assistant_response": "a",
              "timestamp": T0.isoformat()}
    await backend._conn.execute(
        "INSERT OR REPLACE INTO conversations (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at) "
        "VALUES (?, ?, 'old', 'turn', ?, ?, 0, NULL)", (USER, AGENT, f"TURN#{legacy['turn_id']}", json.dumps(legacy)))
    await backend._conn.commit()
    with pytest.raises(HydrationNotReadyError):
        await ChatStorageHydrationSource(backend).load_turns(AGENT, USER, "old", 5)


async def test_tombstoned_unready_session_reports_deleted(backend):
    # FILL IN: seed the same legacy row as above, `await backend.put_tombstone(USER, AGENT, "old")`, expect
    #   SessionDeletedError (not HydrationNotReadyError) — bounded by spec G7 "Deletion wins".
    ...


async def test_is_deleted_and_max_sequence_delegate(backend):
    await _store(backend, [_turn(i) for i in range(3)])
    src = ChatStorageHydrationSource(backend)
    assert await src.max_sequence(AGENT, USER, "s1") == 2
    assert await src.is_deleted(AGENT, USER, "s1") is False
    await backend.put_tombstone(USER, AGENT, "s1")
    assert await src.is_deleted(AGENT, USER, "s1") is True


async def test_rejects_non_positive_max_turns(backend):
    with pytest.raises(ValueError):
        await ChatStorageHydrationSource(backend).load_turns(AGENT, USER, "s1", 0)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`).
2. **Read the spec** (`sdd/specs/durable-conversation-memory.spec.md`, Modules 3, 4, 13, 14).
3. **Check dependencies** — TASK-5573, TASK-5570, TASK-5580, TASK-5574 must all be `"done"` in
   `sdd/tasks/index/durable-conversation-memory.json`.
4. **Verify the Codebase Contract** — especially the TASK-5573 `ChatStorageTurn` API and the TASK-5570 error names.
5. **Update status** in the per-spec index → `"in-progress"` and commit only that file.
6. **Implement** from the blueprint, complete every `# FILL IN:`, run the Validation Commands and the mutation checks.
7. **Commit only the two listed files**; close with
   `parrot sdd task close TASK-5582 durable-conversation-memory verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
