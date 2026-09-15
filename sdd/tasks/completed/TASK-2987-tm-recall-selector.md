# TASK-2987: Implement deterministic bounded recall selection

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2972, TASK-2974
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2975, TASK-2976, TASK-2977 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC1, AC10

---

## Context

Implements §2 Recall and Stage 2 of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2972, TASK-2974 before implementation.

## Scope

- Build a pure snapshot selector over captured projection, event/descriptor units, availability, arguments and counter/calibration.
- Apply required identity/goal/constraint/blocker reserve and spec priority order; serialize canonical complete JSON and remove optional units to fit.
- Include truncation counts and asserted/stale/unknown labels; enforce max_tokens and recent-call argument bounds, budget_too_small and heuristic byte policy.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/recall.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_recall_selector.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.memory.compaction.tokens import get_default_counter, TokenCounter  # packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89
from parrot.memory.compaction.models import ToolInvocation, ToolStatus, ContextBudget  # packages/ai-parrot/src/parrot/memory/compaction/models.py:46
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89`**

```python
def get_default_counter() -> TokenCounter:
# TokenCounter.count at line 35:
def count(self, text: str) -> int:
```

The existing fallback estimates UTF-8 bytes divided by four, minimum one for nonempty text; it is not a provider-token upper bound.

**`packages/ai-parrot/src/parrot/memory/compaction/models.py:46`**

```python
class ToolInvocation:
    tool_name: str
    input: Dict[str, Any]
    output: Optional[str]
    status: ToolStatus
```

ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.

### Does NOT Exist

- No deterministic task recall selector/cache exists in the counter module.
- No call ID, CANCELLED/UNKNOWN enum members or task attribution fields exist on this model.
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

- `packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89` — The existing fallback estimates UTF-8 bytes divided by four, minimum one for nonempty text; it is not a provider-token upper bound.
- `packages/ai-parrot/src/parrot/memory/compaction/models.py:46` — ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.

## Acceptance Criteria

- [ ] Identical captured inputs yield exact identical bytes including counters.
- [ ] Count envelope/truncation overhead; required-only overflow returns measured minimum; Unicode heuristic obeys byte ceiling.
- [ ] Unresolved outcomes precede optional recent success/artifact units and truncation counts match omissions.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC1, AC10 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_recall_selector.py -q`; retain output in `artifacts/logs/task-2987-tm-recall-selector.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_determinism` | Identical captured inputs yield exact identical bytes including counters. |
| `test_budget` | Count envelope/truncation overhead; required-only overflow returns measured minimum; Unicode heuristic obeys byte ceiling. |
| `test_priority` | Unresolved outcomes precede optional recent success/artifact units and truncation counts match omissions. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2987-tm-recall-selector.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- `uv run pytest .../test_recall_selector.py -q` → **25 passed** (first run).
  Log: `artifacts/logs/task-2987-tm-recall-selector.log`.
- `ruff`/`black --line-length 120 --target-version py312`/`isort` clean.

### Acceptance mapping

| Criterion | Evidence |
|---|---|
| Identical captured inputs yield exact identical bytes including counters | `test_determinism_identical_inputs_yield_identical_bytes`, `test_determinism_serialization_is_canonical` |
| Count envelope/truncation overhead | `test_budget_counts_envelope_and_truncation_overhead` — the reported size IS the size of the whole payload, truncation block included |
| Required-only overflow returns measured minimum | `test_budget_required_only_overflow_returns_measured_minimum` — and asserts retrying at exactly that number succeeds |
| Unicode heuristic obeys byte ceiling | `test_budget_unicode_obeys_the_byte_ceiling` (3-byte characters) |
| Unresolved outcomes precede optional units | `test_priority_unresolved_survive_when_optional_units_are_dropped` |
| Truncation counts match omissions | `test_priority_truncation_counts_match_the_omissions` (arithmetic, per group) |
| AC1 | Identity/goal/constraints/blockers are required and never shed; evidence refs, unresolved failures and truthful completion sources all present |
| AC10 | Purity AST scan, `test_determinism_recall_never_appends`, no payload/arguments in output, bounded pages only |

### Design decisions worth flagging downstream

1. **`AvailabilitySnapshot` is an explicit input, not something recall
   discovers.** Availability changes with **no task event** — eviction,
   expiry, worker restart. Capturing it keeps determinism from collapsing
   into "expired content stays available forever at the same task
   sequence". Its `generation` is folded into both the payload and the
   cache key.
2. **`cache_key_parts` is returned by the selector**, so the caching layer
   (TASK-2988) cannot accidentally cache on too little. It covers scope,
   task, sequence, availability generation, tokenizer identity,
   calibration, arguments and the recall schema version.
3. **Out-of-range arguments raise, they do not clamp.** A silently clamped
   nonsensical request hides a caller bug behind a plausible answer.
4. **Calibrated counts round UP.** Under-reporting is the failure that
   overflows a context window, so the rounding direction is deliberate.
5. **`budget_too_small` returns no partial payload**, and its
   `required_min_tokens` is verified sufficient by an actual retry in the
   test — otherwise it would be an unfalsifiable number.
6. **Shed order puts unresolved outcomes LAST** among optional units. They
   are the single most actionable thing a recovering agent needs.
7. **Only a call's own terminal event resolves it.** `_unresolved_calls`
   pops by `call_id`; an unrelated success cannot clear an unknown
   outcome, which would amount to quietly deciding an uncertain external
   effect had succeeded.
8. **A stale REPL binding sets `binding_invalid` but leaves
   `availability` untouched** — the durable payload did not disappear,
   only the binding did.
9. **`omissions` maps to `Optional[bool]`**, where `None` means *unknown*
   (a custom store with no availability probe). Unknown is reported as
   unknown, never optimistically as present.
10. **Recall carries no arguments, rows or raw output.** A test asserts
    the absence of `input`/`arguments`/`output`/`result`/`payload` keys so
    recall cannot drift into being a data channel.

### Note for TASK-2988 (recall cache and probes)

`select_recall()` is synchronous and pure by design. The caching layer,
the bounded reads that build `RecallInputs`, and the additive scoped
omission-availability probe all belong to TASK-2988; this module
deliberately performs none of them. The `omissions` field and the
`needs_task_selection()` helper are the seams provided for it.
