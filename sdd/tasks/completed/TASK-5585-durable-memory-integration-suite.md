# TASK-5585: Durable conversation memory — integration suite (the nine spec §4 scenarios)

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: sdd/specs/durable-conversation-memory.spec.md (Module 17; §4 "Integration Tests")
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5584
**Assigned-to**: unassigned

---

## Context

Spec §4 "Integration Tests": nine scenarios that prove the pieces meet. The unit tasks test each half (does
the bot publish; does the subscriber store; does the backend fence a tombstone); Rule 6 of ARCHITECTURE.md says
a green test proves nothing about a join it never crosses. This suite crosses every join end to end with
real objects: a real `BaseBot` round -> the real `BusTurnPublisher` -> a real `EventBus(transport="memory")`
(same retry / DLQ core as Streams, no Redis) -> the real `ChatStorage.handle_turn_completed` -> a real
`ConversationSQLiteBackend` -> a real `ChatStorageHydrationSource` -> a second real bot with empty working
memory.

---

## Scope

- Create one integration test file with the nine scenarios of spec §4, one `test_*` function each (the
  names are fixed by the spec).
- One shared in-file harness (`stack` fixture): backend, ChatStorage, bus, `TurnPersistence`, bot factory.
- One extra, clearly optional test for the spec §5 outbox-durability criterion, skipped without a real Redis
  (`TEST_REDIS_URL`), because the memory transport has no outbox.

**NOT in scope**:
- Any production code change. If a scenario cannot pass because a production piece is wrong, mark the
  scenario `xfail(strict=True)` with the defect named, report it, and do NOT patch production code here.
- Re-testing unit-level behavior already covered by TASK-5569..5583 (this suite asserts joins).
- The backend contract matrix (TASK-5574..5577) and the server wiring tests (TASK-5584).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/test_durable_conversation_memory.py` | CREATE | nine spec §4 integration scenarios + shared harness |

---

## Codebase Contract (Anti-Hallucination)

> `P` = `packages/ai-parrot/src/parrot`. Items marked **(created by TASK-NNNN)** are not in the tree yet.
> Because this is the last code task of the feature, every one of them MUST be re-verified by `grep` /
> `python -c "import ..."` before the tests are written.

### Verified Imports
```python
import asyncio, inspect, uuid
from pathlib import Path
import pytest
from navigator_eventbus import EventBus                              # >= 0.4.0 for transport=; local .venv has 0.3.0 (see below)
from parrot.bots.base import BaseBot                                 # verified: P/bots/base.py:130
from parrot.clients.base import AbstractClient                       # verified: P/clients/base.py
from parrot.memory import ConversationTurn, InMemoryConversation    # verified: P/memory/__init__.py
from parrot.models import AIMessage                                  # verified: P/models/__init__.py
from parrot.models.basic import ToolCall, CompletionUsage            # verified: P/models/basic.py:23, :48
from parrot.storage import ChatStorage                               # verified: P/storage/__init__.py:3
from parrot.storage.backends.sqlite import ConversationSQLiteBackend    # verified: P/storage/backends/sqlite.py:35
# created by dependencies:
from parrot.memory.hydration import (HydrationUnavailableError, LocalSequenceAllocator, SessionDeletedError)   # TASK-5580
from parrot.memory.persistence import BusTurnPublisher, TURN_COMPLETED_TOPIC                                    # TASK-5569
from parrot.storage.errors import ConversationDeletedError, StorageWriteError                                   # TASK-5570
from parrot.storage.hydration import ChatStorageHydrationSource                                                 # TASK-5582
from parrot.storage.turn_bus import setup_turn_persistence, shutdown_turn_persistence                           # TASK-5581
```
Environment note: the repo `.venv` ships `navigator_eventbus 0.3.0` (no `transport=`, no `outbox=`); the
declared pin is `>=0.4.0` (`packages/ai-parrot/pyproject.toml:201`). The module must skip itself when
`"transport" not in inspect.signature(EventBus.__init__).parameters`. No `fakeredis` and no `moto` are
installed; this suite needs neither.

### Existing Signatures to Use
```python
# P/storage/backends/sqlite.py:35
class ConversationSQLiteBackend(ConversationBackend):  def __init__(self, path, default_ttl_days=180)  # + await initialize()
# P/storage/chat.py
class ChatStorage:
    def __init__(self, redis_conversation=None, dynamodb=None, document_db=None)   # :28  (injected: no network on initialize())
    async def load_conversation(self, user_id, session_id, agent_id=None, limit=50) -> List[Dict]   # :281
    async def delete_conversation(self, user_id, session_id, agent_id=None) -> bool                  # :533
    async def delete_turn(self, session_id, turn_id, user_id=None, agent_id=None) -> bool            # :578
    # created by TASK-5579: store_turn(ChatStorageTurn), handle_turn_completed(envelope),
    #                       handle_conversation_deleted(envelope), register_memory_cleaner(cleaner)
