---
type: feature
base_branch: dev
feature_id: FEAT-895
projects: [ai-parrot]
tags: [bots, memory, ledger-fix, durability]
discovered_from: issue:8f65307982dd
docs:
  policy: required
  pages: [wiki/memory/durable-conversation-memory.md, wiki/memory/conversation-history-ownership.md]
  api_modules: []
---

# Feature Specification: Turn save — outbox first, one save at a time per session

**Feature ID**: FEAT-895
**Date**: 2026-11-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger `issue:8f65307982dd` (minor tech debt, discovered from `spec:FEAT-886`, listed under "Known limitations" in
PR #2121): `AbstractBot._persist_turn_unit` (`abstract.py:2844`) shields the save + publish of a turn from
cancellation, but

1. **no transaction spans the working-memory write and the outbox append.** `save_conversation_turn`
   (`abstract.py:2874`) writes working memory first (`conversation_memory.add_turn`, `:2933`) and publishes
   afterwards (`:2936–2937`). `_publish_turn_completed` (`:3157`) swallows every publisher error ("a lost audit
   event must not fail the round", `:3181`). When the `SqliteOutbox` rejects the append (overflow, unwritable
   file), the bot's working memory keeps a turn that the durable tier never receives. The turn disappears when the
   working-memory key expires.
2. **two quick requests on one session are not serialized.** Two concurrent saves on one
   `(memory_key_id, user_id, session_id)` interleave their order stamp (`_stamp_turn_ordering`, `:3132`), their
   working-memory write and their publish. The order of working-memory writes and the order of bus envelopes can
   then disagree with the allocated `sequence`. The compaction `stage2_needed` read-before-write (`:2928–2931`) can
   also fire twice or not at all.

FEAT-886's bus subscriber does **not** repair the bot's working memory. `ChatStorage.store_turn`
(`storage/chat.py:165`) upserts its own hot tier: a `RedisConversation(key_prefix="chat")` (`chat.py:76–77`) keyed
by the agent **name**. The bot's working memory uses `key_prefix="conversation"` (`memory/redis.py:104`) keyed by
`memory_key_id`. The two writes in `save_conversation_turn` are the only writes to the bot's working memory.

### Goals
- **Outbox first.** The durable tier is the source of truth. `save_conversation_turn` appends to the outbox
  (`turn_publisher.publish`) **before** it writes working memory. A rejected append raises before working memory
  is touched, so it fails the save and the request (no turn in either tier).
- **Working-memory failure after a successful append.** The save still raises. When `self.hydration_source` is
  configured, the session's working memory is invalidated (`conversation_memory.delete_history`, best effort, its
  own failure logged and swallowed), so the next request rehydrates it from the durable tier. Without a hydration
  source, working memory is left as it is: deleting it would drop the session's context with nothing to restore it.
- **One save at a time per session.** An in-process `asyncio.Lock`, keyed by
  `(memory_key_id, str(user_id), str(session_id))` and shared by every bot instance of the process, serializes the
  order stamp, the stage-2 read, the outbox append and the working-memory write of one session. Answers are still
  generated concurrently; only the save step waits. Different sessions never wait for each other.
- The lock registry holds an entry only while a save of that session is running or waiting. It never grows with
  the number of sessions served.
- `MessageAddedEvent` and `Stage2CompactionNeededEvent` are emitted after the lock is released, with today's
  conditions.

### Non-Goals (explicitly out of scope)
- Cross-pod serialization (a distributed lock). Across pods, ordering keeps relying on the shared sequence
  allocator and the `(timestamp, sequence, turn_id)` order of every reader.
