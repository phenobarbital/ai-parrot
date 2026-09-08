# TASK-2986: Implement task association and atomic Redis metadata merging

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2979
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2980, TASK-2981, TASK-2982 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC1, AC11, AC13

---

## Context

Implements §2 Public task selection; Persistence of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2979 before implementation.

## Scope

- Implement selected/open task association with scope-safe keys, association revisions, finite configured TTL and explicit selection recovery.
- Add enabled atomic compare-and-merge for task/compaction/unrelated metadata in hash and full-history modes, including update_history and turn writers.
- On post-creation Redis failure return the committed task ID and association degradation without duplicating tasks; missing metadata does not delete tasks.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/association.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/src/parrot/memory/redis.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_association.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.memory.redis import RedisConversation  # packages/ai-parrot/src/parrot/memory/redis.py:238
from parrot.memory.abstract import ConversationTurn, ConversationHistory  # packages/ai-parrot/src/parrot/memory/abstract.py:178
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/memory/redis.py:238`**

```python
async def update_history(self, history: ConversationHistory) -> None:
# _store_turn at line 261:
async def _store_turn(self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str] = None, *, compaction_state: Optional[Dict[str, Any]] = None) -> None:
```

_get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.

**`packages/ai-parrot/src/parrot/memory/abstract.py:178`**

```python
def from_ai_message(cls, *, user_message: str, response: "AIMessage", user_id: str, chatbot_id: str, context_used: Optional[str] = None, turn_id: Optional[str] = None, assistant_text: Optional[str] = None, error: Optional[str] = None) -> "ConversationTurn":
```

from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.

### Does NOT Exist

- No atomic task/compaction metadata merge or per-call fenced lease protocol exists.
- No canonical task observer handoff or selected-task association behavior exists yet.
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

- `packages/ai-parrot/src/parrot/memory/redis.py:238` — _get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.
- `packages/ai-parrot/src/parrot/memory/abstract.py:178` — from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.

## Acceptance Criteria

- [ ] Race selection with calibration/turn save using real Redis; retain all metadata.
- [ ] Repeat for full-history mode and stale histories; no lost selected task/calibration.
- [ ] Multiple unselected tasks return needs_task_selection; explicit ID recovery never crosses scope.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC1, AC11, AC13 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_association.py -q`; retain output in `artifacts/logs/task-2986-tm-redis-association.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_race_hash` | Race selection with calibration/turn save using real Redis; retain all metadata. |
| `test_race_full` | Repeat for full-history mode and stale histories; no lost selected task/calibration. |
| `test_selection` | Multiple unselected tasks return needs_task_selection; explicit ID recovery never crosses scope. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2986-tm-redis-association.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

Not completed. The implementing agent records completed-by, date, verification evidence, notes, and any approved deviations here when acceptance passes.