# P/storage/backends/base.py:15  ConversationBackend: put_turn, query_turns(user_id, agent_id, session_id, limit=10, newest_first=True), delete_turn
#   created by TASK-5570: query_turn_window(user_id, agent_id, session_id, limit), is_deleted(...), put_tombstone(...), get_index_state(...)
# P/bots/abstract.py:2685  save_conversation_turn (TASK-5583 adds presentation=; sets timestamp/sequence; publishes)
# P/bots/base.py  BaseBot.ask / ask_stream / conversation / invoke  (TASK-5583: turn_id kwarg honored)
# tests/unit/bots/test_bot_history_wiring.py:24  RecordingClient(AbstractClient) — the offline client pattern to copy
# navigator_eventbus 0.4.0 (spec §6): EventBus(transport="memory", **bus_options) -> BusCore(retry_attempts=3, retry_base_delay=0.1,
#   on_dlq=callable(envelope, *, attempts, error, subscriber_id), ...);  EventEnvelope(topic, payload, event_id, ...)
```

### Does NOT Exist
- ~~`fakeredis` / `moto` in this environment~~ — the Redis hot tier is an in-file double; there is no
  Redis Streams transport in `transport="memory"`, so the Streams-specific path and outbox durability are
  covered only by the optional skipped-without-Redis test.
- ~~`ChatStorage.save_turn`~~ — removed (hard cut, TASK-5579); never call it in this suite.
- ~~A public `replay` helper that works with an injected memory bus and no Postgres DSN~~ — `replay_dead_letters`
  reads "whichever store holds them" (spec Q15); with an injected test bus the dead letter is captured by the
  `on_dlq` callback, so the suite replays the captured envelope through `chat_storage.handle_turn_completed`
  (the exact handler replay uses).
- ~~Mocks standing in for the framework request/session plumbing~~ — nothing here touches aiohttp requests.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/integration/test_durable_conversation_memory.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage",
    "sym:packages/ai-parrot/src/parrot/storage/backends/sqlite.py#ConversationSQLiteBackend",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- `tests/unit/bots/test_bot_history_wiring.py` — `RecordingClient`, `_make_bot`. Copy the client, do not import
  from another test module.
- `asyncio_mode = auto` is configured (root `pytest.ini` and `packages/ai-parrot/pyproject.toml`): plain
  `async def test_*`, async fixtures via `pytest_asyncio.fixture` or plain `@pytest.fixture` on `async def`.

### Key Constraints
- Real objects at every boundary (ARCHITECTURE.md Rule 6): a real `BaseBot`, bus, SQLite backend,
  `ChatStorage`, hydration source. The only doubles are (a) the offline LLM client, (b) the hot-tier
  `_HotTier` (Redis stand-in) and (c) a gate / flaky wrapper that is a REAL subclass of the real backend or a
  wrapper around the real handler — never a `MagicMock`.
- Deterministic waits: poll storage state with `_eventually(predicate, timeout=5.0)`; never `sleep()` for a
  fixed time and never assert on elapsed time.
- Mutation proof (see Acceptance Criteria): each scenario must go RED when the production behavior it guards
  is reverted. Do the mutations on a scratch copy of the worktree, restore with a plain edit — NEVER with
  `git checkout` (project rule: mutation restore by edit, not checkout).
- Tests write only to `tmp_path`.

### References in Codebase
- `packages/ai-parrot/tests/test_chat_storage.py` — existing ChatStorage unit tests (mock-based; this suite replaces mocks with real objects)
- `packages/ai-parrot/tests/unit/memory/test_redis_history_ttl.py` — `TEST_REDIS_URL` skip pattern

---

## Implementation Blueprint

### Steps (in order)
1. Verify TASK-5584 is `done`; run `python -c "import parrot.storage.turn_bus, parrot.storage.hydration, parrot.memory.hydration, parrot.memory.persistence"` — *why*: the suite imports four modules that do not exist until the dependency chain lands.
2. Write the module header (skip guard) and the harness block — *why*: every scenario reuses it.
3. Write the nine scenarios in spec order — *why*: names are fixed by spec §4.
4. Write the optional outbox test (skipped without `TEST_REDIS_URL`).
5. Mutation-check each scenario, then run the Validation Commands.

### `packages/ai-parrot/tests/integration/test_durable_conversation_memory.py` (CREATE) — header + harness
```python
"""FEAT-886 integration suite: bot -> bus -> ChatStorage -> hydration (spec §4)."""
from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List

