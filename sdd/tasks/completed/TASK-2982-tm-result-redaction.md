# TASK-2982: Implement typed result adapters and journal redaction

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2971
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2972, TASK-2973, TASK-2974 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC3, AC8, AC11

---

## Context

Implements §2 Observer; Retention and Redaction of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2971 before implementation.

## Scope

- Classify ToolResult envelopes, working-memory error dictionaries and plan partial/error manifests before payload reduction; ordinary values succeed absent typed failures.
- Normalize using Stage 0 and separately redact secret keys, errors, nested arguments and configured sensitive fields before journal/offload.
- Bound serialized payloads to 8 KiB; omit full code, rows and credentials; never infer success by parsing free text.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/adapters.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/redaction.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_result_adapters.py` | CREATE | Task-specific verification / fixtures |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_journal_redaction.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.memory.compaction.normalize import normalize_invocation  # packages/ai-parrot/src/parrot/memory/compaction/normalize.py:129
from parrot.memory.compaction.models import ToolInvocation, ToolStatus, ContextBudget  # packages/ai-parrot/src/parrot/memory/compaction/models.py:46
from parrot.bots.flows.plan.models import ArtifactRef, ExecutionManifest  # packages/ai-parrot/src/parrot/bots/flows/plan/models.py:413
from parrot.tools.manager import ToolManager  # packages/ai-parrot/src/parrot/tools/manager.py:1514
from parrot.tools.abstract import ToolResult  # packages/ai-parrot/src/parrot/tools/abstract.py:250
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/memory/compaction/normalize.py:129`**

```python
def normalize_invocation(inv: ToolInvocation) -> ToolInvocation:
```

Pure normalization canonicalizes JSON/text and condenses tracebacks, rebuilding the dataclass while preserving known fields.

**`packages/ai-parrot/src/parrot/memory/compaction/models.py:46`**

```python
class ToolInvocation:
    tool_name: str
    input: Dict[str, Any]
    output: Optional[str]
    status: ToolStatus
```

ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.

**`packages/ai-parrot/src/parrot/bots/flows/plan/models.py:413`**

```python
class ArtifactRef(BaseModel):
    node_id: str
    keys: List[str]
    status: Literal["ok", "skipped", "partial", "error"]
```

ArtifactRef carries alias keys, small facets/error status/bytes_stored; ExecutionManifest at 444 aggregates refs and nodes_failed.

**`packages/ai-parrot/src/parrot/tools/manager.py:1514`**

```python
async def execute_tool(self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional["PermissionContext"] = None, *, return_tool_result: bool = False) -> Any:
```

ToolDefinition and AbstractTool branches share guard ordering; full-result mode preserves envelopes. Clone shares tool instances while mutable manager state is distinct (2459–2489).

**`packages/ai-parrot/src/parrot/tools/abstract.py:250`**

```python
class ToolResult(BaseModel):
    success: bool
    status: str
    result: Any
    error: Optional[str]
```

Existing envelope fields at 253–266 include metadata, voice_text and display_data; outcome adapters must respect envelope semantics before reduction.

### Does NOT Exist

- No secret redactor exists in normalize_invocation; normalization cannot be treated as credential removal.
- No call ID, CANCELLED/UNKNOWN enum members or task attribution fields exist on this model.
- No immutable artifact_id@version references or domain-step mapping is currently encoded in the manifest.
- No general ToolExecutionObserver registry or task-memory call receipts exist; guard/compression hooks are not that API.
- No task-memory outcome classifier exists on ToolResult.
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

- `packages/ai-parrot/src/parrot/memory/compaction/normalize.py:129` — Pure normalization canonicalizes JSON/text and condenses tracebacks, rebuilding the dataclass while preserving known fields.
- `packages/ai-parrot/src/parrot/memory/compaction/models.py:46` — ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.
- `packages/ai-parrot/src/parrot/bots/flows/plan/models.py:413` — ArtifactRef carries alias keys, small facets/error status/bytes_stored; ExecutionManifest at 444 aggregates refs and nodes_failed.
- `packages/ai-parrot/src/parrot/tools/manager.py:1514` — ToolDefinition and AbstractTool branches share guard ordering; full-result mode preserves envelopes. Clone shares tool instances while mutable manager state is distinct (2459–2489).
- `packages/ai-parrot/src/parrot/tools/abstract.py:250` — Existing envelope fields at 253–266 include metadata, voice_text and display_data; outcome adapters must respect envelope semantics before reduction.

