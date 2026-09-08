# TASK-3000: Implement verified archive and crash-safe durable cleanup

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2997, TASK-2998, TASK-2999
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2987, TASK-2988, TASK-2989 after prerequisites. Shared-file predecessors: TASK-2999, TASK-2998, TASK-2996; do not edit their files concurrently.
**Delivery**: B
**Spec acceptance**: AC8, AC9, AC12

---

## Context

Implements §2 Retention and Redaction of the approved specification. Delivery B establishes durable continuity; passing in-memory tests alone does not complete this work. Consume the committed contracts from TASK-2997, TASK-2998, TASK-2999 before implementation.

## Scope

- Add 90-day terminal archive/delete, unpinned stale-version cleanup, orphan grace and expired hot-key cleanup using durable stores.
- Append retention intent, include it in optional JSONL archive, verify archive before deletion and protect live publication/archive references.
- Make retries safe across archive/delete crashes and report local journal audit removal honestly; retain evidence pinned by any nonterminal task.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/retention.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/store/postgres.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_retention_durable.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.interfaces.file import FileManagerInterface  # packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18
from parrot.memory.compaction.omission import OmissionStore  # packages/ai-parrot/src/parrot/memory/compaction/omission.py:61
from parrot.memory.redis import RedisConversation  # packages/ai-parrot/src/parrot/memory/redis.py:238
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18`**

```python
# Verified export; external method signatures must be pinned in the Phase 0 task.
FileManagerInterface
```

Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.

**`packages/ai-parrot/src/parrot/memory/compaction/omission.py:61`**

```python
async def put(self, session_key: str, content: str, *, turn_id: Optional[str] = None) -> str:
# get at line 87:
async def get(self, session_key: str, content_id: str) -> Optional[str]:
```

InMemoryOmissionStore begins at 120, RedisOmissionStore at 149. get fetches payload text; built-in IDs already include one om_ prefix.

**`packages/ai-parrot/src/parrot/memory/redis.py:238`**

```python
async def update_history(self, history: ConversationHistory) -> None:
# _store_turn at line 261:
async def _store_turn(self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str] = None, *, compaction_state: Optional[Dict[str, Any]] = None) -> None:
```

_get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.

### Does NOT Exist

- No versioned Parquet task store is provided by this compatibility shim; do not invent external stream/stat methods.
- No bounded availability-probe API exists; custom stores need a backward-compatible unknown fallback.
- No atomic task/compaction metadata merge or per-call fenced lease protocol exists.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Default OQ1: JSONL if archive_uri set; otherwise delete with bounded operational audit.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18` — Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.
- `packages/ai-parrot/src/parrot/memory/compaction/omission.py:61` — InMemoryOmissionStore begins at 120, RedisOmissionStore at 149. get fetches payload text; built-in IDs already include one om_ prefix.
- `packages/ai-parrot/src/parrot/memory/redis.py:238` — _get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.

## Acceptance Criteria

- [ ] Failed archive/verification leaves source journal/projection/payloads intact.
- [ ] A blob under active publication or archive reference is not deleted after an unrelated scan.
- [ ] Crash between each cleanup step converges without duplicate archives or loss of still-pinned evidence.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC8, AC9, AC12 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_retention_durable.py -q`; retain output in `artifacts/logs/task-3000-tm-retention-durable.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_archive_failure` | Failed archive/verification leaves source journal/projection/payloads intact. |
| `test_orphan_race` | A blob under active publication or archive reference is not deleted after an unrelated scan. |
| `test_delete_retry` | Crash between each cleanup step converges without duplicate archives or loss of still-pinned evidence. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-3000-tm-retention-durable.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

Not completed. The implementing agent records completed-by, date, verification evidence, notes, and any approved deviations here when acceptance passes.
