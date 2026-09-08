# TASK-3001: Inject task recall into budgeted Stage 2 rendering

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2988, TASK-2990
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2991, TASK-2992, TASK-2993 after prerequisites. Shared-file predecessors: TASK-2990; do not edit their files concurrently.
**Delivery**: B
**Spec acceptance**: AC1, AC10, AC13, AC14

---

## Context

Implements §2 Recall and Stage 2 of the approved specification. Delivery B establishes durable continuity; passing in-memory tests alone does not complete this work. Consume the committed contracts from TASK-2988, TASK-2990 before implementation.

## Scope

- Consume CompactionResult.stage2_needed at render time and selected task association to inject one transient deterministic recall block.
- Budget recall plus framing/calibration against available history tokens; recompute retained history allowance and preserve minimum verbatim requirements or decline with a diagnostic.
- Keep lifecycle telemetry, compaction kill switch, no-task behavior and no-double-inject/no-request-recall rules; never persist synthetic summary turns.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_stage2_task_recall.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.bots.abstract import AbstractBot  # packages/ai-parrot/src/parrot/bots/abstract.py:1742
from parrot.memory.compaction.tokens import get_default_counter, TokenCounter  # packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89
from parrot.memory.compaction.compact import compact_history  # packages/ai-parrot/src/parrot/memory/compaction/compact.py:143
from parrot.memory.compaction.models import ToolInvocation, ToolStatus, ContextBudget  # packages/ai-parrot/src/parrot/memory/compaction/models.py:46
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/bots/abstract.py:1742`**

```python
async def render_context_history(self, history: Optional[ConversationHistory]) -> Tuple[List[HistoryMessage], Optional[CompactionResult]]:
# save_conversation_turn at line 1909:
async def save_conversation_turn(self, user_id: str, session_id: str, turn: ConversationTurn, *, compaction: Optional[CompactionCommit] = None) -> None:
```

Rendering returns messages plus CompactionResult at 1793; memory_key_id at 1864 is the stable identity and save_conversation_turn remains the sole writer.

**`packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89`**

```python
def get_default_counter() -> TokenCounter:
# TokenCounter.count at line 35:
def count(self, text: str) -> int:
```

The existing fallback estimates UTF-8 bytes divided by four, minimum one for nonempty text; it is not a provider-token upper bound.

**`packages/ai-parrot/src/parrot/memory/compaction/compact.py:143`**

```python
def compact_history(history: ConversationHistory, budget: ContextBudget, *, policies: Optional[Dict[str, PrunePolicy]] = None, boundary_turn_id: Optional[str] = None, counter: Optional[TokenCounter] = None, calibration: float = 1.0, current_chatbot_id: Optional[str] = None, include_other_agents: bool = True) -> CompactionResult:
```

stage2_needed is computed as watermark_overflow or cum > available at 325.

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

- No task recall injection/turn-task context helper exists in the current bot.
- No deterministic task recall selector/cache exists in the counter module.
- No summary-provider registration callback exists; the task candidate must integrate at rendering.
- No call ID, CANCELLED/UNKNOWN enum members or task attribution fields exist on this model.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

This is Delivery B integration even though it uses the in-process service contracts.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/abstract.py:1742` — Rendering returns messages plus CompactionResult at 1793; memory_key_id at 1864 is the stable identity and save_conversation_turn remains the sole writer.
- `packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89` — The existing fallback estimates UTF-8 bytes divided by four, minimum one for nonempty text; it is not a provider-token upper bound.
- `packages/ai-parrot/src/parrot/memory/compaction/compact.py:143` — stage2_needed is computed as watermark_overflow or cum > available at 325.
- `packages/ai-parrot/src/parrot/memory/compaction/models.py:46` — ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.

## Acceptance Criteria

- [ ] History plus recall/framing fits configured available budget or injection is explicitly declined.
- [ ] Ordinary/streaming render paths receive at most one snapshot without instructing duplicate recall.
- [ ] Disabled compaction/no selected task preserves current history rendering and save behavior.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC1, AC10, AC13, AC14 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_stage2_task_recall.py -q`; retain output in `artifacts/logs/task-3001-tm-stage2-recall.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_combined_budget` | History plus recall/framing fits configured available budget or injection is explicitly declined. |
| `test_streaming_once` | Ordinary/streaming render paths receive at most one snapshot without instructing duplicate recall. |
| `test_kill_switch` | Disabled compaction/no selected task preserves current history rendering and save behavior. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-3001-tm-stage2-recall.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

Not completed. The implementing agent records completed-by, date, verification evidence, notes, and any approved deviations here when acceptance passes.
