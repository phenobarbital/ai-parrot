# TASK-2970: Pin integration contracts and measure snapshot costs

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial verification gate: wait for all dependencies and run without concurrent edits to production files exercised by the checks.
**Delivery**: A
**Spec acceptance**: AC13, AC16

---

## Context

Implements §3 Phase 0; §7 constraints of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. This investigation is the first runnable task and gates all implementation.

## Scope

- Pin the implementation commit and inventory every catalog write/read, manager dispatch branch, plan receipt boundary, and worker transport path.
- Inspect the installed navigator file-manager byte-stream/stat APIs and record real signatures suitable for strict bounded blob I/O; do not add dependencies.
- Measure independent numeric/string and nested-object snapshots and fingerprints at 8/64/256 MiB; record peak retained bytes and timings with deterministic fixtures.
- Record the 64 MiB default decision and non-blocking OQ1/OQ2 defaults, plus the integration map used by downstream tasks.

**NOT in scope**: Production implementation, task execution, new dependencies, and unrelated refactors.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/memory/task-memory-integration-map.md` | CREATE | Documented deliverable |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/bench_snapshot_costs.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.working_memory.internals import WorkingMemoryCatalog, CatalogEntry, GenericEntry  # packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542
from parrot.tools.manager import ToolManager  # packages/ai-parrot/src/parrot/tools/manager.py:1514
from parrot.bots.flows.plan.node import PlanToolNode, build_manifest  # packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347
from parrot.tools.repl_worker.transport import encode_dataframe  # packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55
from parrot.interfaces.file import FileManagerInterface  # packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18
from pydantic import BaseModel, Field  # packages/ai-parrot/pyproject.toml:54
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542`**

```python
def get(self, key: str) -> CatalogEntry | GenericEntry:
def drop(self, key: str) -> bool:
```

GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.

**`packages/ai-parrot/src/parrot/tools/manager.py:1514`**

```python
async def execute_tool(self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional["PermissionContext"] = None, *, return_tool_result: bool = False) -> Any:
```

ToolDefinition and AbstractTool branches share guard ordering; full-result mode preserves envelopes. Clone shares tool instances while mutable manager state is distinct (2459–2489).

**`packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347`**

```python
async def _store(self, key: str, payload: Any, *, index: Optional[int]) -> int:
# _call_with_retry at line 414:
async def _call_with_retry(self, args: Dict[str, Any]) -> Any:
```

_call_with_retry dispatches through the manager at 431; _store awaits store_result at 350 after dispatch returns. _read_key at 392 accesses catalog.get synchronously. Factory closure starts around 530.

**`packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55`**

```python
def encode_dataframe(df: pd.DataFrame, name: str) -> EncodedDataFrame:
```

Arrow conversion failure branches to pickle.dumps at 81; EncodedDataFrame carries format/shm_name/size/payload.

**`packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18`**

```python
# Verified export; external method signatures must be pinned in the Phase 0 task.
FileManagerInterface
```

Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.

**`packages/ai-parrot/pyproject.toml:54`**

```python
# Dependency declarations: Python >=3.11; pydantic ==2.12.5;
# pandas >=2.0.0; pyarrow >=25.0; orjson >=3.9;
# existing graphindex-postgres extra: asyncpg >=0.29.
```

Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

### Does NOT Exist

- No awaited catalog backend, versioned evidence metadata, locks or to_descriptor method exists at this commit.
- No general ToolExecutionObserver registry or task-memory call receipts exist; guard/compression hooks are not that API.
- No plan node ID automatically equals a runtime TaskStep ID; no receipt persists beyond dispatcher context reset yet.
- No guarantee of pickle-free transport exists without an explicit strict branch.
- No versioned Parquet task store is provided by this compatibility shim; do not invent external stream/stat methods.
- No new qworker/ULID/task-memory dependency is authorized; do not assume stdlib uuid7 on Python 3.11.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Investigation deliverable only; do not implement production memory code. Store raw benchmark logs in artifacts/logs/.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542` — GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.
- `packages/ai-parrot/src/parrot/tools/manager.py:1514` — ToolDefinition and AbstractTool branches share guard ordering; full-result mode preserves envelopes. Clone shares tool instances while mutable manager state is distinct (2459–2489).
- `packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347` — _call_with_retry dispatches through the manager at 431; _store awaits store_result at 350 after dispatch returns. _read_key at 392 accesses catalog.get synchronously. Factory closure starts around 530.
- `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55` — Arrow conversion failure branches to pickle.dumps at 81; EncodedDataFrame carries format/shm_name/size/payload.
- `packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18` — Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.
- `packages/ai-parrot/pyproject.toml:54` — Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

## Acceptance Criteria

- [ ] Inventory identifies direct catalog, tee, plan, ordinary and streaming call sites without assuming a universal hook.
- [ ] 8/64/256 MiB measurements record environment, reproducible input sizes and verification limitations.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC13, AC16 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run python packages/ai-parrot/tests/tools/working_memory/task_memory/bench_snapshot_costs.py`; retain output in `artifacts/logs/task-2970-tm-integration-spike.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_contract_inventory` | Inventory identifies direct catalog, tee, plan, ordinary and streaming call sites without assuming a universal hook. |
| `test_snapshot_measurements` | 8/64/256 MiB measurements record environment, reproducible input sizes and verification limitations. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2970-tm-integration-spike.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence

