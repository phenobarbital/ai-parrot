# TASK-2993: Resolve exact evidence versions into current REPL workers

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2976, TASK-2980, TASK-2992
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2982, TASK-2983, TASK-2984 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC5, AC6, AC9

---

## Context

Implements §2 ResultPolicy and REPL Recovery of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2976, TASK-2980, TASK-2992 before implementation.

## Scope

- Implement explicit ReplBindingResolver.load with trusted scope, exact version, configured byte limit and worker generation.
- Verify payload fingerprint before strict injection, publish binding only after acknowledgment, and diagnose stale generation without losing durable location.
- Support supported in-memory artifacts now and the injected durable load protocol later; never restore namespaces or execute saved code.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/repl.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_repl_binding_resolver.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.repl_worker.handle import WorkerHandle  # packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036
from parrot.tools.working_memory.internals import WorkingMemoryCatalog, CatalogEntry, GenericEntry  # packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542
from parrot.tools.repl_worker.protocol import InjectDfRequest  # packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py:214
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036`**

```python
async def inject_dataframe(self, name: str, df: Any) -> None:
# set_var at line 1092:
async def set_var(self, name: str, value: Any) -> None:
```

Injection calls encode_dataframe in an executor and releases shared memory after acknowledgment; namespace APIs include get_var/snapshot/reset at 1087/1103/1108.

**`packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542`**

```python
def get(self, key: str) -> CatalogEntry | GenericEntry:
def drop(self, key: str) -> bool:
```

GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.

**`packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py:214`**

```python
class InjectDfRequest(BaseModel):
    op: Literal["inject_df"] = "inject_df"
    name: str
    format: Literal["arrow", "pickle"] = "arrow"
```

Existing request also carries optional shm_name, size and pickle payload; set/get variable requests follow.

### Does NOT Exist

- No strict evidence mode or generation-bound ReplBindingResolver exists.
- No awaited catalog backend, versioned evidence metadata, locks or to_descriptor method exists at this commit.
- No task-scope/fencing/worker-generation context envelope exists on this request.
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

- `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036` — Injection calls encode_dataframe in an executor and releases shared memory after acknowledgment; namespace APIs include get_var/snapshot/reset at 1087/1103/1108.
- `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542` — GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.
- `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py:214` — Existing request also carries optional shm_name, size and pickle payload; set/get variable requests follow.

## Acceptance Criteria

- [ ] A restarted/replaced worker invalidates only its live binding; resolver returns a new generation-bound binding.
- [ ] Foreign scope, oversized load or hash mismatch rejects before injection.
- [ ] Recall and descriptor reads never invoke the resolver or load data.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC5, AC6, AC9 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_repl_binding_resolver.py -q`; retain output in `artifacts/logs/task-2993-tm-repl-resolver.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_generation` | A restarted/replaced worker invalidates only its live binding; resolver returns a new generation-bound binding. |
| `test_scope_size_hash` | Foreign scope, oversized load or hash mismatch rejects before injection. |
| `test_explicit_only` | Recall and descriptor reads never invoke the resolver or load data. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2993-tm-repl-resolver.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker, delegated fork) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- `test_repl_binding_resolver.py` → **21 passed, 0 skipped**.
  `test_strict_worker_transport.py` still **23 passed**.
  Log: `artifacts/logs/task-2993-tm-repl-resolver.log`.
- `ruff`/`black`/`isort` clean.

### A REAL subprocess ran — verified, not skipped
`test_real_subprocess_worker_round_trip` spawns an actual `WorkerHandle`,
injects a 20-row frame through the strict Arrow/shm path and reads it
back with `assert_frame_equal`. Confirmed with `-v` that it reports
**PASSED** rather than SKIPPED, and re-confirmed independently during
review. The in-process handle is covered separately, and both are
asserted to satisfy the `WorkerLike` protocol.

### Ordering is the guarantee, and it is asserted as such
Scope, existence, availability, kind, verifiability and the byte ceiling
are all settled **before** any load; the fingerprint is verified **before**
any injection; the binding is published only **after** the worker
acknowledges.

Every refusal test asserts `worker.call_count == 0`. This matters: a
resolver that injected and *then* returned a refusal would pass a naive
"it refused" assertion having already done the damage.

### Design decisions
1. **`artifact_locatable` is on every result, and both halves are
   asserted.** A stale binding and lost bytes are different failures.
   Reporting lost evidence as a stale binding hides data loss; reporting
   a stale binding as lost evidence makes a routine worker restart look
   like corruption.
2. **A foreign scope and a nonexistent version return the identical
   refusal** (`unknown_version`), deliberately — distinguishing them
   would make this an existence oracle for another scope's artifact ids.
3. **Fingerprints are recomputed via `snapshots.py`**, not re-derived.
   Two independent implementations of "the canonical bytes" would
   eventually disagree, and the disagreement would surface as a spurious
   mutation report.
4. **`ReplBinding.worker_session_id` carries the handle's `generation`
   string** (a uuid4 hex), matching how the committed `recall.py` already
   reads it (`binding.worker_session_id != availability.worker_generation`),
   so recall's staleness check works against these bindings unchanged.
   The model's separate integer `worker_generation` stays 0.
5. **The public surface is asserted to be exactly `{describe, load}`**, so
   no bulk namespace-restore entry point can be added without a test
   noticing.

### Two test bugs of its own, fixed rather than worked around
The first structural checks used substring matching over raw source and
so flagged the modules' **own prose** ("there is no pickle fallback",
"never calls `load_payload`"). Replaced with an AST walk over referenced
identifiers — the stronger check anyway, since *documenting* that you
never call something is fine while *calling* it is not.

### CONTRACT CORRECTION
The task listed `inject_dataframe(self, name, df)` at `handle.py:1036` —
the **pre-TASK-2992** signature. The committed one is
`inject_dataframe(name, df, *, strict=, envelope=, max_bytes=)`, and
`WorkerHandle.generation` did not exist at the pinned commit either. Both
are TASK-2992 outputs and were correctly flagged in the task's "Does NOT
Exist" section; the implementation codes against the committed reality.