- Serializing whole requests (history load → LLM call → save).
- A real two-store transaction or a compensating removal of a working-memory turn.
- Outbox recovery for a dead pod's `<hostname>-<pid>.db` (a separate PR #2121 limitation).
- `issue:a20713dc67a6` (OUTPUT wrapper scan), fixed by FEAT-894 in the same file.
- `voice.py` (`:687`, `:727`) keeps calling `save_conversation_turn` directly. It gets the new order and the lock
  through that method, with no change to `voice.py`.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:9915286019353338d44cec5868a02ecce1af5360fd155262d022d90d5b90d3ee evaluation_digest=sha256:8f58515669f4919049d4ed18e0b97cc64f38032fb2a839b4cba2db387dd10356 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Three changes in `packages/ai-parrot/src/parrot/bots/abstract.py`, plus tests and two wiki pages:

1. **`_TurnSaveLocks`** — a small module-level class next to `_FALLBACK_FLOOR_CACHE_MAX` (`:242`), with one
   instance `_TURN_SAVE_LOCKS`. `hold(key)` is an async context manager: get-or-create `[asyncio.Lock(), holders]`,
   increment `holders`, `async with lock`, and in `finally` decrement and delete the entry at zero (only if the
   stored entry is still the same object). A waiter cancelled while queued still runs `finally`, so the count
   stays exact. No await happens between the dict lookup and the increment, so the registry needs no lock of its
   own on one event loop.
2. **`save_conversation_turn`** — the order stamp, the raw snapshot, the stage-2 read, the outbox append and the
   working-memory write run inside `async with _TURN_SAVE_LOCKS.hold(self._turn_save_key(user_id, session_id))`.
   Inside, the publish moves **before** `add_turn`. A failing `add_turn` after an append invalidates working
   memory (only with a hydration source) and re-raises. The event emission stays after the block.
3. **`_save_or_snapshot_turn`** — the history-disabled branch (`_snapshot_turn` + publish) runs under the same
   lock. The history branch already gets it from `save_conversation_turn`. The lock is taken in exactly these two
   places, never in a caller of either, so no path acquires it twice (asyncio locks are not reentrant).
