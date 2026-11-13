# TASK-5684: Outbox-first turn save under a per-session lock

**Feature**: FEAT-895 — Turn save — outbox first, one save at a time per session
**Spec**: `sdd/specs/bots-abstract-tech-debt-2.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:8f65307982dd`

---

## Context

`save_conversation_turn` writes working memory first and publishes afterwards, and `_publish_turn_completed`
swallows publisher errors. A rejected outbox append therefore leaves a turn in the bot's working memory that the
durable tier never receives; the bus subscriber writes its own `chat:` hot tier, never the bot's working memory.
Two quick saves on one session also interleave their order stamp, outbox append and working-memory write
(spec §1). This task makes the outbox append come first and raise, invalidates working memory best-effort when the
write after a successful append fails (only with a hydration source), and serializes the save of one session
with an in-process lock shared by every bot instance.

---

## Scope

- `abstract.py`, module level: `_TurnSaveLocks` (refcounted per-key `asyncio.Lock` registry) and its instance
  `_TURN_SAVE_LOCKS`, right after `_FALLBACK_FLOOR_CACHE_MAX`.
- `AbstractBot._turn_save_key` and `AbstractBot._invalidate_working_memory` (new private helpers).
- `save_conversation_turn`: lock around stamp → snapshot → stage-2 read → publish → `add_turn`; publish moves
  before `add_turn`; a failing `add_turn` after an append invalidates (hydration only) and re-raises; events stay
  after the lock; docstring.
- `_save_or_snapshot_turn`: the history-disabled branch runs under the same lock; docstring.
- `_publish_turn_completed`: drop the `try/except` and the ERROR log, so errors propagate; docstring.
- `_persist_finalized_turn` / `_persist_turn_unit`: docstrings only.
- `test_turn_publish_after_save.py`: replace `test_publish_after_add_turn` and
  `test_publish_failure_does_not_fail_round`, and add the new M1 tests from spec §4.

**NOT in scope**: `voice.py`, `base.py`, `data.py` (they reach the new behaviour through
`save_conversation_turn` / `_persist_turn_unit`); memory backends (`memory/redis.py` & co.); `ChatStorage`;
a distributed lock; serializing whole requests; the wiki pages (TASK-5685).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | lock registry, two helpers, outbox-first save, raising publish, docstrings |
| `packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py` | MODIFY | two tests replaced, seven added |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# abstract.py already has every import it needs (verified: abstract.py:6,14,16,19 at 098e0b08e3)
from typing import Any, ClassVar, Dict, List, Sequence, Tuple, Type, Union, Optional, AsyncIterator, TYPE_CHECKING
from contextlib import asynccontextmanager
import asyncio
import copy
# test file (existing: test_turn_publish_after_save.py:4,10,15)
import asyncio
import pytest
from parrot.memory import InMemoryConversation
# new imports for the test file
import parrot.bots.abstract as abstract_mod          # holds _TURN_SAVE_LOCKS (created by this task)
from parrot.memory import ConversationTurn          # verified: test_turn_publish_after_save.py:112
from parrot.memory.hydration import HydrationSource  # verified: test_turn_publish_after_save.py:247
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py (lines at 098e0b08e3)
_FALLBACK_FLOOR_CACHE_MAX = 10_000  # :240
class AbstractBot:
    hydration_source: Optional[HydrationSource] = None  # :317
    memory_key_id: str  # property
    async def _snapshot_turn(self, user_id: str, session_id: str, turn: ConversationTurn)
        -> Optional[Dict[str, Any]]  # :2760 — returns None unless a publisher is set; stamps ordering; deepcopy
    async def _save_or_snapshot_turn(self, user_id, session_id, turn, *, use_history: bool, compaction=None,
        presentation=None, publish: bool = True) -> Optional[Dict[str, Any]]  # :2767 — history branch :2783-2786,
        # history-disabled branch :2787-2790
    async def _persist_turn_unit(...)  # :2844 — ensure_future + _log_failure callback + asyncio.shield
    async def save_conversation_turn(self, user_id: str, session_id: str, turn: ConversationTurn, *,
        compaction=None, presentation=None, publish: bool = True) -> Optional[Dict[str, Any]]  # :2876
        # :2913 `if not self.conversation_memory: return`; :2915-2921 chatbot_id check (raises ValueError)
        # :2923 stamp; :2925 snapshot; :2927-2933 stage-2 read; :2935-2937 add_turn; :2938-2939 publish;
        # :2940- MessageAddedEvent (try/except) and Stage2CompactionNeededEvent; returns snapshot
    async def _publish_turn_completed(self, user_id: str, session_id: str, snapshot: Optional[Dict[str, Any]],
        presentation: Optional[TurnPresentation]) -> None  # :3158 — try/except :3168-3183

