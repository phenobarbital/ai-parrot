# TASK-2971: Define bounded task models and configuration

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2970
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial prerequisite on the critical path; downstream tasks wait for its contract to be committed.
**Delivery**: A
**Spec acceptance**: AC2, AC7, AC11, AC12

---

## Context

Implements §2 Data Models of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2970 before implementation.

## Scope

- Define all task, step, policy, event, descriptor, binding, attribution and invocation-wrapper models listed in the spec; use UUID4 runtime identities and UTC timestamps.
- Define typed payload variants, PlanChanges operations, domain errors and limits; count serialized UTF-8 payload bytes rather than dictionary entries.
- Define TaskMemoryConfig and TASK_MEMORY_* defaults, including retention/capacity and explicit durable/best-effort modes; keep imports leaf-safe.
- Resolve request-local initial step labels to runtime IDs through an explicit command input representation without accepting model-authored scope.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/__init__.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/models.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/config.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_models.py` | CREATE | Task-specific verification / fixtures |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/__init__.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from pydantic import BaseModel, Field  # packages/ai-parrot/src/parrot/tools/working_memory/models.py:7
from parrot.memory.compaction.models import ToolInvocation, ToolStatus, ContextBudget  # packages/ai-parrot/src/parrot/memory/compaction/models.py:46
from pydantic import BaseModel, Field  # packages/ai-parrot/pyproject.toml:54
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/models.py:7`**

```python
# Existing input model at line 268:
class GetResultInput(BaseModel):
    key: str
    max_length: int
    include_raw: bool
```

OperationSpecInput begins at 104; GetResultInput default max_length=500 and include_raw=False. Existing Pydantic import is at line 7.

**`packages/ai-parrot/src/parrot/memory/compaction/models.py:46`**

```python
class ToolInvocation:
    tool_name: str
    input: Dict[str, Any]
    output: Optional[str]
    status: ToolStatus
```

ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.

**`packages/ai-parrot/pyproject.toml:54`**

```python
# Dependency declarations: Python >=3.11; pydantic ==2.12.5;
# pandas >=2.0.0; pyarrow >=25.0; orjson >=3.9;
# existing graphindex-postgres extra: asyncpg >=0.29.
```

Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

### Does NOT Exist

- No task-memory Pydantic models or PlanChanges command union exists at this commit.
- No call ID, CANCELLED/UNKNOWN enum members or task attribution fields exist on this model.
- No new qworker/ULID/task-memory dependency is authorized; do not assume stdlib uuid7 on Python 3.11.
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

- `packages/ai-parrot/src/parrot/tools/working_memory/models.py:7` — OperationSpecInput begins at 104; GetResultInput default max_length=500 and include_raw=False. Existing Pydantic import is at line 7.
- `packages/ai-parrot/src/parrot/memory/compaction/models.py:46` — ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.
- `packages/ai-parrot/pyproject.toml:54` — Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

## Acceptance Criteria