4. **`_publish_turn_completed`** — raises what building the event or `publisher.publish` raises. The ERROR log
   and the `except` are removed; the caller logs (`_persist_turn_unit._log_failure`, `voice.py`'s handler). Still a
   no-op when there is no publisher or no snapshot.

`_persist_turn_unit` keeps the `ensure_future` + `asyncio.shield` unit: the lock is acquired **inside** the
shielded task, so a caller cancelled while its save waits for the lock does not cancel the save.

### Component Diagram
```
entry point ─► _persist_finalized_turn ─► _persist_turn_unit (shielded task)
                                              └─ _save_or_snapshot_turn
                                                    ├─ history on : save_conversation_turn
                                                    │     └─ hold(memory_key_id, user, session)
                                                    │          stamp → snapshot → stage2 read
                                                    │          → publish (outbox)   ← raises on reject
                                                    │          → add_turn            ← on failure: invalidate (hydration only), re-raise
                                                    │     events (MessageAdded, Stage2) after release
                                                    └─ history off: hold(...) → stamp → snapshot → publish
voice.py ─► save_conversation_turn (same path)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot.save_conversation_turn` | modifies | lock, publish before `add_turn`, invalidation, `abstract.py:2874` |
| `AbstractBot._save_or_snapshot_turn` | modifies | history-disabled branch under the lock, `abstract.py:2771` |
| `AbstractBot._publish_turn_completed` | modifies | raises instead of logging, `abstract.py:3157` |
| `AbstractBot._persist_turn_unit` / `_persist_finalized_turn` | docstring only | `abstract.py:2844`, `:2796` |
| `BaseBot.ask_stream` partial save | consumer, unchanged | `base.py:2217` |
| `VoiceBot` turn saves | consumer, unchanged | `voice.py:687`, `:727` |
| `ChatStorage.store_turn` | unchanged | writes its own `chat:` hot tier, not the bot's working memory |

### Data Models
None.

### New Public Interfaces
None. `_TurnSaveLocks`, `_TURN_SAVE_LOCKS` and `AbstractBot._turn_save_key` are private.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Ordered, serialized turn save | no | — | the save path's failure ordering is judgement-heavy |
| M2: Documentation | no | — | prose edits to two pages |

### Module 1: Ordered, serialized turn save
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`,
  `packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py`
- **Responsibility**: outbox-first save, best-effort invalidation, per-session lock, raising publish.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # abstract.py — module level, after `_FALLBACK_FLOOR_CACHE_MAX = 10_000` (:242)
  class _TurnSaveLocks:
      """Per-session save locks shared by every bot of this process; an entry lives only while it is held or awaited."""

      def __init__(self) -> None:
          self._entries: Dict[Tuple[str, str, str], List[Any]] = {}  # key -> [asyncio.Lock, holders]

      @asynccontextmanager
      async def hold(self, key: Tuple[str, str, str]) -> AsyncIterator[None]:
          ...

  _TURN_SAVE_LOCKS = _TurnSaveLocks()

  # AbstractBot
  def _turn_save_key(self, user_id: Optional[str], session_id: Optional[str]) -> Tuple[str, str, str]:
      return (self.memory_key_id, str(user_id), str(session_id))

  async def _invalidate_working_memory(self, user_id: str, session_id: str) -> None:
      """Drop the session's working memory so the next request rehydrates it (only with a hydration source)."""
  ```

### Module 2: Documentation
- **Path**: `wiki/memory/durable-conversation-memory.md`, `wiki/memory/conversation-history-ownership.md`,
  `packages/ai-parrot/tests/docs/test_durable_memory_docs.py`
- **Responsibility**: the pages state the new order and failure rules; a content test pins them.
- **Depends on**: M1 (documents its behaviour).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_publish_before_add_turn` | M1 | replaces `test_publish_after_add_turn`: the recording publisher sees working memory WITHOUT the turn; after the round the turn is stored |
| `test_rejected_outbox_append_fails_the_round_and_leaves_memory_untouched` | M1 | replaces `test_publish_failure_does_not_fail_round`: a publisher raising `RuntimeError("outbox full")` → `ask` raises it, working memory holds no turn |
| `test_working_memory_failure_after_the_append_invalidates_a_hydrated_session` | M1 | `add_turn` raises, a hydration source is set → the save raises, the publisher holds the event, `get_history` returns `None` |
| `test_working_memory_failure_without_a_hydration_source_keeps_the_history` | M1 | same failure, no hydration source → the save raises, the earlier turn is still in working memory |
| `test_same_session_saves_are_serialized` | M1 | two concurrent `save_conversation_turn` on one session, the publisher sleeps → events `publish:a, store:a, publish:b, store:b`; sequences ascend in that order |
| `test_bots_sharing_a_memory_key_serialize_their_saves` | M1 | two bot instances with the same `memory_key_id`, memory and publisher → same total order as above |
| `test_different_sessions_do_not_wait_for_each_other` | M1 | two sessions → both publishes happen before either store |
| `test_history_disabled_publication_is_serialized` | M1 | `_save_or_snapshot_turn(use_history=False)` twice concurrently on one session → publishes do not overlap |
| `test_save_lock_registry_releases_idle_and_cancelled_entries` | M1 | after the saves, and after a waiter is cancelled while queued, `_TURN_SAVE_LOCKS._entries` is empty |
| `test_turn_save_order_is_documented` | M2 | the main page says the outbox append precedes the working-memory write and that a rejected append fails the round; neither page says the turn is published after `add_turn` or that a publish failure never fails the round |
| existing tests in the contract files | M1 | unchanged; prove cancellation shielding, snapshot rawness, ordering stamps, `memory_key_id` attribution, the once-only stage-2 event and the FEAT-886 integration flow hold (the last three call `save_conversation_turn` directly; spec gate blast radius) |

### Integration Tests
| Test | Description |
|---|---|
| `tests/integration/test_durable_conversation_memory.py` | unchanged; the bot → outbox → subscriber → storage round trip still holds with the new order |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py
- packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py
- packages/ai-parrot/tests/unit/bots/test_memory_key_id.py
- packages/ai-parrot/tests/unit/bots/test_context_budget.py
- packages/ai-parrot/tests/integration/test_durable_conversation_memory.py
- packages/ai-parrot/tests/docs/test_durable_memory_docs.py
markers: none

### Test Data / Fixtures

The new tests reuse `Client`, `RecordingPublisher`, `_bot` and `_round` from `test_turn_publish_after_save.py`.
The ordering tests use a local publisher that appends `"publish:<turn_id>"` to a shared list and awaits
`asyncio.sleep(0.05)`, and wrap `conversation_memory.add_turn` to append `"store:<turn_id>"`. The hydration tests
set `bot.hydration_source` to a local `HydrationSource` subclass (its three abstract methods return `[]`, `False`
and `0`).

---

## 5. Acceptance Criteria

- [ ] A rejected outbox append fails the save with nothing written to working memory.
- [ ] A working-memory failure after a successful append re-raises, and invalidates the session's working memory
      only when a hydration source is configured.
- [ ] Concurrent saves of one session run one at a time in this process (shared across bot instances with one
      `memory_key_id`); saves of different sessions do not wait for each other.
- [ ] The lock registry is empty when no save is running or waiting.
- [ ] The new tests fail on `origin/dev` without the fix (mutation check) and pass with it.
- [ ] The six Validation Contract files pass from the worktree with `PYTHONPATH=packages/ai-parrot/src`.
- [ ] `parrot sdd techwiki check --spec sdd/specs/bots-abstract-tech-debt-2.spec.md --root .` passes.
- [ ] `ruff check` passes on the changed files. `black` (line length 120) leaves the changed lines unchanged.

---

## 6. Codebase Contract

### Verified Imports
```python
# abstract.py already imports everything M1 needs (verified: abstract.py:6,14,16,19)
from typing import Any, ClassVar, Dict, List, Sequence, Tuple, Type, Union, Optional, AsyncIterator, TYPE_CHECKING
from contextlib import asynccontextmanager
import asyncio
import copy
# tests
from parrot.memory import ConversationTurn  # verified: test_turn_publish_after_save.py:104
from parrot.memory.hydration import HydrationSource  # verified: test_turn_publish_after_save.py:191
import parrot.bots.abstract as abstract_mod  # module of _TURN_SAVE_LOCKS (created by M1)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
_FALLBACK_FLOOR_CACHE_MAX = 10_000  # line 242
class AbstractBot:
    hydration_source: Optional[HydrationSource] = None  # line 319
    def memory_key_id(self) -> str  # property, line 2327
    def _publishes_turns(self, user_id: Optional[str], session_id: Optional[str]) -> bool  # line 2754
    async def _snapshot_turn(self, user_id: str, session_id: str, turn: ConversationTurn)
        -> Optional[Dict[str, Any]]  # line 2762 — stamps ordering (:2768), deep-copies the turn
    async def _save_or_snapshot_turn(self, user_id: str, session_id: str, turn: ConversationTurn, *,
        use_history: bool, compaction: Optional[CompactionCommit] = None,
        presentation: Optional[TurnPresentation] = None, publish: bool = True) -> Optional[Dict[str, Any]]  # :2771
    async def _persist_finalized_turn(self, response: AIMessage, *, question: str, user_id, session_id, turn_id,
        use_history: bool, context_used=None, compaction=None, output_mode=None, started=None,
        assistant_text=None) -> Optional[Dict[str, Any]]  # line 2796
    async def _persist_turn_unit(self, user_id, session_id, turn, *, use_history: bool, compaction=None,
        presentation=None) -> Optional[Dict[str, Any]]  # line 2844 — ensure_future + add_done_callback + shield
    async def save_conversation_turn(self, user_id: str, session_id: str, turn: ConversationTurn, *,
        compaction: Optional[CompactionCommit] = None, presentation: Optional[TurnPresentation] = None,
        publish: bool = True) -> Optional[Dict[str, Any]]  # line 2874
        # :2921 stamp; :2923 snapshot; :2926-2931 stage-2 read; :2933 add_turn; :2936-2937 publish;
        # :2938-2960 MessageAddedEvent (try/except); :2962-2976 Stage2CompactionNeededEvent; returns snapshot
    async def _stamp_turn_ordering(self, user_id: str, session_id: str, turn: ConversationTurn) -> None  # :3132
    async def _publish_turn_completed(self, user_id: str, session_id: str, snapshot: Optional[Dict[str, Any]],
        presentation: Optional[TurnPresentation]) -> None  # line 3157 — try/except at :3166-3182

# packages/ai-parrot/src/parrot/memory/abstract.py
class ConversationMemory:
    async def delete_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> bool  # :725

# packages/ai-parrot/src/parrot/memory/hydration.py
class HydrationSource(ABC):  # line 31
    async def load_turns(...)  # :35
    async def is_deleted(self, agent_name: str, user_id: str, session_id: str) -> bool  # :45
    async def max_sequence(self, agent_name: str, user_id: str, session_id: str) -> int  # :49

# packages/ai-parrot/src/parrot/memory/persistence.py
class TurnPublisher(Protocol):  # line 101
    async def publish(self, event: "TurnCompletedEvent") -> None  # "Raises only when the outbox rejects the write."
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_TURN_SAVE_LOCKS.hold` | `save_conversation_turn` | `async with` around stamp → add_turn | `abstract.py:2921–2937` |
| `_TURN_SAVE_LOCKS.hold` | `_save_or_snapshot_turn` | `async with` around the history-disabled branch | `abstract.py:2791–2793` |
| `_invalidate_working_memory` | `ConversationMemory.delete_history` | `chatbot_id=self.memory_key_id` | `memory/abstract.py:725` |

### Does NOT Exist (Anti-Hallucination)
- ~~a per-session lock anywhere in `AbstractBot`~~ — added by this feature.
- ~~`ConversationMemory.invalidate` / `evict`~~ — there is none; use `delete_history`.
- ~~a bus subscriber that writes the bot's working memory~~ — `ChatStorage` writes its own `chat:` hot tier.
- ~~`TurnPublisher.publish_or_log`, a "strict" flag on `_publish_turn_completed`~~ — there is none; the method
  itself now raises.
- ~~an outbox write inside `ConversationMemory.add_turn`~~ — the append is the bot's `turn_publisher.publish`.

### Edit Sites (Blueprint Anchors)

Verified against: `1119ad64b6`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `_FALLBACK_FLOOR_CACHE_MAX = 10_000` | `abstract.py:242` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        snapshot = await self._snapshot_turn(user_id, session_id, turn)` | `abstract.py:2791` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        Save + publish run as one unit shielded from cancellation: a cancelled request cannot leave working` | `abstract.py:2821` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        """Save + publish ``turn`` as one cancellation-shielded unit (see :meth:`_persist_finalized_turn`)."""` | `abstract.py:2854` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        snapshot = copy.deepcopy(turn.to_dict()) if self.turn_publisher is not None else None` | `abstract.py:2923` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        await self.conversation_memory.add_turn(` | `abstract.py:2933` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        # FEAT-176: emit MessageAddedEvent after persisting to memory.` | `abstract.py:2938` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        """Publish ``TurnCompletedEvent`` for the raw ``snapshot``. Never raises (logged at ERROR)."""` | `abstract.py:3164` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        except Exception:  # pylint: disable=broad-except  # a lost audit event must not fail the round` | `abstract.py:3181` | 1 |
| `packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py` | MODIFY | `async def test_publish_after_add_turn():` | `test_turn_publish_after_save.py:89` | 1 |
| `packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py` | MODIFY | `async def test_publish_failure_does_not_fail_round(caplog):` | `test_turn_publish_after_save.py:126` | 1 |
| `wiki/memory/durable-conversation-memory.md` | MODIFY | `        +--> ConversationMemory.add_turn      (awaited)` | `durable-conversation-memory.md:39` | 1 |
| `wiki/memory/durable-conversation-memory.md` | MODIFY | ``After `add_turn` succeeds, `AbstractBot.save_conversation_turn` hands the **raw, pre-normalization** turn, wrapped in a`` | `durable-conversation-memory.md:50` | 1 |
| `wiki/memory/durable-conversation-memory.md` | MODIFY | `never retried. A publish failure inside the bot is logged at ERROR and never fails the round.` | `durable-conversation-memory.md:60` | 1 |
| `wiki/memory/conversation-history-ownership.md` | MODIFY | ``  `ConversationTurn.sequence`, and publishes the raw turn after `add_turn`. `ask`, `ask_stream`, `conversation` `` | `conversation-history-ownership.md:202` | 1 |

`        await self._stamp_turn_ordering(user_id, session_id, turn)` occurs twice (`:2768` in `_snapshot_turn`,
`:2921` in `save_conversation_turn`); anchor on the snapshot line `:2923` instead.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Take the lock only in `save_conversation_turn` and in the history-disabled branch of `_save_or_snapshot_turn`.
  Never in `_persist_turn_unit`, `_persist_finalized_turn` or `_snapshot_turn`: the history branch of
  `_save_or_snapshot_turn` calls `save_conversation_turn`, and an `asyncio.Lock` is not reentrant.
- Keep the snapshot before the publish and before `add_turn` ("Raw, pre-normalization snapshot: MUST precede
  add_turn").
- `black` line length 120, Google-style docstrings, strict type hints.

### Known Risks / Gotchas
- **Behaviour change**: an outbox fault (overflow, unwritable SQLite file) now fails the request. The FEAT-886 wiki
  sentence "A publish failure inside the bot is logged at ERROR and never fails the round" becomes false and is
  rewritten in M2.
- The invalidation after a working-memory failure races the outbox relay. A request that arrives before the
  subscriber stored the turn rehydrates a window without it. This is accepted: without the invalidation, working
  memory lacks the turn until its key expires.
- In a worktree the shared venv imports the main checkout: run pytest with `PYTHONPATH=packages/ai-parrot/src`.
- A lock bound to one event loop must not be reused on another. The registry deletes idle entries, so a lock never
  outlives the saves that use it (pytest-asyncio runs each test on a new loop).
- FEAT-892 (agent-memory-mixin, in progress) cites `abstract.py` line numbers around `_persist_finalized_turn`
  (`:2796`) and `_stored_turn_text` (`:3392`). This feature shifts them; FEAT-892 re-verifies its anchors by symbol.

### External Dependencies
None.

---

## Decisions

```yaml
schema_version: 1
document_id: bots-abstract-tech-debt-2
entries:
  - id: outbox-before-working-memory
    statement: >-
      AbstractBot.save_conversation_turn appends the turn to the outbox before it writes working memory, and a
      rejected append fails the save with working memory untouched.
    relation: constrains
    about: [bots, memory]
    targets:
      - sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn
      - sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._publish_turn_completed
    contradicts: []
    supersedes: []
    rationale: >-
      The durable tier is the source of truth and the bus subscriber does not write the bot's working memory, so
      a turn kept only in working memory is lost when the key expires.
    rejected_alternatives:
      - working memory first, then remove the turn when the outbox rejects
      - working memory first, mark the turn unpublished and republish it on the next save
  - id: per-session-save-lock
    statement: >-
      Turn saves of one (memory_key_id, user_id, session_id) run one at a time in a process, under an in-process
      lock shared by every bot instance; whole requests and other pods are not serialized.
    relation: constrains
    about: [bots, memory]
    targets:
      - sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn
      - sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn
    contradicts: []
    supersedes: []
    rationale: >-
      Serializing only the save keeps answers concurrent while making the order stamp, the outbox order and the
      working-memory order agree within a pod; cross-pod order already rests on the shared sequence allocator.
    rejected_alternatives:
      - lock the whole request (history load to save)
      - a distributed Redis lock per turn
```

## Consequences

<!-- decision-audit: input_digest=sha256:9915286019353338d44cec5868a02ecce1af5360fd155262d022d90d5b90d3ee evaluation_digest=sha256:8f58515669f4919049d4ed18e0b97cc64f38032fb2a839b4cba2db387dd10356 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:bots-abstract-tech-debt-2#per-session-save-lock@1; scope: sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn; message: sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn impacts 14 dependent(s): sym:packages/ai-parrot-server/tests/studio/test_tenant_matrix.py#test_same_name_agents_shared_memory_backend, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_turn_unit, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.ask_stream, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.ask_voice, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_calibration_pairing_in_save_turn, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_stage2_event_emitted_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_event_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_no_event_on_rejection, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_keys_by_memory_key_id, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_mismatched_attribution, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_unattributed_turn, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_without_memory_is_a_noop, sym:packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py#test_snapshot_is_raw_before_normalization_and_offload
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:bots-abstract-tech-debt-2#outbox-before-working-memory@1; scope: sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn; message: sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn impacts 14 dependent(s): sym:packages/ai-parrot-server/tests/studio/test_tenant_matrix.py#test_same_name_agents_shared_memory_backend, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_turn_unit, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.ask_stream, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.ask_voice, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_calibration_pairing_in_save_turn, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_stage2_event_emitted_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_event_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_no_event_on_rejection, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_keys_by_memory_key_id, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_mismatched_attribution, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_unattributed_turn, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_without_memory_is_a_noop, sym:packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py#test_snapshot_is_raw_before_normalization_and_offload
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:bots-abstract-tech-debt-2#outbox-before-working-memory@1; scope: sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._publish_turn_completed; message: sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._publish_turn_completed impacts 14 dependent(s): sym:packages/ai-parrot-server/tests/studio/test_tenant_matrix.py#test_same_name_agents_shared_memory_backend, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_turn_unit, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.ask_stream, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_calibration_pairing_in_save_turn, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_stage2_event_emitted_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_event_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_no_event_on_rejection, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_keys_by_memory_key_id, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_mismatched_attribution, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_unattributed_turn, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_without_memory_is_a_noop, sym:packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py#test_snapshot_is_raw_before_normalization_and_offload
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:bots-abstract-tech-debt-2#per-session-save-lock@1; scope: sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn; message: sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn impacts 2 dependent(s): sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_finalized_turn, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_turn_unit

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: durability, ledger-fix
- Targets resolved: 3/3
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 3,
    "targets_total": 3,
    "unmapped_tags": [
      "durability",
      "ledger-fix"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:8f58515669f4919049d4ed18e0b97cc64f38032fb2a839b4cba2db387dd10356",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:05ab877b696fba81ea19b1a443821a33b7990a2299e55d7f5d6042d02f73e629",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn impacts 14 dependent(s): sym:packages/ai-parrot-server/tests/studio/test_tenant_matrix.py#test_same_name_agents_shared_memory_backend, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_turn_unit, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.ask_stream, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.ask_voice, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_calibration_pairing_in_save_turn, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_stage2_event_emitted_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_event_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_no_event_on_rejection, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_keys_by_memory_key_id, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_mismatched_attribution, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_unattributed_turn, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_without_memory_is_a_noop, sym:packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py#test_snapshot_is_raw_before_normalization_and_offload",
      "participants": [
        {
          "decision_id": "adr:spec:bots-abstract-tech-debt-2#per-session-save-lock",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:0939fe0df6ebe591892459044c80f8daed5599e2d7006279df919f71e8fbab13",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn impacts 14 dependent(s): sym:packages/ai-parrot-server/tests/studio/test_tenant_matrix.py#test_same_name_agents_shared_memory_backend, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_turn_unit, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.ask_stream, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.ask_voice, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_calibration_pairing_in_save_turn, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_stage2_event_emitted_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_event_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_no_event_on_rejection, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_keys_by_memory_key_id, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_mismatched_attribution, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_unattributed_turn, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_without_memory_is_a_noop, sym:packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py#test_snapshot_is_raw_before_normalization_and_offload",
      "participants": [
        {
          "decision_id": "adr:spec:bots-abstract-tech-debt-2#outbox-before-working-memory",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:35ff431d9dd2e0477eeaca40c09e8e31291714de91ecc098aa22d18618a227aa",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._publish_turn_completed impacts 14 dependent(s): sym:packages/ai-parrot-server/tests/studio/test_tenant_matrix.py#test_same_name_agents_shared_memory_backend, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_turn_unit, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.ask_stream, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_calibration_pairing_in_save_turn, sym:packages/ai-parrot/tests/unit/bots/test_context_budget.py#test_stage2_event_emitted_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_event_once, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_emits_no_event_on_rejection, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_keys_by_memory_key_id, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_mismatched_attribution, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_rejects_unattributed_turn, sym:packages/ai-parrot/tests/unit/bots/test_memory_key_id.py#test_save_conversation_turn_without_memory_is_a_noop, sym:packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py#test_snapshot_is_raw_before_normalization_and_offload",
      "participants": [
        {
          "decision_id": "adr:spec:bots-abstract-tech-debt-2#outbox-before-working-memory",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._publish_turn_completed"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:d4ec64cf10e05dccd8e5864fd2e628f27113c2d846cc011b40ea782762df1951",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn impacts 2 dependent(s): sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_finalized_turn, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_turn_unit",
      "participants": [
        {
          "decision_id": "adr:spec:bots-abstract-tech-debt-2#per-session-save-lock",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:9915286019353338d44cec5868a02ecce1af5360fd155262d022d90d5b90d3ee",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:02d01fccfcc7c4938bbd669507861d7ae153284d02955d1b405cd8611c422e5e",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Q1. Serialize the save only, the whole request, or across pods? — *Resolved by Jesus Lara (2026-11-14, /sdd-fix)*:
  the save step only, with an in-process per-session lock.
- [x] Q2. Which consistency rule between working memory and the outbox? — *Resolved by Jesus Lara (2026-11-14,
  /sdd-fix)*: outbox first; a rejected append fails the save; a later working-memory failure invalidates working
  memory best-effort so the next request rehydrates.
- [x] Q3. Does the bus subscriber repair the bot's working memory, making the invalidation unnecessary? —
  *Resolved (code)*: no. `ChatStorage` writes a separate `chat:` hot tier keyed by agent name. The invalidation is
  kept, limited to bots with a hydration source.
- [x] Q4. Reuse FEAT-886 or FEAT-894? — *Resolved*: neither. FEAT-886 is complete and merged (PR #2121). FEAT-894
  (`bots-abstract-tech-debt`, a parallel `/sdd-fix` run for `issue:a20713dc67a6`) lists this issue as a non-goal;
  this spec takes the planner's slug with the `-2` suffix.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec authored by /sdd-fix from a ledger issue)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required` — the FEAT-886 pages state the old order and the old failure rule.
- **Pages**:
  - `wiki/memory/durable-conversation-memory.md` — update: event-flow diagram and the two paragraphs on publish
    order and publish failure.
  - `wiki/memory/conversation-history-ownership.md` — update: the "Emitter-owned ordering" bullet.
- **API modules**: none.

---

## Worktree Strategy

One feature worktree `feat-FEAT-895-bots-abstract-tech-debt-2` off `origin/dev`.

- Module graph: M2 depends on M1.
- Shared files: none between the two modules.
- Exclusive resources: none.
- Cross-feature: FEAT-894 edits `_run_output_pipeline` / `_propagate_output_verdict` (`abstract.py:3296–3390`) and
  `test_finalize_persist_turn.py`; this feature edits `abstract.py:242` and `:2771–3182` and
  `test_turn_publish_after_save.py`. Separate hunks. FEAT-892 edits `configure` / `cleanup` and the entry-point
  call sites in `base.py` / `data.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-14 | Jesus Lara | Created by /sdd-fix from `issue:8f65307982dd` (fixgroup:fdeb764ab324) |
