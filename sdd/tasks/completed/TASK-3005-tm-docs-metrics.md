# TASK-3005: Document task memory operations and record acceptance metrics

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3001, TASK-3004
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial verification gate: wait for all dependencies and run without concurrent edits to production files exercised by the checks.
**Delivery**: B
**Spec acceptance**: AC15, AC16

---

## Context

Implements §5 AC15–AC16; §7 dependencies of the approved specification. Delivery B establishes durable continuity; passing in-memory tests alone does not complete this work. Consume the committed contracts from TASK-3001, TASK-3004 before implementation.

## Scope

- Document all task tools, explicit task selection, completion sources, ResultPolicy, safe REPL loads, configuration, migration/rollback and recovery operator actions.
- Explain Delivery A/B guarantees, unknown outcomes, association repair, strict serialization and retention/archive limitations; preserve OQ defaults and measured cap decision.
- Record recall tokens/build time, observer overhead, invalid-ref rate, repeated-operation counts and snapshot/hash distributions using reproducible fixtures; do not invent latency SLOs.
- Link actual focused/integration regression evidence and make provisioning/skipped test status explicit.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/memory/recoverable-task-memory.md` | CREATE | Documented deliverable |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/bench_task_memory.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from pydantic import BaseModel, Field  # packages/ai-parrot/pyproject.toml:54
from parrot.memory.compaction.tokens import get_default_counter, TokenCounter  # packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89
from parrot.tools.working_memory import WorkingMemoryToolkit  # packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259
from parrot.interfaces.file import FileManagerInterface  # packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/pyproject.toml:54`**

```python
# Dependency declarations: Python >=3.11; pydantic ==2.12.5;
# pandas >=2.0.0; pyarrow >=25.0; orjson >=3.9;
# existing graphindex-postgres extra: asyncpg >=0.29.
```

Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

**`packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89`**

```python
def get_default_counter() -> TokenCounter:
# TokenCounter.count at line 35:
def count(self, text: str) -> int:
```

The existing fallback estimates UTF-8 bytes divided by four, minimum one for nonempty text; it is not a provider-token upper bound.

**`packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259`**

```python
async def get_result(self, key: str, max_length: int = 500, include_raw: bool = False) -> dict:
```

Constructor at line 103 has session_id/max_rows/max_cols/tool_locals_registry/answer_memory/thread_offload_cells; store at 194 and store_result at 208 call synchronous catalog methods.

**`packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18`**

```python
# Verified export; external method signatures must be pinned in the Phase 0 task.
FileManagerInterface
```

Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.

### Does NOT Exist

- No new qworker/ULID/task-memory dependency is authorized; do not assume stdlib uuid7 on Python 3.11.
- No deterministic task recall selector/cache exists in the counter module.
- Task-memory opt-in constructor wiring and wm_* task tools do not exist at the verification commit.
- No versioned Parquet task store is provided by this compatibility shim; do not invent external stream/stat methods.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Final documentation/metrics gate; does not authorize new production features.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/pyproject.toml:54` — Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.
- `packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89` — The existing fallback estimates UTF-8 bytes divided by four, minimum one for nonempty text; it is not a provider-token upper bound.
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259` — Constructor at line 103 has session_id/max_rows/max_cols/tool_locals_registry/answer_memory/thread_offload_cells; store at 194 and store_result at 208 call synchronous catalog methods.
- `packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18` — Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.

## Acceptance Criteria