# packages/ai-parrot/src/parrot/memory/abstract.py
class ConversationMemory:
    async def delete_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> bool  # :725

# packages/ai-parrot/src/parrot/memory/hydration.py
class HydrationSource(ABC):  # :31 — abstract: load_turns(...), is_deleted(agent_name, user_id, session_id) -> bool,
    # max_sequence(agent_name, user_id, session_id) -> int

# packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py
class Client(AbstractClient)  # :21
class RecordingPublisher:  # :59 — __init__(memory, key, fail=False); .events; .memory_at_publish; raises
    # RuntimeError("outbox full") when fail
async def _bot(publisher_factory=None, mode="ok", **kw) -> BaseBot  # :75 — name="alpha", chatbot_id="uuid-1"
async def _round(bot, text="hello", **kw) -> AIMessage  # :85 — bot.ask(text, user_id="u", session_id="s", ...)
```

### Does NOT Exist
- ~~a per-session lock in `AbstractBot`~~ — created by this task.
- ~~`ConversationMemory.invalidate` / `evict`~~ — use `delete_history`.
- ~~a bus subscriber that writes the bot's working memory~~ — `ChatStorage` writes `chat:`-prefixed keys by agent
  name; the bot's working memory is `conversation:`-prefixed by `memory_key_id`.
- ~~a `strict=` parameter on `_publish_turn_completed`~~ — the method itself raises now.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._save_or_snapshot_turn",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._publish_turn_completed",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_turn_unit",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._persist_finalized_turn"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Take the lock ONLY in `save_conversation_turn` and in the history-disabled branch of `_save_or_snapshot_turn` —
  because the history branch calls `save_conversation_turn` and `asyncio.Lock` is not reentrant.
- Keep the snapshot before the publish and before `add_turn` — the published turn must be the raw one.
- Invalidate only when an append happened (`publish` and a snapshot) AND `self.hydration_source` is set — without a
  hydration source nothing restores a dropped history.
- Emit `MessageAddedEvent` / `Stage2CompactionNeededEvent` after the lock is released, with today's conditions.
- `black` line length 120; Google-style docstrings; strict type hints.

### References in Codebase
- `storage/chat.py:76-77` and `memory/redis.py:104` — the two different Redis key prefixes (why the bus does not
  repair the bot's working memory).

---

## Implementation Blueprint

### Steps (in order)
1. Write the new and replaced tests first and run them on the unmodified code: the order, failure and
   serialization tests must FAIL — *why*: a mutation check proves they pin the gap (spec §5).
2. Add `_TurnSaveLocks` / `_TURN_SAVE_LOCKS` and the two helpers — *why*: the save path needs them.
3. Rewrite `save_conversation_turn`'s body between the attribution check and the event emission, then the
   history-disabled branch, then `_publish_turn_completed` — *why*: order, lock and raising publish land together;
   any one alone leaves a failing test.
4. Update the four docstrings.
5. Run the Validation Commands, `ruff check` and `black --check` on both files.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — after `_FALLBACK_FLOOR_CACHE_MAX = 10_000`)
```python
# AFTER — insert below `_FALLBACK_FLOOR_CACHE_MAX = 10_000` (verified: abstract.py:240)
# occurrences: 1 (verified: grep -c '_FALLBACK_FLOOR_CACHE_MAX = 10_000' abstract.py)


