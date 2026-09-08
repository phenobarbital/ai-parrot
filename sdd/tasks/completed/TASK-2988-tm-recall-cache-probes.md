# TASK-2988: Add bounded recall reads, cache and omission probes

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2986, TASK-2987
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2980, TASK-2981, TASK-2982 after prerequisites. Shared-file predecessors: TASK-2987; do not edit their files concurrently.
**Delivery**: A
**Spec acceptance**: AC1, AC10, AC11

---

## Context

Implements §2 Recall and Stage 2 of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2986, TASK-2987 before implementation.

## Scope

- Add scoped availability probes to built-in omission stores with unknown fallback for custom backends; never load content to test existence.
- Implement bounded consistent snapshot/event/artifact queries and Redis cache keyed by scope/sequence/availability generation/args/tokenizer/calibration/schema.
- Refresh worker/omission overlays or invalidate cache generations when state changes without a new task event; handle cache outage without changing task truth.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/recall.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/memory/compaction/omission.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_recall_cache.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.memory.compaction.omission import OmissionStore  # packages/ai-parrot/src/parrot/memory/compaction/omission.py:61
from parrot.memory.compaction.tokens import get_default_counter, TokenCounter  # packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89
from parrot.memory.redis import RedisConversation  # packages/ai-parrot/src/parrot/memory/redis.py:238
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/memory/compaction/omission.py:61`**

```python
async def put(self, session_key: str, content: str, *, turn_id: Optional[str] = None) -> str:
# get at line 87:
async def get(self, session_key: str, content_id: str) -> Optional[str]:
```

InMemoryOmissionStore begins at 120, RedisOmissionStore at 149. get fetches payload text; built-in IDs already include one om_ prefix.

**`packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89`**

```python
def get_default_counter() -> TokenCounter:
# TokenCounter.count at line 35:
def count(self, text: str) -> int:
```

The existing fallback estimates UTF-8 bytes divided by four, minimum one for nonempty text; it is not a provider-token upper bound.

**`packages/ai-parrot/src/parrot/memory/redis.py:238`**

```python
async def update_history(self, history: ConversationHistory) -> None:
# _store_turn at line 261:
async def _store_turn(self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str] = None, *, compaction_state: Optional[Dict[str, Any]] = None) -> None:
```

_get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.

### Does NOT Exist

- No bounded availability-probe API exists; custom stores need a backward-compatible unknown fallback.
- No deterministic task recall selector/cache exists in the counter module.
- No atomic task/compaction metadata merge or per-call fenced lease protocol exists.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Compose the service/backend contracts from completed prerequisites. Keep new methods private unless the spec explicitly lists an LLM-facing tool. Keep the disabled path behavior and schemas unchanged.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/memory/compaction/omission.py:61` — InMemoryOmissionStore begins at 120, RedisOmissionStore at 149. get fetches payload text; built-in IDs already include one om_ prefix.
- `packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89` — The existing fallback estimates UTF-8 bytes divided by four, minimum one for nonempty text; it is not a provider-token upper bound.
- `packages/ai-parrot/src/parrot/memory/redis.py:238` — _get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.

## Acceptance Criteria

