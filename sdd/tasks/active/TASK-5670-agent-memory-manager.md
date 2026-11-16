# TASK-5670: Unified scoped preparation and event ownership

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5669, TASK-5668, TASK-5665, TASK-5666
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes assemble_candidates from TASK-5669; Consumes UserMemoryStore and suppression semantics from TASK-5668; Consumes scope-correct episodic routes and store review/event behavior from TASK-5665; Consumes extract_user_knowledge from TASK-5666

## Context

Implement the bounded A1 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Release Preconditions

No additional owner decision is required beyond completed dependency contracts. Do not bypass a blocked dependency.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- One manager path across enabled capabilities (`packages/ai-parrot/src/parrot/memory/unified/manager.py`).
- Real manager capability, tenant and event ownership tests (`packages/ai-parrot/tests/memory/unified/test_manager.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/unified/manager.py` | MODIFY | One manager path across enabled capabilities |
| `packages/ai-parrot/tests/memory/unified/test_manager.py` | MODIFY | Real manager capability, tenant and event ownership tests |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.memory.agent_memory.models import MemoryEvent, MemoryRequestScope, MemoryWriteReceipt
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.unified.context import ContextAssembler
from parrot.memory.unified.manager import UnifiedMemoryManager
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/unified/manager.py:53`: `class UnifiedMemoryManager:` (exact-line occurrence count 1).
- `packages/ai-parrot/tests/memory/unified/test_manager.py:47`: `class TestUnifiedMemoryManager:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/store.py`: 57:class EpisodicMemoryStore:
- `packages/ai-parrot/src/parrot/memory/unified/context.py`: 17:class ContextAssembler:
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:86` — `EpisodicMemoryStore.__init__`: `def __init__(self, backend: AbstractEpisodeBackend, embedding_provider: EpisodeEmbeddingProvider | None=None, reflection_engine: ReflectionEngine | None=None, redis_cache: EpisodeRedisCache | None=None, default_ttl_days: int=90, importance_scorer: ImportanceScorer | None=None, recall_strategy: RecallStrategy | None=None) -> None:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:106` — `EpisodicMemoryStore.record_episode`: `async def record_episode(self, namespace: MemoryNamespace, situation: str, action_taken: str, outcome: EpisodeOutcome, outcome_details: str | None=None, error_type: str | None=None, error_message: str | None=None, category: EpisodeCategory=EpisodeCategory.TOOL_EXECUTION, importance: int | None=None, related_tools: list[str] | None=None, related_entities: list[str] | None=None, metadata: dict[str, Any] | None=None, generate_reflection: bool=True, ttl_days: int | None=None) -> EpisodicMemory:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:235` — `EpisodicMemoryStore.record_tool_episode`: `async def record_tool_episode(self, namespace: MemoryNamespace, tool_name: str, tool_args: dict[str, Any], tool_result: Any, user_query: str | None=None) -> EpisodicMemory:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:377` — `EpisodicMemoryStore.recall_similar`: `async def recall_similar(self, query: str, namespace: MemoryNamespace, top_k: int=5, score_threshold: float=0.3, category: EpisodeCategory | None=None, include_failures_only: bool=False) -> list[EpisodeSearchResult]:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:436` — `EpisodicMemoryStore.get_failure_warnings`: `async def get_failure_warnings(self, namespace: MemoryNamespace, current_query: str | None=None, max_warnings: int=5) -> str:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:522` — `EpisodicMemoryStore.get_user_preferences`: `async def get_user_preferences(self, namespace: MemoryNamespace, limit: int=10) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:544` — `EpisodicMemoryStore.get_room_context`: `async def get_room_context(self, namespace: MemoryNamespace, limit: int=10, categories: list[EpisodeCategory] | None=None) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/unified/context.py:41` — `ContextAssembler.__init__`: `def __init__(self, config: MemoryConfig | None=None) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/context.py:49` — `ContextAssembler.assemble`: `def assemble(self, episodic_warnings: str='', relevant_skills: str='', conversation: str='', semantic_knowledge: str='') -> MemoryContext:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:83` — `UnifiedMemoryManager.__init__`: `def __init__(self, namespace: MemoryNamespace, conversation_memory: Optional[ConversationMemory]=None, episodic_store: Optional[EpisodicMemoryStore]=None, skill_registry: Optional[Any]=None, config: Optional[MemoryConfig]=None, cross_domain_router: Optional[CrossDomainRouter]=None, brain: Optional[BrainStore]=None, org_brain: Optional[BrainStore]=None) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:109` — `UnifiedMemoryManager.configure`: `async def configure(self, **kwargs: Any) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:124` — `UnifiedMemoryManager.cleanup`: `async def cleanup(self) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:139` — `UnifiedMemoryManager.get_context_for_query`: `async def get_context_for_query(self, query: str, user_id: str, session_id: str) -> MemoryContext:`
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:178` — `UnifiedMemoryManager.record_interaction`: `async def record_interaction(self, query: str, response: Any, tool_calls: list[Any], user_id: str, session_id: str) -> None:`

### Does NOT Exist

- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/unified/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_manager.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.__init__",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.get_failure_warnings",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.get_room_context",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.get_user_preferences",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.recall_similar",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_episode",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_tool_episode",
    "sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler",
    "sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler.__init__",
    "sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler.assemble",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.__init__",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.cleanup",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.configure",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.get_context_for_query",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.record_interaction",
    "sym:packages/ai-parrot/tests/memory/unified/test_manager.py#TestUnifiedMemoryManager"
  ]
}
```

## Implementation Notes

Use async I/O, strict hints, Pydantic v2 and Google docstrings; log through self.logger or
the module logger. Format Python with black (120) and run scoped ruff. Keep test logs under
artifacts/logs. All DB/process fixtures are isolated; no shared DDL or dependency mutation is
authorized. User explicitly confirmed that the new AgentMemoryToolkit remains in core at
parrot.memory.agent_memory; do not move it into parrot_tools.

## Implementation Blueprint

### Steps (in order)

1. Verify release preconditions and dependency contracts — unresolved evidence must not become invented implementation policy.
2. Recheck the exact anchors and imports below after dependencies land — overlapping writers deliberately run in sequence.
3. Apply each per-file block and complete its bounded FILL IN items — preserve public contracts outside this task's scope.
4. Implement the behavioral cases below with real temporary stores where persistence matters — mocks alone cannot prove durability.
5. Run the narrow validation commands and scoped style checks — do not mark missing backend evidence as a passing persistence test.

### `packages/ai-parrot/src/parrot/memory/unified/manager.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class UnifiedMemoryManager:' packages/ai-parrot/src/parrot/memory/unified/manager.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/unified/manager.py:53: class UnifiedMemoryManager:
from parrot.memory.agent_memory.models import MemoryEvent, MemoryRequestScope, MemoryWriteReceipt

# Add to UnifiedMemoryManager; keep get_context_for_query and record_interaction signatures.
async def prepare_context(self, query: str, *, scope: MemoryRequestScope) -> MemoryContext:
    """Retrieve enabled supplementary capabilities concurrently under immutable request scope."""
    # FILL IN: typed candidates and one assembler; agent path disables conversation retrieval — AC03.
    # Spec F9: prepare_context never calls _get_conversation (no chatbot_id, outside FEAT-886's hydration and
    #   deletion guard); standalone get_context_for_query keeps it unchanged.
    # Brain calls use injected brain_service.search(query, tenant_id, max_tokens), never BrainStore.
    raise NotImplementedError

async def record_event(self, event: MemoryEvent) -> MemoryWriteReceipt:
    """Route each event to its owning store without replaying tool attempts as response episodes."""
    # FILL IN: independent extraction, PARTIAL fallback and durable failure receipts — AC09/AC12.
    raise NotImplementedError

# Replace constructor brain/org_brain store arguments with an injected brain_service.
# Retain standalone text/history compatibility; do not change AbstractBot history ownership.
```

**Why:** A single event owner prevents double recording and keeps AbstractBot the sole conversation-history writer.

### `packages/ai-parrot/tests/memory/unified/test_manager.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class TestUnifiedMemoryManager:' packages/ai-parrot/tests/memory/unified/test_manager.py)
# MODIFY anchor at packages/ai-parrot/tests/memory/unified/test_manager.py:47: class TestUnifiedMemoryManager:
# Extend/migrate the anchored tests; retain unrelated coverage.
# FILL IN: AC03/AC09: one memory preparation and one event owner; no tool re-recording; no verified outcome records PARTIAL and creates no review.
# FILL IN: AC04/AC05: user-only works independently and concurrent requests never mutate manager namespace; tenant binds brain recall and recording consistently.
# FILL IN: AC15: constructor receives brain_service; no direct BrainStore/org-brain instance; text-only brain results never imply versioned review evidence.
# FILL IN: AC03: preserve get_context_for_query/record_interaction signatures and the unchanged M0 real-store regression.
```

**Why:** A single event owner prevents double recording and keeps AbstractBot the sole conversation-history writer.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/unified/manager.py` — One manager path across enabled capabilities; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/unified/test_manager.py` — Real manager capability, tenant and event ownership tests; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC03/AC09: one memory preparation and one event owner; no tool re-recording; no verified outcome records PARTIAL and creates no review.
- [ ] AC04/AC05: user-only works independently and concurrent requests never mutate manager namespace; tenant binds brain recall and recording consistently.
- [ ] AC15: constructor receives brain_service; no direct BrainStore/org-brain instance; text-only brain results never imply versioned review evidence.
- [ ] AC03: preserve get_context_for_query/record_interaction signatures and the unchanged M0 real-store regression.
- [ ] AC03 (F9): prepare_context returns no conversation section and never calls `_get_conversation`; standalone get_context_for_query still includes it.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/unified/test_manager.py -q`
- `pytest packages/ai-parrot/tests/memory/unified/test_manager_real_store.py -q`

## Test Specification

- `independent_capabilities_and_scoped_context`: AC03/AC09: one memory preparation and one event owner; no tool re-recording; no verified outcome records PARTIAL and creates no review.
- `single_partial_response_event`: AC04/AC05: user-only works independently and concurrent requests never mutate manager namespace; tenant binds brain recall and recording consistently.
- `brain_service_tenant_and_no_history_duplication`: AC15: constructor receives brain_service; no direct BrainStore/org-brain instance; text-only brain results never imply versioned review evidence.

Use deterministic clocks, runtime-derived identities and isolated temporary stores. Preserve
CancelledError. Use subprocesses for crash/multiprocess checks, never shared production data.

## Agent Instructions

1. Use the FEAT-892 worktree provisioned by sdd-start; never implement on dev.
2. Check every Depends-on task is done and each Release Preconditions item is met; blocked is not runnable.
3. Read the full spec and reverify this task's Codebase Contract; refresh stale evidence before editing.
4. Implement only declared files plus normal SDD state; preserve concurrent/unrelated changes.
5. Run validation, commit scoped implementation, and finalize with `parrot sdd task finalize`
   using real TaskCompletionEvidence and the exact implementation HEAD. Let finalization own
   the completion note and active-to-completed move; do not fabricate completion evidence.