class _TurnSaveLocks:
    """Per-session turn-save locks shared by every bot of this process (FEAT-895).

    An entry exists only while a save of its session holds or awaits the lock, so the registry never grows with the
    number of sessions served and a lock never outlives the event loop its saves ran on.
    """

    def __init__(self) -> None:
        self._entries: Dict[Tuple[str, str, str], List[Any]] = {}  # key -> [asyncio.Lock, holders]

    @asynccontextmanager
    async def hold(self, key: Tuple[str, str, str]) -> AsyncIterator[None]:
        """Hold ``key``'s lock for the body. Saves of one key run one at a time; other keys never wait."""
        entry = self._entries.get(key)
        if entry is None:
            entry = self._entries[key] = [asyncio.Lock(), 0]
        entry[1] += 1  # no await between lookup and increment: atomic on one event loop
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0 and self._entries.get(key) is entry:
                del self._entries[key]


_TURN_SAVE_LOCKS = _TurnSaveLocks()
```
**Why**: module level, not per instance — bot clones that share a `memory_key_id` must share the lock. The
`finally` also runs for a waiter cancelled while queued, so the count stays exact.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — helpers + history-disabled branch)
```python
# BEFORE — insert above `    async def _save_or_snapshot_turn(` (verified: abstract.py:2767; occurrences: 1)
    def _turn_save_key(self, user_id: Optional[str], session_id: Optional[str]) -> Tuple[str, str, str]:
        """Key of this session's turn-save lock: ``(memory_key_id, user_id, session_id)`` (FEAT-895)."""
        return (self.memory_key_id, str(user_id), str(session_id))

    async def _invalidate_working_memory(self, user_id: str, session_id: str) -> None:
        """Drop the session's working memory after a failed write so the next request rehydrates it (FEAT-895).

        Only with a ``hydration_source``: without one nothing could restore the dropped history. Best effort: a
        failure is logged and swallowed, and the caller re-raises the original error.
        """
        if self.hydration_source is None or not self.conversation_memory:
            return
        # FILL IN: await delete_history(user_id, session_id, chatbot_id=self.memory_key_id) inside try/except
        #          Exception → self.logger.warning(... exc_info=True) — bounded by spec §1 Goals (best effort)

# REPLACE — the history-disabled branch, starting at
#   `        snapshot = await self._snapshot_turn(user_id, session_id, turn)` (verified: abstract.py:2787; occurrences: 1)
        async with _TURN_SAVE_LOCKS.hold(self._turn_save_key(user_id, session_id)):
            snapshot = await self._snapshot_turn(user_id, session_id, turn)
            if publish:
                await self._publish_turn_completed(user_id, session_id, snapshot, presentation)
        return snapshot