- `uv run python packages/ai-parrot/tests/tools/working_memory/task_memory/bench_snapshot_costs.py`
  → exit 0. Full output retained at `artifacts/logs/task-2970-tm-integration-spike.log`.
- `ruff check` clean; `black --line-length 120 --target-version py312` and
  `isort` applied.
- Contract inventory verified against live source at `1447c25a8c` (dev
  `0b4920b2f` + the SDD start commit); every pinned anchor re-checked with
  `grep -n` before being written into the map.

### Results

| Payload | 8 MiB | 64 MiB | 256 MiB |
|---|---|---|---|
| numeric/string DF — copy / fingerprint (s) | 0.001 / 0.390 | 0.006 / 2.301 | 0.030 / 9.458 |
| nested-object DF — copy / fingerprint (s) | 0.001 / 3.949 | 0.004 / 31.191 | 0.015 / 122.741 |
| JSON/text stdlib — encode / fingerprint (s) | 1.993 / 0.012 | 16.647 / 0.113 | 65.097 / 0.417 |
| JSON/text orjson — encode / fingerprint (s) | 0.050 / 0.013 | 0.434 / 0.115 | 1.614 / 0.417 |

Environment: Python 3.12.3, Linux 7.0.0-31-generic x86_64, pandas 2.2.3,
numpy 2.4.6. Single host, single run — orders of magnitude, not an SLO.

### Decisions recorded

- **OQ3 resolved**: `snapshot_max_bytes` default stays **64 MiB**.
- **P0-1**: canonical JSON uses `orjson` + `OPT_SORT_KEYS` (byte-identical
  to the stdlib arm, ~40x faster, ~25% lower peak). No new dependency.
- **P0-2**: nested mutable object cells ⇒ `evidence_verifiable=False`.
  pandas does *not* raise on unhashable cells — it silently hashes their
  string repr, so a computable fingerprint there is not integrity proof.
  `df.copy(deep=True)` also does not detach them (verified by object
  identity at every size).
- **P0-3**: blob I/O uses `create_from_bytes` / `get_file_metadata` /
  `download_file(BytesIO)`; the `FileMetadata.size` pre-check is the byte
  ceiling. There is no chunked writer and no byte-limit parameter on the
  interface — do not invent one.
- **P0-4**: the invocation observer attaches to the `ToolManager`, not to
  tool instances — `clone()` (`manager.py:2439`) shares tool instances but
  gives the clone its own mutable manager state.
- OQ1 and OQ2 keep their spec defaults; nothing measured contradicts them.

### Spec contract corrections

None required. The spec's Codebase Contract was re-verified anchor by
anchor and every claim held, including the `storage/overflow.py:20` claim
(confirmed JSON-definition oriented: `json.dumps` above a 200 KB
`INLINE_THRESHOLD`, written to a `{prefix}.json` key — not a versioned
Parquet store). Several line anchors quoted in the map were corrected
against the current tree during writing (e.g. `clone()` at `:2439`, not
`:2459`; `_store_turn` at `redis.py:261`, with the non-atomic metadata
rewrite at `:290-297`).

### Approved deviations

Two empty `__init__.py` files were created alongside the benchmark
(`packages/ai-parrot/tests/tools/working_memory/__init__.py` and
`.../task_memory/__init__.py`). They are not in the ownership table, but
every sibling test package under `packages/ai-parrot/tests/tools/` has one
and pytest's package-style collection needs them to avoid basename
collisions with later task modules. Deliberate, minimal, and recorded here.

### Notes for downstream tasks

- **There is no universal hook.** 9 direct catalog writes, 3 external
  catalog reads (the plan node reaches into `_catalog` directly), 5
  `render_context_history` call sites and 4 `from_ai_message` call sites.
  Design accordingly — §1.1 of the map.
- `tool_started` must be persisted before **four** distinct `[EXECUTED]`
  lines in `execute_tool`, not one (§1.3).
- `PlanToolNode._store` (`:347`) runs *after* dispatch returned, so the
  attempt receipt must be retained across that boundary or
  `producer_call_id` is lost (§1.4).
- Registration must run hashing in a thread and must never hold the
  catalog lock across it: the copy is cheap, the fingerprint is not.
