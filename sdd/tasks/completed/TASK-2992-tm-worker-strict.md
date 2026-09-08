# TASK-2992: Add strict Arrow and safe JSON worker transport

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2975, TASK-2981
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2973, TASK-2974, TASK-2976 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC6, AC9, AC13

---

## Context

Implements §2 ResultPolicy and REPL Recovery of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2975, TASK-2981 before implementation.

## Scope

- Add opt-in strict evidence transport preserving legacy defaults; reject unsupported DataFrames before creating pickle payloads.
- Carry bounded trusted task/worker generation context over the bridge and validate strict requests on both host and worker; constrain JSON values.
- Preserve shared-memory ACK ownership and cleanup on failures/cancellation; provide equivalent strict validation in the in-process adapter.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/repl_worker/inprocess.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_strict_worker_transport.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.repl_worker.transport import encode_dataframe  # packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55
from parrot.tools.repl_worker.handle import WorkerHandle  # packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036
from parrot.tools.repl_worker.protocol import InjectDfRequest  # packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py:214
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55`**

```python
def encode_dataframe(df: pd.DataFrame, name: str) -> EncodedDataFrame:
```

Arrow conversion failure branches to pickle.dumps at 81; EncodedDataFrame carries format/shm_name/size/payload.

**`packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036`**

```python
async def inject_dataframe(self, name: str, df: Any) -> None:
# set_var at line 1092:
async def set_var(self, name: str, value: Any) -> None:
```

Injection calls encode_dataframe in an executor and releases shared memory after acknowledgment; namespace APIs include get_var/snapshot/reset at 1087/1103/1108.

**`packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py:214`**

```python
class InjectDfRequest(BaseModel):
    op: Literal["inject_df"] = "inject_df"
    name: str
    format: Literal["arrow", "pickle"] = "arrow"
```

Existing request also carries optional shm_name, size and pickle payload; set/get variable requests follow.

**`packages/ai-parrot/src/parrot/tools/repl_worker/worker.py:278`**

```python
# Existing dispatch branch:
if isinstance(message, InjectDfRequest):
    # Arrow or pickle decode, then namespace.set_var(message.name, df).
```

The worker currently accepts either format and selects decode_pickle_payload for the non-Arrow branch at 289.

**`packages/ai-parrot/src/parrot/tools/repl_worker/inprocess.py:216`**

```python
async def inject_dataframe(self, name: str, df: Any) -> None:
```

Currently performs await self.set_var(name, df); set_var at 210 updates locals and globals and snapshot at 225 filters modules/callables.

### Does NOT Exist

- No guarantee of pickle-free transport exists without an explicit strict branch.
- No strict evidence mode or generation-bound ReplBindingResolver exists.
- No task-scope/fencing/worker-generation context envelope exists on this request.
- No strict evidence request validation exists at the worker boundary.
- No serialization or strict supported-value validation happens in this existing in-process injection.
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

- `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55` — Arrow conversion failure branches to pickle.dumps at 81; EncodedDataFrame carries format/shm_name/size/payload.
- `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036` — Injection calls encode_dataframe in an executor and releases shared memory after acknowledgment; namespace APIs include get_var/snapshot/reset at 1087/1103/1108.
- `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py:214` — Existing request also carries optional shm_name, size and pickle payload; set/get variable requests follow.
- `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py:278` — The worker currently accepts either format and selects decode_pickle_payload for the non-Arrow branch at 289.
- `packages/ai-parrot/src/parrot/tools/repl_worker/inprocess.py:216` — Currently performs await self.set_var(name, df); set_var at 210 updates locals and globals and snapshot at 225 filters modules/callables.

## Acceptance Criteria

- [ ] Force Arrow conversion failure and spy on pickle serialization; strict calls never reach it, legacy fallback still works.
- [ ] Arrow/JSON supported values and generation envelopes round-trip safely in real subprocess and in-process mode.
- [ ] Cancellation, corrupt envelope and byte overflow leave no leaked shared-memory segments.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC6, AC9, AC13 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_strict_worker_transport.py -q`; retain output in `artifacts/logs/task-2992-tm-worker-strict.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_no_pickle` | Force Arrow conversion failure and spy on pickle serialization; strict calls never reach it, legacy fallback still works. |
| `test_roundtrip` | Arrow/JSON supported values and generation envelopes round-trip safely in real subprocess and in-process mode. |
| `test_cleanup` | Cancellation, corrupt envelope and byte overflow leave no leaked shared-memory segments. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2992-tm-worker-strict.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- `test_strict_worker_transport.py` → **23 passed**, including a **real
  subprocess worker** round trip (confirmed executed with `-v`, not
  skipped) and `/dev/shm` leak checks.
- Log: `artifacts/logs/task-2992-tm-worker-strict.log`. `ruff`/`black`/`isort` clean.

### Regression evidence (AC13)
The existing `packages/ai-parrot/tests/repl_worker` suite has 21–22
pre-existing failures whose count varies between runs (these subprocess
tests are flaky). Rather than compare counts, the sorted `FAILED` test-id
lists were diffed with `comm` against unmodified `dev` in the main
checkout: **zero additions, zero removals**. The failure *set* is
byte-identical, so this change introduces no regression.

### Design decisions
1. **The strict refusal fires before `pickle.dumps`, not after.** Building
   the payload and then declining to send it would already have serialized
   arbitrary objects in-process. `test_no_pickle_strict_never_reaches_pickle`
   therefore **spies on `pickle.dumps`** rather than merely asserting a
   raise — the weaker assertion would pass against the broken
   implementation.
2. **`test_no_pickle_fixture_really_defeats_arrow` is asserted first and
   separately.** If Arrow happened to accept the "unsupported" fixture,
   every strict-refusal assertion in the module would pass vacuously. The
   fixture class is module-level, because a locally-defined class is
   unpicklable and would have failed the *legacy* path for the wrong
   reason.
3. **The worker refuses independently of the host.** Unpickling happens
   worker-side, so that is where the check must live; a host bug or forged
   frame must not smuggle a pickle payload across under an evidence label.
4. **The in-process adapter runs the identical dtype check** even though
   binding is a plain assignment. Skipping it would make in-process mode
   silently more permissive, and the two modes would disagree about what
   counts as evidence.
5. **`tuple` is refused by `ensure_strict_json`** despite looking
   JSON-safe: it round-trips as a `list`, so the value that arrives is not
   the value that was sent.
6. **`WorkerHandle.generation` is a uuid4, not a pid.** The OS recycles
   pids, so a fresh worker could otherwise masquerade as the one a REPL
   binding was made against.
7. **Leak-safety on every path**: the byte ceiling is checked *before* the
   shm block is allocated; `encode_dataframe` unlinks its own block if
   filling it fails; and the unlink in `inject_dataframe`'s `finally` is
   `asyncio.shield`ed so a cancelled send still frees its segment.

### Deviation
`strict` defaults to `False` everywhere and the legacy pickle fallback is
untouched, per the spec's "Do not change legacy transport defaults".