```
**Why**: the history-disabled branch also stamps and publishes, so it needs the same lock — but here, not in the
caller, because the history branch takes the lock inside `save_conversation_turn`.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — `save_conversation_turn` body)
```python
# REPLACE — from `        await self._stamp_turn_ordering(user_id, session_id, turn)` (the SECOND occurrence, :2923 —
#   disambiguate with the next line `        # Raw, pre-normalization snapshot: MUST precede add_turn`) through
#   `            await self._publish_turn_completed(user_id, session_id, snapshot, presentation)` (:2939),
#   keeping the stage-2 read lines unchanged but indented one level
        async with _TURN_SAVE_LOCKS.hold(self._turn_save_key(user_id, session_id)):
            await self._stamp_turn_ordering(user_id, session_id, turn)
            # Raw, pre-normalization snapshot: MUST precede add_turn (spec §7 "Raw turn snapshot").
            snapshot = copy.deepcopy(turn.to_dict()) if self.turn_publisher is not None else None

            # FILL IN: the FEAT-525 stage-2 read (:2927-2933), unchanged, indented one level

            # FEAT-895 outbox first: the durable tier is the source of truth. A rejected append raises here, before
            # working memory is touched.
            if publish:
                await self._publish_turn_completed(user_id, session_id, snapshot, presentation)
            try:
                await self.conversation_memory.add_turn(
                    user_id, session_id, turn, chatbot_id=chatbot_key, compaction=compaction
                )
            except Exception:
                # FILL IN: when an append happened (publish and snapshot is not None), await
                #          self._invalidate_working_memory(user_id, session_id); then bare `raise`
                #          — bounded by spec §1 Goals
                raise
        # FEAT-176: emit MessageAddedEvent after persisting to memory.   (existing line :2940 — unchanged from here on)
```
**Why**: the lock spans every step that reads or allocates per-session state, so the sequence, the outbox order and
the working-memory order agree. The event emission stays outside: a slow listener must not hold the session.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — `_publish_turn_completed`)
```python
# REPLACE the docstring `        """Publish ``TurnCompletedEvent`` for the raw ``snapshot``. Never raises (logged at ERROR)."""`
#   (verified: abstract.py:3165; occurrences: 1) and remove the try/except whose handler is
#   `        except Exception:  # pylint: disable=broad-except  # a lost audit event must not fail the round` (:3182)
        """Publish ``TurnCompletedEvent`` for the raw ``snapshot`` — the outbox append of the save (FEAT-895).

        No-op without a publisher or a snapshot. Whatever building the event or ``publisher.publish`` raises (the
        outbox rejected the append) propagates, so the save fails before working memory is written.
        """
        publisher = self.turn_publisher
        if publisher is None or snapshot is None:
            return
        event = TurnCompletedEvent(...)  # FILL IN: the existing keyword arguments, unchanged, de-indented
        await publisher.publish(event)
```
**Why**: the caller logs (`_persist_turn_unit._log_failure`, `voice.py`'s handler); logging here too would
double-log.

### `packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py` (MODIFY)
```python
# REPLACE `async def test_publish_after_add_turn():` (:89; occurrences: 1) with test_publish_before_add_turn
# REPLACE `async def test_publish_failure_does_not_fail_round(caplog):` (:126; occurrences: 1) with
#   test_rejected_outbox_append_fails_the_round_and_leaves_memory_untouched
# APPEND at end of file:
class _OrderedPublisher:
    """Records ``publish:<turn_id>`` into a shared log, then yields so a concurrent save could interleave."""

    def __init__(self, log: list) -> None:
        self.log, self.events = log, []

    async def publish(self, event) -> None:
        self.log.append(f"publish:{event.turn['turn_id']}")
        await asyncio.sleep(0.05)
        self.events.append(event)


class _Hydration(HydrationSource):
    async def load_turns(self, *a, **kw):
        return []

    async def is_deleted(self, *a, **kw) -> bool:
        return False

    async def max_sequence(self, *a, **kw) -> int:
        return 0

