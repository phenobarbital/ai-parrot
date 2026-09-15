# TASK-2975: Implement bounded snapshots and deterministic fingerprints

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2972
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2973, TASK-2974, TASK-2978 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC5, AC6, AC16

---

## Context

Implements §2 Catalog Backend, Versions, and Evidence of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2972 before implementation.

## Scope

- Implement safe snapshots for numeric/string DataFrames and canonical JSON/text; capture shape/schema and actual retained byte accounting.
- Fingerprint ordered schema/index/content using versioned BLAKE2b-8 rules; distinguish blob checksum from content fingerprint.
- Reject unsupported nested mutable object evidence or mark unverifiable; enforce limits during serialization and offload heavy work without mutating catalog from threads.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/snapshots.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_snapshots.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.working_memory.internals import WorkingMemoryCatalog, CatalogEntry, GenericEntry  # packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542
from pydantic import BaseModel, Field  # packages/ai-parrot/pyproject.toml:54
from parrot.tools.repl_worker.transport import encode_dataframe  # packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542`**

```python
def get(self, key: str) -> CatalogEntry | GenericEntry:
def drop(self, key: str) -> bool:
```

GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.

**`packages/ai-parrot/pyproject.toml:54`**

```python
# Dependency declarations: Python >=3.11; pydantic ==2.12.5;
# pandas >=2.0.0; pyarrow >=25.0; orjson >=3.9;
# existing graphindex-postgres extra: asyncpg >=0.29.
```

Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

**`packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55`**

```python
def encode_dataframe(df: pd.DataFrame, name: str) -> EncodedDataFrame:
```

Arrow conversion failure branches to pickle.dumps at 81; EncodedDataFrame carries format/shm_name/size/payload.

### Does NOT Exist

- No awaited catalog backend, versioned evidence metadata, locks or to_descriptor method exists at this commit.
- No new qworker/ULID/task-memory dependency is authorized; do not assume stdlib uuid7 on Python 3.11.
- No guarantee of pickle-free transport exists without an explicit strict branch.
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
- `packages/ai-parrot/pyproject.toml:54` — Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.
- `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55` — Arrow conversion failure branches to pickle.dumps at 81; EncodedDataFrame carries format/shm_name/size/payload.

## Acceptance Criteria

- [ ] Mutating live input does not mutate supported snapshots, including explicit handling of nested object cells.
- [ ] Reload-equivalent content hashes identically; column/dtype/index/value changes alter the fingerprint.
- [ ] Cap boundary and unsupported types report true memory/verification status, never sys.getsizeof-based false confidence.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC5, AC6, AC16 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_snapshots.py -q`; retain output in `artifacts/logs/task-2975-tm-snapshots.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_independence` | Mutating live input does not mutate supported snapshots, including explicit handling of nested object cells. |
| `test_fingerprint` | Reload-equivalent content hashes identically; column/dtype/index/value changes alter the fingerprint. |
| `test_size_limit` | Cap boundary and unsupported types report true memory/verification status, never sys.getsizeof-based false confidence. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2975-tm-snapshots.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker, delegated fork) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence

- `uv run pytest .../test_snapshots.py -q` → **49 passed**.
  Log: `artifacts/logs/task-2975-tm-snapshots.log`.
- Whole `task_memory` suite: **219 passed**.
- `ruff check` clean; `black`/`isort` applied.
- Codebase Contract re-verified anchor by anchor (internals.py
  70/175/189/468/473/499/542/548, transport.py 55/81, pyproject
  54/104/157/173). **No stale anchors.**

### Independent verification (not taken on trust)

The implementing agent's three load-bearing claims were re-checked
directly before this task was accepted:

- `orjson.dumps({1:"a"}, OPT_NON_STR_KEYS|OPT_SORT_KEYS)` and the same for
  `{"1":"a"}` both produce `b'{"1":"a"}'` — **collision confirmed**.
- Renaming a DataFrame column leaves `hash_pandas_object` output
  **bit-identical** — confirmed on pandas 2.2.3.
- `dict`, `set` and `tuple` object cells hash without raising (pandas
  falls back to their string repr); only `list` raises — **confirmed**.
- Functionally: a nested-object frame yields
  `outcome=unverifiable, fingerprint=None, evidence_verifiable=False`; a
  numeric/string frame is `captured` and verifiable; both mutation and
  column rename change the fingerprint.

### Acceptance mapping

| Criterion | Evidence |
|---|---|
| Deterministic reproducible fingerprints | `fingerprint_dataframe` / `fingerprint_bytes` + reproducibility tests |
| 64 MiB boundary and byte accounting | `ByteAccount`, `SizeMethod`, over-cap refusal before copy |
| Nested mutable values never falsely verified | `unsafe_object_columns`, `UNVERIFIABLE` outcome |
| AC5 / AC6 | mutation detection, unverifiable fallback, three-way outcome |

### Design decisions worth flagging downstream

1. **`OPT_NON_STR_KEYS` is deliberately absent** from canonical JSON. It
   would make `{1:"a"}` and `{"1":"a"}` fingerprint-identical. Non-string
   keys are refused as unverifiable instead.
2. **The fingerprint header is load-bearing, not decorative** — without
   it a column rename is invisible to the row hashes.
3. **Nested-mutable detection is structural, not exception-driven.**
   Because dict/set/tuple cells hash fine, "did hashing throw" is not a
   safety signal. `unsafe_object_columns` scans distinct types per object
   column in one pass, with no sampling (so no false all-clear).
4. **`tuple` and `frozenset` are conservatively refused** despite being
   immutable: a tuple can contain a dict, and frozenset iteration order is
   not guaranteed stable across processes.
5. **Three-way `SnapshotOutcome`** (`CAPTURED` / `SPILL_REQUIRED` /
   `UNVERIFIABLE`) rather than a boolean — an over-cap *supported* value
   is materially different from an unsupported one, and only the caller
   knows whether a durable tier exists. **This module never writes bytes.**
6. **Honest size accounting** — `PANDAS_DEEP_ESTIMATE` (exact=False) for
   frames, `CANONICAL_UTF8` (exact=True) for JSON/text, `UNKNOWN` with
   `live_bytes=None` for arbitrary objects rather than a `sys.getsizeof`
   guess.
7. **`blob_checksum` uses a `ck_` prefix and its own algorithm version**,
   so a Parquet-byte hash can never be silently compared against a
   pandas-content hash.