- [ ] Reject overlong strings, oversized collections/UTF-8 event payloads and unknown enum/schema versions.
- [ ] All event variants round-trip without losing typed fields; derived active/ready lists are not duplicate persisted state.
- [ ] Defaults match 64 MiB snapshots, 512 MiB cache, 2,000,000-byte rehydration, and stated retention thresholds.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC2, AC7, AC11, AC12 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_models.py -q`; retain output in `artifacts/logs/task-2971-tm-domain-models.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_bounds` | Reject overlong strings, oversized collections/UTF-8 event payloads and unknown enum/schema versions. |
| `test_roundtrip` | All event variants round-trip without losing typed fields; derived active/ready lists are not duplicate persisted state. |
| `test_defaults` | Defaults match 64 MiB snapshots, 512 MiB cache, 2,000,000-byte rehydration, and stated retention thresholds. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2971-tm-domain-models.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence

- `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_models.py -q`
  → **55 passed**. Log: `artifacts/logs/task-2971-tm-domain-models.log`.
- `ruff check` clean; `black --line-length 120 --target-version py312` and
  `isort` applied to all four files.
- Regressions run: `tests/tools/compression`, `tests/tools/execution_plan`,
  `tests/bots/flows/plan` → **284 passed, 6 skipped, 2 failed**.

### Pre-existing failures (NOT caused by this task)

Both reproduce identically on unmodified `dev` in the main checkout when
the same directory set is run together, and both pass in isolation — they
are cross-module test-ordering pollution that predates this branch:

- `tools/compression/test_e2e.py::test_execute_tool_public_signature_unchanged`
  (also fails on baseline when run alone).
- `bots/flows/plan/test_plan.py::test_tool_not_registered_on_import`
  (passes alone, fails on baseline in the combined run).

Reported as a pre-existing condition, not as a passed acceptance case.

### Acceptance mapping

| Criterion | Evidence |
|---|---|
| Reject overlong strings / oversized collections / oversized UTF-8 payloads / unknown enums and schema versions | `test_bounds_*` (16 focused cases + aggregate `test_bounds`) |
| Event variants round-trip; derived lists are not duplicate persisted state | `test_roundtrip_every_payload_variant` (9 parametrized), `test_roundtrip_derived_lists_are_not_persisted` |
| Defaults: 64 MiB snapshot, 512 MiB cache, 2,000,000-byte rehydration, retention thresholds | `test_defaults_byte_budgets`, `test_defaults_retention_thresholds` |
| AC2 (identical semantics both stores) | Shared vocabulary + pure derived readiness rules; store parity is exercised by TASK-2978/2995 |
| AC7 (replanning, partial plans, completion gate) | `test_roundtrip_completion_guard`, `test_roundtrip_derived_readiness_rules` |
| AC11 (scope isolation) | `TaskScope.cache_key()` percent-encodes components so no value can forge another scope's key; `TaskScope.matches()` |
| AC12 (retention/limits auditable) | `Limits`, `TaskMemoryConfig` retention table, `is_journal_exhausted(reserved=...)`, `EventType.is_reserved` |

### Design decisions worth flagging downstream

1. **`durable=True` is accepted, not rejected.** An earlier draft raised at
   construction time because Delivery A has no PostgreSQL store. That was
   reverted: it would force the Delivery B tasks (TASK-2994+) to edit a
   file they do not own. The flag now expresses intent, and the *store
   factory* performs the lazy `asyncpg` availability check and raises
   `TaskMemoryUnavailable`. Configuration validation does not guess at
   backend availability.
2. **Typed payloads are grouped into nine families**, not one class per
   event type. `PAYLOAD_FAMILY_BY_EVENT` maps every `EventType` to its
   family and `JournalEvent` rejects a mismatch as a `ReducerError`.
   `test_roundtrip_every_event_type_has_a_payload_family` fails loudly if
   a future event type is added without a family.
3. **`InvocationRecord.invocation` is typed `Optional[Any]`** and holds the
   existing compaction `ToolInvocation` dataclass. Re-declaring it as a
   Pydantic model would have broken leaf-safety and duplicated the
   compaction serializer; the spec requires preserving it unchanged as the
   shared normalized payload.
4. **`ArtifactDescriptor._check_verifiability`** refuses `evidence_verifiable`
   without a fingerprint or for an unsupported kind. This is the model-level
   enforcement of TASK-2970's finding that pandas silently repr-hashes
   unhashable object cells, so a *computable* fingerprint over nested
   mutable data is not integrity proof.
5. **`CallOutcome.NOT_EXECUTED`** was added for the manager's early returns
   (unknown tool, guard denial, authorization required). The spec requires
   those be classified as unsuccessful dispatch with `executed=False`
   rather than pretending a tool body ran; `ToolCallPayload.executed`
   carries the same fact into the journal.
6. **Leaf-safety is tested by loading `models.py` directly from its path**
   in a subprocess, not by importing it through the package — importing by
   package path legitimately executes the parent `__init__` modules, which
   do import the toolkit. What must stay leaf-safe is the module itself.

### Notes

Test-running in this worktree requires
`PYTHONPATH=<worktree>/packages/ai-parrot/src`, because the shared venv
resolves `parrot` from the *main* checkout. The compiled Cython/Rust
extensions (`parrot/utils/types*.so`, `parrot/utils/parsers/toml*.so`,
`yaml_rs*.so`) were copied from the main checkout into the worktree; they
are gitignored build artifacts and are not part of this commit.