- [ ] Spies reject data loads, get-content, describe, LLM and unbounded scans during recall.
- [ ] Cross-scope/task/calibration/worker generation snapshots never collide.
- [ ] Expired/unknown omission refs and dead worker bindings are truthful at unchanged task sequence.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC1, AC10, AC11 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_recall_cache.py -q`; retain output in `artifacts/logs/task-2988-tm-recall-cache-probes.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_no_payload_reads` | Spies reject data loads, get-content, describe, LLM and unbounded scans during recall. |
| `test_cache_keys` | Cross-scope/task/calibration/worker generation snapshots never collide. |
| `test_expiry` | Expired/unknown omission refs and dead worker bindings are truthful at unchanged task sequence. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2988-tm-recall-cache-probes.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker, delegated fork) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- `test_recall_cache.py` → **27 passed, 0 skipped**. Redis was reachable,
  so both live cases **ran**. `test_recall_selector.py` still **25
  passed**. `unit/memory` **115 passed**.
  Log: `artifacts/logs/task-2988-tm-recall-cache-probes.log`.
- `ruff`/`black`/`isort` clean.

### A conflict with TASK-2987 resolved WITHOUT gaming it
`test_recall_selector.py::test_determinism_recall_is_pure` AST-scans
`recall.py` and forbids importing `time`/`os`/`asyncio` **anywhere in the
module**. That guard was written when the file was selector-only; this
task's mandate is to add an I/O layer to the *same* file, so `import time`
for the cache TTL broke it.

Dodging the scan with `__import__("time")` would have defeated the
guard's purpose. Instead `InMemoryRecallCache` takes its clock as a
**required argument**: no clock is imported anywhere in `recall.py`, the
guard stays meaningful **and unmodified**, and the time source becomes
explicit at the call site. Production wiring passes `time.monotonic`;
tests pass a fake, which is also how TTL expiry is tested without
sleeping.

Verified during review: no dynamic-import dodge is present, and the guard
still passes.

### The cache initially saved nothing — and the test caught it
The first version built the full `RecallInputs` **before** computing the
key, so a "hit" avoided only the final serialization: the journal page
and the omission probes ran anyway. Restructured into `_read_fence`
(projection + descriptor page — the two reads a key *cannot* be computed
without) → cache check → `_complete_inputs` (journal page + probes) only
on a miss. `test_cache_keys_ttl_expires_without_sleeping` counts
`list_events` calls, so it fails if that ordering ever regresses.

### The probe is the point, enforced by an armed trap
`OmissionStore.get` **loads content**, so recall must never call it merely
to test existence — omitted payloads are by construction the large ones.
`RedisOmissionStore.probe` uses `HEXISTS` (verified during review), and
the test's `_TrapClient.hget` **raises**, so an implementation that
reached for the payload fails loudly rather than passing slowly.
`probe_many` batches into one pipeline round trip, falling back to the
base loop for clients without `pipeline` rather than crashing on them —
the same lesson TASK-2986 learned with `_FakeRedis`.

**`probe` is deliberately not abstract.** A store written before FEAT-538
keeps working and inherits `None` — *unknown*. Unknown is never reported
as available: claiming content is present when the store cannot say so
would let recall promise recoverable text that may be long gone.

### Other decisions
1. **`build_cache_key_parts` was extracted, not duplicated.** The reader
   needs the key *before* selecting — a cache keyable only after doing the
   work it avoids is useless — but a second copy of the key definition
   would drift. `select_recall` now calls the same function, so its
   `cache_key_parts` and the reader's key cannot disagree.
2. **`cache_digest` hashes the canonical serialization, not a joined
   string.** A test pins the case a naive `":".join` gets wrong
   (`"a:b"+"c"` vs `"a"+"b:c"`).
3. **Each cache dimension is varied independently.** Varying several at
   once would still pass if one were silently ignored.
4. **Cache failures degrade to a miss, never to an error** — a broken
   cache, a corrupt entry and a `RuntimeError` on read all recompute, with
   the task's revision asserted unchanged afterwards.

### Contract note
No stale anchors — `omission.py:61`/`:87`, `InMemoryOmissionStore` at 120,
`RedisOmissionStore` at 149, the single `om_` prefix and `tokens.py:89`
all verified as described. One **omission** rather than an error: the
contract does not mention `FileOmissionStore` (line 199), which is also a
built-in and therefore also got a real probe.

### Environment gaps (reported, not patched)
- `hypothesis` is missing from the pruned venv, so `test_compact.py` and
  `test_normalize.py` cannot be collected (2 collection errors).
- `tests/outputs/a2ui/test_artifacts.py` fails 5 tests. **Verified
  pre-existing** — the agent swapped in the committed `HEAD` `omission.py`,
  got the same 5 failures and restored its file md5-identically; the
  reviewer independently reproduced the same 5 failures on unmodified
  `dev` in the main checkout.
