# TASK-2980: Implement evidence-bound completion validation

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2979
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2981, TASK-2982, TASK-2986 after prerequisites. Shared-file predecessors: TASK-2979; do not edit their files concurrently.
**Delivery**: A
**Spec acceptance**: AC3, AC5, AC7

---

## Context

Implements §2 Reducer and Completion; Evidence of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2979 before implementation.

## Scope

- Implement code-registered artifact_exists, artifact_fingerprint_matches, artifact_non_empty and no_pending_tool_failures validators.
- Resolve aliases once, pin exact versions, distinguish old-version overwrite from same-version mutation, and reject error artifacts as successful evidence.
- Implement validated/asserted completion rules; validate outside long locks and compare task revision and evidence generation at commit.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/validators.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/service.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_completion_validators.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.working_memory.internals import WorkingMemoryCatalog, CatalogEntry, GenericEntry  # packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542
from parrot.memory.compaction.omission import OmissionStore  # packages/ai-parrot/src/parrot/memory/compaction/omission.py:61
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542`**

```python
def get(self, key: str) -> CatalogEntry | GenericEntry:
def drop(self, key: str) -> bool:
```

GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.

**`packages/ai-parrot/src/parrot/memory/compaction/omission.py:61`**

```python
async def put(self, session_key: str, content: str, *, turn_id: Optional[str] = None) -> str:
# get at line 87:
async def get(self, session_key: str, content_id: str) -> Optional[str]:
```

InMemoryOmissionStore begins at 120, RedisOmissionStore at 149. get fetches payload text; built-in IDs already include one om_ prefix.

### Does NOT Exist

- No awaited catalog backend, versioned evidence metadata, locks or to_descriptor method exists at this commit.
- No bounded availability-probe API exists; custom stores need a backward-compatible unknown fallback.
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

- `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542` — GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.
- `packages/ai-parrot/src/parrot/memory/compaction/omission.py:61` — InMemoryOmissionStore begins at 120, RedisOmissionStore at 149. get fetches payload text; built-in IDs already include one om_ prefix.

## Acceptance Criteria

- [ ] Validated policies require every validator; asserted completion requires accessible evidence and required note with explicit source label.
- [ ] Mutation/revision change during validation causes retry or rejection, never stale completion.
- [ ] Old immutable version remains valid after overwrite; same-version live mutation emits invalidation and blocks completion.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC3, AC5, AC7 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_completion_validators.py -q`; retain output in `artifacts/logs/task-2980-tm-completion-validators.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_completion_modes` | Validated policies require every validator; asserted completion requires accessible evidence and required note with explicit source label. |
| `test_mutation_race` | Mutation/revision change during validation causes retry or rejection, never stale completion. |
| `test_overwrites` | Old immutable version remains valid after overwrite; same-version live mutation emits invalidation and blocks completion. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2980-tm-completion-validators.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- `test_completion_validators.py` → **19 passed**; with the service suite,
  **42 passed**. Log: `artifacts/logs/task-2980-tm-completion-validators.log`.
- `ruff`/`black`/`isort` clean.

### Two findings my own tests forced — both fixed in the implementation
1. **`assert_unchanged` compared only fingerprints.** A version
   *invalidated* between validation and commit keeps its fingerprint, so
   the comparison passed and a completion could commit against evidence
   that had just been invalidated. Invalidation is now checked separately
   and explicitly.
2. **The test conflated two different situations.** Evidence already
   invalid when validation *begins* is simply invalid evidence
   (`artifact_exists` refuses it); evidence invalidated *during* the
   window is a **mutation** (`EvidenceMutated`, which additionally implies
   reopening anything completed against it). They now assert their own
   accurate error instead of sharing one.

### Design decisions
1. **Overwrite vs mutation is tested from BOTH directions.** An overwrite
   must *not* invalidate (else every alias rewrite would spuriously reopen
   sound work); a mutation *must*. Testing one direction only would let
   the opposite bug through.
2. **An unknown validator RAISES; never a vacuous pass.** Treating an
   unregistered name as "nothing to check" would silently downgrade a
   `validated` completion to an unchecked one.
3. **`artifact_fingerprint_matches` requires `evidence_verifiable`**, so a
   nested-object frame can never satisfy it — pandas will happily compute
   a repr-based fingerprint for one (TASK-2970's finding), and that is not
   integrity proof.
4. **`artifact_non_empty` judges by CAPTURED SHAPE**, never by loading the
   payload. A validator that loaded data to check emptiness would make
   completion arbitrarily expensive and defeat the byte ceilings.
5. **Aliases are resolved ONCE and pinned.** Resolving twice would open a
   window in which an overwrite between the two reads silently changed
   what was validated; a test asserts a post-resolution overwrite does not
   move the pin.
6. **`agent_asserted` needs at least one ACCESSIBLE reference plus the
   note**, and is labelled the weaker source everywhere. An assertion
   backed by nothing reachable is a guess, not an assertion.
7. **Validation runs OUTSIDE the store lock**, proven by a re-entrant
   validator that reads the same task from inside validation — it would
   deadlock if the lock were held.
8. **Without an artifact store, `complete_step` REFUSES** rather than
   completing unvalidated. Refusing is the safe default.
