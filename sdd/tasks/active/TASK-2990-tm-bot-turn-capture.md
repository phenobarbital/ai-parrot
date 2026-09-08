# TASK-2990: Wire bot turn context and single invocation persistence

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2984, TASK-2986, TASK-2989
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2991, TASK-2992, TASK-2993 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC1, AC4, AC11, AC13, AC14

---

## Context

Implements §2 Integration Points; Single Observer of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2984, TASK-2986, TASK-2989 before implementation.

## Scope

- Wire shared in-process task service/catalog/observer during async bot setup; derive TaskScope from stable memory_key_id and runtime user/session.
- Bracket all ordinary, streaming and structured entry points with context setup/reset, including early cancellation and explicit task selection after history loss.
- Feed captured ToolInvocation records to saved ConversationTurn exactly once; retain from_ai_message legacy fallback for unobserved turns and keep bot as sole history writer.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/memory/abstract.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_bot_task_context.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.bots.abstract import AbstractBot  # packages/ai-parrot/src/parrot/bots/abstract.py:1742
from parrot.bots.base import BaseBot  # packages/ai-parrot/src/parrot/bots/base.py:1147
from parrot.bots.agent import BasicAgent  # packages/ai-parrot/src/parrot/bots/agent.py:146
from parrot.memory.abstract import ConversationTurn, ConversationHistory  # packages/ai-parrot/src/parrot/memory/abstract.py:178
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

**`packages/ai-parrot/src/parrot/bots/base.py:1147`**

```python
# Existing calls in ordinary (1147) and streaming (1788) paths:
rendered_history, compaction_result = await self.render_context_history(conversation_history)
```

Both paths load history with chatbot_id=self.memory_key_id and render it before the provider call; inspect all other entry points before integrating context.

**`packages/ai-parrot/src/parrot/bots/agent.py:146`**

```python
async def configure(self, app=None) -> None:
```

configure awaits its parent and then wires tool namespaces; new async task-memory setup belongs in an enabled lifecycle path.

**`packages/ai-parrot/src/parrot/memory/abstract.py:178`**

```python
def from_ai_message(cls, *, user_message: str, response: "AIMessage", user_id: str, chatbot_id: str, context_used: Optional[str] = None, turn_id: Optional[str] = None, assistant_text: Optional[str] = None, error: Optional[str] = None) -> "ConversationTurn":
```

from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.

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
- No implicit ContextVar assignment in a child publishes a new parent value; task-session wiring is new work.
- No task-memory backend/sweeper factory is already wired into configure.
- No canonical task observer handoff or selected-task association behavior exists yet.
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

- `packages/ai-parrot/src/parrot/bots/abstract.py:1742` — Rendering returns messages plus CompactionResult at 1793; memory_key_id at 1864 is the stable identity and save_conversation_turn remains the sole writer.
- `packages/ai-parrot/src/parrot/bots/base.py:1147` — Both paths load history with chatbot_id=self.memory_key_id and render it before the provider call; inspect all other entry points before integrating context.
- `packages/ai-parrot/src/parrot/bots/agent.py:146` — configure awaits its parent and then wires tool namespaces; new async task-memory setup belongs in an enabled lifecycle path.
- `packages/ai-parrot/src/parrot/memory/abstract.py:178` — from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.
- `packages/ai-parrot/src/parrot/memory/compaction/models.py:46` — ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.

## Acceptance Criteria

- [ ] Ordinary/streaming/structured paths observe context with no leak after exceptions/cancellation.
- [ ] Captured calls appear once, not plus converted AIMessage.tool_calls; only save_conversation_turn persists.
- [ ] No new dependencies/network initialization or history changes when task memory is absent.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC1, AC4, AC11, AC13, AC14 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_bot_task_context.py -q`; retain output in `artifacts/logs/task-2990-tm-bot-turn-capture.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_entrypoints` | Ordinary/streaming/structured paths observe context with no leak after exceptions/cancellation. |
| `test_single_writer` | Captured calls appear once, not plus converted AIMessage.tool_calls; only save_conversation_turn persists. |
| `test_disabled` | No new dependencies/network initialization or history changes when task memory is absent. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2990-tm-bot-turn-capture.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

Not completed. The implementing agent records completed-by, date, verification evidence, notes, and any approved deviations here when acceptance passes.