import pytest
from navigator_eventbus import EventBus

from parrot.bots.base import BaseBot
from parrot.memory import ConversationTurn, InMemoryConversation
from parrot.memory.hydration import LocalSequenceAllocator, SessionDeletedError, HydrationUnavailableError
from parrot.storage import ChatStorage
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.errors import ConversationDeletedError, StorageWriteError
from parrot.storage.hydration import ChatStorageHydrationSource
from parrot.storage.turn_bus import setup_turn_persistence, shutdown_turn_persistence

pytestmark = pytest.mark.skipif(
    "transport" not in inspect.signature(EventBus.__init__).parameters,
    reason="navigator-eventbus >= 0.4.0 required (EventBus(transport='memory'))",
)
USER, SESSION, AGENT = "u1", "s1", "alpha"


class _HotTier(InMemoryConversation):
    """Stand-in for the Redis hot tier — the one external service that cannot run here."""

    async def upsert_turn(self, user_id, session_id, turn, chatbot_id=None):
        # FILL IN: replace the stored turn with the same turn_id, else append (create the history when absent),
        #          reusing InMemoryConversation get/create/update_history — bounded by spec §3 M9 `upsert_turn`.
        ...


async def _eventually(predicate: Callable[[], Awaitable[bool]], timeout: float = 5.0) -> None:
    """Poll `predicate` until true or fail — deterministic wait on real async state."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not await predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached"
        await asyncio.sleep(0.01)


@dataclass
class Stack:
    backend: ConversationSQLiteBackend
    storage: ChatStorage
    bus: Any
    handle: Any
    dead_letters: List[Any]
    make_bot: Callable[..., Awaitable[BaseBot]]

    async def stored_turns(self, agent_id: str = AGENT) -> List[dict]:
        return await self.backend.query_turns(USER, agent_id, SESSION, limit=50, newest_first=False)


@pytest.fixture
async def stack(tmp_path):
    backend = ConversationSQLiteBackend(path=str(tmp_path / "conv.db"))
    await backend.initialize()
    storage = ChatStorage(redis_conversation=_HotTier(), dynamodb=backend)
    dead: List[Any] = []

    async def _on_dlq(envelope, *, attempts, error, subscriber_id):
        dead.append((envelope, attempts, error))

    bus = EventBus(transport="memory", on_dlq=_on_dlq, retry_attempts=3, retry_base_delay=0.0)
    handle = await setup_turn_persistence(storage, bus=bus)
    allocator = LocalSequenceAllocator()  # shared across "workers" like the Redis allocator would be

    async def make_bot(*, name=AGENT, chatbot_id="uuid-alpha", memory=None, client=None, **kw) -> BaseBot:
        bot = BaseBot(name=name, chatbot_id=chatbot_id, llm=client or RecordingClient(), memory_type="memory",
                      injection_detection=False, turn_publisher=handle.publisher,
                      hydration_source=ChatStorageHydrationSource(backend), sequence_allocator=allocator, **kw)
        await bot.configure()
        bot.conversation_memory = memory or InMemoryConversation()
        return bot

    yield Stack(backend, storage, bus, handle, dead, make_bot)
    await shutdown_turn_persistence(handle)
    await storage.close()


# RecordingClient: copy from tests/unit/bots/test_bot_history_wiring.py and extend its AIMessage with
#   tool_calls=[ToolCall(id="t1", name="lookup", arguments={"q": "x"}, result="42", execution_time=0.5)],
#   usage=CompletionUsage(prompt_tokens=3, completion_tokens=5, estimated_cost=0.42), model="stub", provider="stub".
#   Its ask_stream must be able to yield some chunks and then raise (flag `fail_after`).
```
**Why this shape**: one `Stack` per test (tmp SQLite file, fresh bus) keeps scenarios independent. The bot
factory injects the three collaborators exactly like `BotManager._attach_durable_memory` does (TASK-5584), so
the suite exercises the production wiring contract without needing aiohttp. `retry_base_delay=0.0` keeps the
retry scenario fast; the attempt count stays at the spec's 3.

### Scenario blocks (same file) — one block per spec test, each FILL IN
```python
async def test_turn_round_trip_bus_to_storage(stack):
    """bot round -> publisher -> bus -> ChatStorage; the stored turn has tool results, usage and tenant."""
    bot = await stack.make_bot()
    await bot.ask("hello", user_id=USER, session_id=SESSION, tenant="acme", use_vector_context=False)
    await _eventually(lambda: _has_turns(stack, 1))
    # FILL IN: row = (await stack.stored_turns())[0]; assert row["tool_invocations"][0]["output"] == "42" (and name, elapsed),
    #          row["presentation"]["usage"]["total_tokens"] == 8, ["tenant"] == "acme", ["model"]/["provider"],
    #          row["schema_version"] == 2, row["chatbot_id"] == "uuid-alpha", agent key == "alpha"
    #          (NOT memory_key_id) — spec §5 "Rich turns" and "Key alignment". Bounded by AC-Rich-turns.


async def test_retry_then_dlq(stack):
    """failing backend: three attempts, then the envelope is in the DLQ; replay stores exactly one turn."""
    # FILL IN: wrap the real backend: `flaky = _FlakyBackend(stack.backend, fail=True)` (a real subclass/delegate whose
    #          put_turn raises StorageWriteError and counts calls) injected as storage._dynamo BEFORE the round;
    #          ask once; _eventually(len(stack.dead_letters) == 1); flaky.put_calls == 3 (retry_attempts);
    #          flaky.fail = False; await stack.storage.handle_turn_completed(envelope) twice (replay + duplicate)
    #          -> exactly one turn per tier. Bounded by spec §5 "Failure propagation and retries".


async def test_hydrate_after_restart(stack):
    """a new bot instance with empty working memory continues with the newest budget window."""
    # FILL IN: bot A, max_context_turns=2: three asks; wait for 3 stored turns; bot B = make_bot(memory=InMemoryConversation(),
    #          max_context_turns=2, client=<fresh RecordingClient>); B.ask("again") -> B's client call carries history= with the
    #          newest 2 prior turns ascending (not the oldest), and B.memory history now holds those 2 + the new turn.


async def test_hydration_race_two_workers(stack):
    """two concurrent first requests, one installed history."""
    # FILL IN: shared InMemoryConversation `mem` wrapped by a spy subclass counting install_history -> True results;
    #          two bots (same name, same mem) asked concurrently with asyncio.gather on a session that already has stored
    #          turns; exactly one install returns True; both rounds see the hydrated turns; final history has
    #          hydrated + 2 turns, no duplicates. Bounded by spec §5 "Hydration once".


async def test_delete_during_delayed_write(stack):
    """pause the subscriber, delete the session, resume, replay the DLQ: nothing becomes visible or hydrates."""
    # FILL IN: before setup, the gate wraps storage.handle_turn_completed (patch the instance attribute, then re-run
    #          setup_turn_persistence with the same bus on a fresh Stack variant, or build the gate into `stack` via a
    #          fixture parameter); round -> handler held at the gate; await storage.delete_conversation(USER, SESSION,
    #          agent_id=AGENT); release; _eventually(handler finished); assert: backend.query_turns raises
    #          ConversationDeletedError (or returns []), storage.load_conversation(...) == [], hot tier empty,
    #          ChatStorageHydrationSource.load_turns raises SessionDeletedError; then replay the captured envelope again
    #          -> still nothing. Bounded by spec §5 "Deletion races".


async def test_delete_during_hydration_install(stack):
    """the post-install guard recheck rejects the session."""
    # FILL IN: seed two stored turns via the bus; a real ChatStorageHydrationSource SUBCLASS whose is_deleted returns
    #          False the first time and True afterwards (flip after load_turns); bot B.ask raises SessionDeletedError and
    #          B.conversation_memory.get_history(USER, SESSION, chatbot_id="uuid-alpha") is None.


async def test_deleted_turn_stays_deleted(stack):
    """a delayed upsert cannot undo a turn deletion."""
    # FILL IN: round -> stored; capture the envelope (subscribe a recorder to TURN_COMPLETED_TOPIC on stack.bus or reuse the
    #          dead-letter capture); await storage.delete_turn(SESSION, turn_id, user_id=USER, agent_id=AGENT);
    #          replay the envelope via handle_turn_completed -> returns without raising (terminal ack), turn absent in both
    #          tiers; the sibling turn of the same session is untouched.


async def test_guard_unavailable_fails_closed(stack):
    """no stale history is served and no session is initialized."""
    # FILL IN: HydrationSource subclass whose is_deleted raises HydrationUnavailableError; bot with a pre-existing history
    #          in working memory; ask raises HydrationUnavailableError; client.calls == [] (LLM never reached); no NEW
    #          session initialized for an unseen session id.


async def test_stream_disconnect_stores_partial_turn(stack):
    """a mid-stream disconnect stores a partial turn with error state (spec §4, §7 "Streaming and cancellation")."""
    # FILL IN: two cases. (1) Caller disconnect — the spec's meaning: consume one chunk of bot.ask_stream, then
    #          cancel the consuming task / aclose() the generator; ChatStorage holds a turn with the partial text and
    #          an error state; the next ask() on the same session proceeds cleanly. (2) LLM stream failure:
    #          RecordingClient(fail_after=1) yields "par" then raises RuntimeError("boom"); the stored turn has
    #          assistant_response == "par" and error containing "boom".


@pytest.mark.skipif(not __import__("os").environ.get("TEST_REDIS_URL"), reason="needs a real Redis Streams + outbox")
async def test_outbox_survives_process_restart():
    """spec §5 'Outbox durability' (not one of the nine §4 tests): published, 'killed', delivered after restart."""
    # FILL IN: build a streams bus with SqliteOutbox in tmp_path and the bus relay stopped; publish one turn; drop the bus
    #          without close(); build a second bus on the same outbox path; the turn reaches ChatStorage exactly once.
```
**Why this shape**: nine named functions map 1:1 to spec §4, each asserting a join, not a unit. The optional
tenth carries the §5 criterion the nine do not cover, and is skipped everywhere Redis is absent.

### FILL IN checklist
- [ ] `_HotTier.upsert_turn` — replace-by-turn_id; bounded by spec §3 M9
- [ ] `RecordingClient` — copy + tool_calls/usage/fail_after; bounded by `test_bot_history_wiring.py` pattern
- [ ] `test_retry_then_dlq` — attempt counting wrapper + envelope capture; bounded by spec §5 retry/DLQ
- [ ] `test_delete_during_delayed_write` — a gate that pauses the real handler; bounded by spec §5 "Deletion races"
- [ ] each scenario — a `_has_turns(stack, n)` helper built on `stack.stored_turns()`

---

## Acceptance Criteria

- [ ] The nine scenarios of spec §4 pass: `test_turn_round_trip_bus_to_storage`, `test_retry_then_dlq`, `test_hydrate_after_restart`, `test_hydration_race_two_workers`, `test_delete_during_delayed_write`, `test_delete_during_hydration_install`, `test_deleted_turn_stays_deleted`, `test_guard_unavailable_fails_closed`, `test_stream_disconnect_stores_partial_turn`.
- [ ] Spec §5 criteria exercised here: "Rich turns", "Key alignment", "Hydration once", "Failure propagation and retries", "Deletion races", "AgentTalk mismatch fixed" (working memory seen by the second round of one bot).
- [ ] Skips cleanly (one visible skip reason) on `navigator-eventbus < 0.4.0`; no test needs Redis or moto except the optional outbox test.
- [ ] Mutation check A: make `ChatStorage.handle_turn_completed` swallow `StorageWriteError` -> `test_retry_then_dlq` goes RED.
- [ ] Mutation check B: skip the post-install `is_deleted` recheck in `AbstractBot._hydrate_history` -> `test_delete_during_hydration_install` goes RED.
- [ ] Mutation check C: make `put_turn` ignore the tombstone -> `test_delete_during_delayed_write` and `test_deleted_turn_stays_deleted` go RED.
- [ ] Mutation check D: make `install_history` unconditional (no NX) -> `test_hydration_race_two_workers` goes RED.
- [ ] Mutation check E: make `_assert_session_active` return on a guard exception -> `test_guard_unavailable_fails_closed` goes RED.
- [ ] Each mutation is applied and restored by editing (never `git checkout`), and the RED output is recorded in the Completion Note.
- [ ] `ruff check packages/ai-parrot/tests/integration/test_durable_conversation_memory.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/integration/test_durable_conversation_memory.py -q`

---

## Test Specification

The file IS the test specification; the harness and the nine scenario signatures are fixed above. Spec §4
"Test Data / Fixtures" items used here, written inside this file: `memory_bus` (the `EventBus(transport="memory")`
built inside `stack`), `failing_backend` (`_FlakyBackend`, a delegate over the real SQLite backend whose
`put_turn` fails N times then succeeds), and ordinary rows produced by real bot rounds instead of the
`legacy_rows` fixture (legacy rows belong to the backfill tests).

```python
# the two small in-file helpers the scenarios share
async def _has_turns(stack: "Stack", n: int) -> bool:
    return len(await stack.stored_turns()) >= n


class _FlakyBackend:
    """Delegates to the real backend; put_turn raises StorageWriteError while `fail` is set and counts attempts."""

    def __init__(self, inner, fail: bool = True) -> None:
        self._inner, self.fail, self.put_calls = inner, fail, 0

    async def put_turn(self, *a, **kw):
        self.put_calls += 1
        if self.fail:
            raise StorageWriteError("injected")
        return await self._inner.put_turn(*a, **kw)

    def __getattr__(self, name):  # every other operation hits the real backend
        return getattr(self._inner, name)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** (§4 Integration Tests, §5 Acceptance Criteria, Rule 6 in `ARCHITECTURE.md`)
3. **Check dependencies** — TASK-5584 (and transitively the whole chain) must be `"done"` in
   `sdd/tasks/index/durable-conversation-memory.json`
4. **Verify the Codebase Contract** — every created-by-dependency symbol must import; update the contract FIRST if a name moved
5. **Update status** in the per-spec index -> `"in-progress"`
6. **Implement** the file from the Blueprint; complete every `# FILL IN:`
7. **Verify** the acceptance criteria, including the five mutation checks
8. **Commit the code** — stage only the file this task lists
9. **Close the task** with `parrot sdd task close TASK-5585 durable-conversation-memory verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Created tests/integration/test_durable_conversation_memory.py: the nine spec §4 scenarios (+ an extra "second round sees the first" test) on a real BaseBot -> BusTurnPublisher -> EventBus(transport="memory") -> ChatStorage -> real SQLite -> ChatStorageHydrationSource stack.

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-11-13
**STATUS: done-with-issues** (see the two items below).
**Tests**: 10 passed (navigator-eventbus 0.4.1). ruff clean.
**Mutation evidence**: A (swallow StorageWriteError in handle_turn_completed) -> RED; B (no post-install guard recheck) -> RED; D (install_history not NX) -> RED; E (guard fails open on an unknown exception) -> RED only after adding a RuntimeError-raising guard to test_guard_unavailable_fails_closed (the first version only raised HydrationUnavailableError, which takes the `except HydrationError: raise` branch).
**Issue 1 — mutation C survives**: making SQLite `put_turn` ignore the tombstone does NOT turn test_delete_during_delayed_write / test_deleted_turn_stays_deleted RED, because ChatStorage._fence_after_write (a second, independent defense) re-checks the tombstones after the write and removes the resurrected copies. The backend guard itself is pinned by the backend contract suite (test_sqlite_durable_contract: removing the guard -> 3 RED). Net: the end-to-end behavior is protected twice; the integration test cannot isolate the first layer.
**Issue 2 — the optional spec §5 outbox-durability test (`test_outbox_survives_process_restart`) was NOT written**: it needs a real Redis Streams bus + SqliteOutbox restart; no Redis server is reachable from the test sandbox as a service. Outbox crash recovery is therefore untested in this feature.

**Deviations from spec**: the optional tenth test was not implemented (above)