## Acceptance Criteria

- [ ] Denied/error/cancelled/partial results preserve outcome semantics; business dicts are not globally mistaken for envelopes.
- [ ] Nested credentials and error text are absent from serialized journal/omission input.
- [ ] Multibyte text and deep arguments obey the byte/depth caps without malformed JSON.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC3, AC8, AC11 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_result_adapters.py packages/ai-parrot/tests/tools/working_memory/task_memory/test_journal_redaction.py -q`; retain output in `artifacts/logs/task-2982-tm-result-redaction.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_typed_results` | Denied/error/cancelled/partial results preserve outcome semantics; business dicts are not globally mistaken for envelopes. |
| `test_secrets` | Nested credentials and error text are absent from serialized journal/omission input. |
| `test_payload_bytes` | Multibyte text and deep arguments obey the byte/depth caps without malformed JSON. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2982-tm-result-redaction.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker, delegated fork) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- **127 passed** (49 adapters + 78 redaction), all three required cases
  present (`test_typed_results`, `test_secrets`, `test_payload_bytes`).
- Whole suite: **448 passed**. Log: `artifacts/logs/task-2982-tm-result-redaction.log`.
- `ruff`/`black`/`isort` clean.

### Independently verified (not taken on trust)
- ReDoS fix: a 5,000-character scan now takes **2.1 ms** (was 774 ms).
- `Authorization: Bearer sk-...` no longer leaks the credential.
- `api_key`, `API_KEY`, `x-api-key`, `password`, `Token`, `authorization`
  all redacted; nested structures redacted; a credential inside a
  traceback redacted.
- `fp_`/`om_` digests survive intact — they are 16 chars, below the
  32-char long-hex floor. Redacting them would break evidence refs and
  omission lookups.

### CONTRACT CORRECTION
The task's "Does NOT Exist" section said no secret redactor exists in
`normalize_invocation`. Narrowly true but **misleading by omission**:
`packages/ai-parrot/src/parrot/security/redaction.py` already ships a
hardened one (`redact_text`, `redact_secrets`, `looks_sensitive_key`,
`OutputScrubber`; FEAT-252) — confirmed present.

Neither subsumes the other: it has JWT / AWS-key / DSN / long-hex
*value-shape* detection this one lacked; this one has configurable denied
keys, depth/byte caps, the 8 KiB journal ceiling and Stage-0 ordering. Its
four value-shape patterns were **adopted rather than imported**, because
importing `parrot.security` pulls numpy + asyncpg + redis (~1 s) onto the
journal write path.

**Follow-up for a maintainer**: consolidating the two redactors is
worthwhile but is a cross-cutting decision beyond this task's ownership,
so it is flagged here rather than made.

### Other decisions
1. **Structural typing, not `isinstance`** — avoids coupling task memory
   to `parrot.tools.abstract` and `parrot.bots.flows.plan.models`. The
   tests exercise the **real** `ToolResult`/`ArtifactRef`/
   `ExecutionManifest` so the shapes cannot drift apart silently.
2. **`looks_like_tool_result` excludes plain mappings.** A dict with
   `success`/`status`/`result` keys is business data; only a mapping whose
   `status` is a *recognised failure* is an error envelope
   (`{"status": "shipped"}` is a success).
3. **`timeout`/`pending` → `UNKNOWN`, not `ERROR`.** Both may already have
   produced an external effect; calling them failures invites the
   automatic retry of an uncertain effect the spec forbids.
4. **An unrecognised status never becomes a guessed failure** — it falls
   back to the `success` boolean, else success. Free text is never parsed.
5. **A documented limit is asserted, not hidden.** Free-form prose
   narration ("the api key was set to: X") is *not* caught, because
   matching a denied name across arbitrary whitespace would redact
   unrelated prose. The structured path is unaffected
   (`{"api key": ...}` *is* redacted). A test asserts the gap so it stays
   visible rather than being assumed closed.