# FILL IN: test_working_memory_failure_after_the_append_invalidates_a_hydrated_session,
#          test_working_memory_failure_without_a_hydration_source_keeps_the_history,
#          test_same_session_saves_are_serialized, test_bots_sharing_a_memory_key_serialize_their_saves,
#          test_different_sessions_do_not_wait_for_each_other, test_history_disabled_publication_is_serialized,
#          test_save_lock_registry_releases_idle_and_cancelled_entries — bounded by spec §4 Unit Tests
```
**Why**: the sleeping publisher opens the interleaving window that the lock must close; `add_turn` is wrapped per
test to log `store:<turn_id>`.

### FILL IN checklist
- [ ] `_invalidate_working_memory` body — best effort, spec §1 Goals.
- [ ] The stage-2 read moved inside the lock unchanged.
- [ ] The `except` branch of `add_turn` — invalidate only after an append, then re-raise.
- [ ] `TurnCompletedEvent(...)` keyword arguments carried over unchanged.
- [ ] Docstrings of `save_conversation_turn`, `_save_or_snapshot_turn`, `_persist_finalized_turn` (the "Save +
      publish run as one unit…" paragraph, :2817) and `_persist_turn_unit` (:2854): state outbox first, the
      raising append and the per-session lock taken inside the shielded unit.
- [ ] Test bodies — spec §4 Unit Tests.

---

## Acceptance Criteria

- [ ] A rejected outbox append fails the save; working memory holds no new turn.
- [ ] A working-memory failure after the append re-raises, and invalidates the session's working memory only with a
      hydration source.
- [ ] Concurrent saves of one session run one at a time, including across two bot instances with one
      `memory_key_id`; different sessions do not wait for each other.
- [ ] `_TURN_SAVE_LOCKS._entries` is empty when no save runs or waits, also after a cancelled waiter.
- [ ] The new tests fail on the unmodified code and pass with the fix.
- [ ] The Validation Commands pass from the worktree with `PYTHONPATH=packages/ai-parrot/src`.
- [ ] `ruff check` passes; `black --check` leaves the changed lines unchanged.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_memory_key_id.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_context_budget.py -q`
- `pytest packages/ai-parrot/tests/integration/test_durable_conversation_memory.py -q`

---

## Test Specification

See spec §4 Unit Tests (rows for M1).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug bots-abstract-tech-debt-2 --feature-id FEAT-895`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/bots-abstract-tech-debt-2.json` → `"in-progress"` (set `started_at`) and
   commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `parrot sdd task close TASK-5684 bots-abstract-tech-debt-2 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed**: 2026-11-14 · **Verification**: verified · **Code commit**: `cf184da502`

- `_TurnSaveLocks` / `_TURN_SAVE_LOCKS` (module level, refcounted per-key `asyncio.Lock`), `AbstractBot._turn_save_key`
  and `AbstractBot._invalidate_working_memory` added. `save_conversation_turn` takes the lock around stamp → snapshot →
  stage-2 read → outbox append → `add_turn`; the append now precedes `add_turn`; a failing `add_turn` after an append
  invalidates working memory only with a hydration source, then re-raises. `_save_or_snapshot_turn`'s history-disabled
  branch runs under the same lock. `_publish_turn_completed` no longer swallows errors.
- Tests: `test_publish_after_add_turn` → `test_publish_before_add_turn`; `test_publish_failure_does_not_fail_round` →
  `test_rejected_outbox_append_fails_the_round_and_leaves_memory_untouched`; seven M1 tests added. All nine failed on
  the unmodified code. Five targeted mutations (lock key without session, no lock on the history-disabled branch,
  invalidation without the hydration guard, no invalidation, registry never shrinking) each failed their test.
- Validation Commands: 91 passed (five files, `PYTHONPATH=packages/ai-parrot/src`). Also run:
  `ai-parrot-server` `tests/studio/test_tenant_matrix.py` + `tests/manager/test_turn_persistence_wiring.py` — 14 passed,
  14 skipped (infrastructure-gated). `ruff check` clean; `abstract.py` black-clean; the new test hunks black-clean
  (the rest of the test file predates black).
- Pre-existing, unrelated: `tests/tools/working_memory/task_memory/test_bot_task_context.py::
  test_single_writer_only_save_conversation_turn_persists` fails on `dev` without this change (it AST-scans `base.py`
  for a direct `save_conversation_turn` call, which FEAT-886 moved into `_persist_turn_unit`). Filed as
  `issue:d55f57be4ae6`.
- Behaviour change, as decided in spec Q2: an outbox fault (overflow, unwritable SQLite file) now fails the request.