- [ ] Examples match implemented schemas and imports with no model-authored scope or unsafe retry advice.
- [ ] Measurements cover all AC16 metrics and 8/64/256 MiB inputs with environment and reproducible commands.
- [ ] Documentation links both delivery gates, migration checks and actual validation logs.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC15, AC16 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run python packages/ai-parrot/tests/tools/working_memory/task_memory/bench_task_memory.py`; retain output in `artifacts/logs/task-3005-tm-docs-metrics.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_docs_examples` | Examples match implemented schemas and imports with no model-authored scope or unsafe retry advice. |
| `test_metrics` | Measurements cover all AC16 metrics and 8/64/256 MiB inputs with environment and reproducible commands. |
| `test_traceability` | Documentation links both delivery gates, migration checks and actual validation logs. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-3005-tm-docs-metrics.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: sdd-worker (Claude Opus 5) — 2026-09-09
**Commit**: `c821f824d`

### What was built

`docs/memory/recoverable-task-memory.md` and
`bench_task_memory.py`. The benchmark imports the 8/64/256 MiB
measurement from `bench_snapshot_costs.py` rather than reimplementing
it, so that measurement keeps a single definition.

### The three required cases are checks, not prose

- **`test_docs_examples`** parses every python block in the document and
  resolves every `parrot.*` symbol it imports. A documentation example
  naming a symbol that does not exist is worse than no example — it is
  confidently wrong and a reader cannot tell without trying it. It also
  refuses documentation that advertises automatic retry of external
  effects, or that omits that Delivery A is non-durable.
- **`test_traceability`** asserts that every repo-relative path the
  document cites actually exists (11 of them), and that both delivery
  gates, the crash matrix and the migration are named. A traceability
  link to a file that is not there is not traceability.
- **`test_metrics`** records all five AC16 metrics and asserts the three
  required payload sizes are covered.

### Measured results (recorded, not asserted as SLOs)

| Metric | Result |
|---|---|
| Recall, 5 / 25 / 100 steps | 647 / 2 339 / 2 429 tokens; 0.6 / 2.0 / **313** ms median |
| Observer overhead | ≈48 µs per call capture-only; ≈197 µs journalled (in-memory) |
| Invalid-reference rate | 3/3 refused; 3/3 bare aliases rejected |
| Repeated operations after recovery | **0** |
| Fingerprint, DataFrame 8/64/256 MiB | 0.29 s / 2.32 s / **9.36 s** |
| Canonicalise JSON 8/64/256 MiB | peak RSS 32 MiB / 254 MiB / **1 014 MiB** |

Two findings are written into the document rather than smoothed over:

1. **Recall build time is markedly non-linear.** A 100-step plan costs
   roughly 150× a 25-step one while producing barely more output,
   because the selector is doing far more work deciding what to *drop*.
   The token cap still holds at every size — that part is asserted — but
   anyone running plans that large should measure rather than assume
   recall is cheap.
2. **The payload measurements justify the 64 MiB snapshot cap (D4).**
   Fingerprinting 256 MiB takes ~9.4 s and canonicalising 256 MiB of
   JSON peaks near 1 GB resident, because encoding holds the live value
   and its encoded form at once. Snapshotting that in RAM on a request
   path is not viable, which is exactly why the default stays 64 MiB.
   The spec asked for the cap decision to be recorded against
   measurement; this is that record.

### Verification evidence

- `python bench_task_memory.py` exits 0 with all three cases passing at
  the full 8/64/256 MiB. Log:
  `artifacts/logs/task-3005-tm-docs-metrics.log`.
- `tests/tools/working_memory`: **932 passed / 0 failed** with services;
  **842 passed / 90 skipped / 0 failed** without. Both figures were
  reproduced *before* being written into the document, and the document
  states plainly that the 90 skips are the durable cases and that a skip
  is never a pass.
- The documented enabling snippet was **executed**, not just parsed: it
  publishes 23 tools, 10 of them the task tools.
- `ruff` clean.

### Notes for the reviewer

- Two API assumptions were corrected against source while writing the
  benchmark: `DispatchOutcome.succeeded` is a property, not a
  constructor — the dispatcher's real call is
  `observer.finish(call, value=...)`; and a 100-step plan cannot be
  created in one `begin_task`, because a single journal event may not
  exceed the 8 KiB payload cap. The benchmark now builds large plans in
  batches, which is also how a real plan grows.
- One bug of my own: the journalled observer measurement first closed
  over a *different* store than the session's task lived in, so every
  append failed and the fail-closed observer refused to run the tool at
  all. The append is now bound to the same store.

### Approved deviations

None.
