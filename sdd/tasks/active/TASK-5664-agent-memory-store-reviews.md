# TASK-5664: Scoped store review/citation API and durable lessons

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5662, TASK-5659, TASK-5654
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes atomic ReviewBackend.apply_review from TASK-5662; Consumes select_grade from TASK-5659; Consumes current_memory_scope from TASK-5654

## Context

Implement the bounded M2 slice of FEAT-892 revision 0.2. The owner's accepted
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

- Store-owned admission and durable lesson contents (`packages/ai-parrot/src/parrot/memory/episodic/store.py`).
- Runtime-bound citations and persist-before-ack lesson text (`packages/ai-parrot/src/parrot/memory/episodic/tools.py`).
- Version/scope admission and persisted explicit lessons (`packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/store.py` | MODIFY | Store-owned admission and durable lesson contents |
| `packages/ai-parrot/src/parrot/memory/episodic/tools.py` | MODIFY | Runtime-bound citations and persist-before-ack lesson text |
| `packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py` | CREATE | Version/scope admission and persisted explicit lessons |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.memory.agent_memory.runtime import current_memory_scope, current_memory_exposure
from parrot.memory.dynamics.models import MemoryCitation, ReviewReceipt, ReviewSignal
from parrot.memory.episodic.models import EpisodicMemory
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.episodic.tools import EpisodicMemoryToolkit
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/episodic/store.py:57`: `class EpisodicMemoryStore:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/tools.py:22`: `class EpisodicMemoryToolkit(AbstractToolkit):` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/models.py`: 214:class MemoryNamespace(BaseModel):
- `packages/ai-parrot/src/parrot/memory/episodic/store.py`: 57:class EpisodicMemoryStore:
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:179` — `EpisodicMemory.to_dict`: `def to_dict(self) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:191` — `EpisodicMemory.from_dict`: `def from_dict(cls, data: dict[str, Any]) -> EpisodicMemory:`
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:246` — `MemoryNamespace.build_filter`: `def build_filter(self) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:283` — `MemoryNamespace.redis_prefix`: `def redis_prefix(self) -> str:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:86` — `EpisodicMemoryStore.__init__`: `def __init__(self, backend: AbstractEpisodeBackend, embedding_provider: EpisodeEmbeddingProvider | None=None, reflection_engine: ReflectionEngine | None=None, redis_cache: EpisodeRedisCache | None=None, default_ttl_days: int=90, importance_scorer: ImportanceScorer | None=None, recall_strategy: RecallStrategy | None=None) -> None:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:106` — `EpisodicMemoryStore.record_episode`: `async def record_episode(self, namespace: MemoryNamespace, situation: str, action_taken: str, outcome: EpisodeOutcome, outcome_details: str | None=None, error_type: str | None=None, error_message: str | None=None, category: EpisodeCategory=EpisodeCategory.TOOL_EXECUTION, importance: int | None=None, related_tools: list[str] | None=None, related_entities: list[str] | None=None, metadata: dict[str, Any] | None=None, generate_reflection: bool=True, ttl_days: int | None=None) -> EpisodicMemory:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:235` — `EpisodicMemoryStore.record_tool_episode`: `async def record_tool_episode(self, namespace: MemoryNamespace, tool_name: str, tool_args: dict[str, Any], tool_result: Any, user_query: str | None=None) -> EpisodicMemory:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:377` — `EpisodicMemoryStore.recall_similar`: `async def recall_similar(self, query: str, namespace: MemoryNamespace, top_k: int=5, score_threshold: float=0.3, category: EpisodeCategory | None=None, include_failures_only: bool=False) -> list[EpisodeSearchResult]:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:436` — `EpisodicMemoryStore.get_failure_warnings`: `async def get_failure_warnings(self, namespace: MemoryNamespace, current_query: str | None=None, max_warnings: int=5) -> str:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:522` — `EpisodicMemoryStore.get_user_preferences`: `async def get_user_preferences(self, namespace: MemoryNamespace, limit: int=10) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:544` — `EpisodicMemoryStore.get_room_context`: `async def get_room_context(self, namespace: MemoryNamespace, limit: int=10, categories: list[EpisodeCategory] | None=None) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/episodic/tools.py:37` — `EpisodicMemoryToolkit.__init__`: `def __init__(self, store: EpisodicMemoryStore, namespace: MemoryNamespace, **kwargs) -> None:`
- `packages/ai-parrot/src/parrot/memory/episodic/tools.py:97` — `EpisodicMemoryToolkit.record_lesson`: `async def record_lesson(self, situation: str, lesson: str, category: str='decision', importance: int=5) -> str:`
- `packages/ai-parrot/src/parrot/memory/episodic/tools.py:153` — `EpisodicMemoryToolkit.get_warnings`: `async def get_warnings(self, context: str='') -> str:`

### Does NOT Exist

- `packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory.from_dict",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory.to_dict",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace.build_filter",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace.redis_prefix",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.__init__",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.get_failure_warnings",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.get_room_context",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.get_user_preferences",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.recall_similar",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_episode",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_tool_episode",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/tools.py#EpisodicMemoryToolkit",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/tools.py#EpisodicMemoryToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/tools.py#EpisodicMemoryToolkit.get_warnings",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/tools.py#EpisodicMemoryToolkit.record_lesson"
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

### `packages/ai-parrot/src/parrot/memory/episodic/store.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class EpisodicMemoryStore:' packages/ai-parrot/src/parrot/memory/episodic/store.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/store.py:57: class EpisodicMemoryStore:
from parrot.memory.dynamics.models import MemoryCitation, ReviewReceipt, ReviewSignal

# Add to EpisodicMemoryStore; keep existing recording signatures and default-off baseline behavior.
async def review(self, memory_ids: list[str], signal: ReviewSignal, *,
                 namespace: MemoryNamespace, exposure_id: str) -> list[ReviewReceipt]:
    """Resolve delivered versions, admit trusted evidence and apply each review durably once."""
    # FILL IN: scope -> exposure -> evidence -> attribution -> grade -> transaction — AC11/AC12.
    raise NotImplementedError

async def cite(self, memory_ids: list[str], *, namespace: MemoryNamespace,
               exposure_id: str) -> MemoryCitation:
    """Bind only delivered versions; acknowledging a citation never reinforces state."""
    # FILL IN: subset checks and non-leaking rejection — AC11.
    raise NotImplementedError
```

**Why:** The store is the authority for durable admission; changing a returned lesson object after persistence would otherwise lose explicit lesson text.

### `packages/ai-parrot/src/parrot/memory/episodic/tools.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class EpisodicMemoryToolkit(AbstractToolkit):' packages/ai-parrot/src/parrot/memory/episodic/tools.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/tools.py:22: class EpisodicMemoryToolkit(AbstractToolkit):
from parrot.memory.agent_memory.runtime import current_memory_scope, current_memory_exposure

# Add to EpisodicMemoryToolkit:
async def cite_memory(self, episode_ids: list[str]) -> str:
    """Cite within the runtime-bound delivered exposure without selecting a grade."""
    # FILL IN: resolve scope and current_memory_exposure; reject absence/cross-scope refs — AC11.
    raise NotImplementedError

# Fix record_lesson so explicit reflection/lesson text enters the transaction before persistence,
# rather than mutating only the returned episode. Preserve the public tool argument contract.
```

**Why:** The store is the authority for durable admission; changing a returned lesson object after persistence would otherwise lose explicit lesson text.

### `packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py` (CREATE)

```python
"""Behavioral acceptance tests for Scoped store review/citation API and durable lessons."""
import pytest

def test_cite_does_not_reinforce() -> None:
    """Verify cite does not reinforce."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_review_admission_and_idempotency() -> None:
    """Verify review admission and idempotency."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_lesson_text_persisted_before_ack() -> None:
    """Verify lesson text persisted before ack."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** The store is the authority for durable admission; changing a returned lesson object after persistence would otherwise lose explicit lesson text.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/episodic/store.py` — Store-owned admission and durable lesson contents; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/episodic/tools.py` — Runtime-bound citations and persist-before-ack lesson text; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py` — Version/scope admission and persisted explicit lessons; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC11: cite/recall alone changes no earned state; non-delivered/trimmed/cross-scope refs cannot be reviewed.
- [ ] AC09/AC12: explicit lesson text survives real-store reopen before success is returned; no-signal conversations stay PARTIAL and tools are not re-recorded as response episodes.
- [ ] AC12: duplicate/revised/conflicting outcome IDs obey frozen transaction semantics and no exception is reported as an applied write.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py -q`

## Test Specification

- `cite_does_not_reinforce`: AC11: cite/recall alone changes no earned state; non-delivered/trimmed/cross-scope refs cannot be reviewed.
- `review_admission_and_idempotency`: AC09/AC12: explicit lesson text survives real-store reopen before success is returned; no-signal conversations stay PARTIAL and tools are not re-recorded as response episodes.
- `lesson_text_persisted_before_ack`: AC12: duplicate/revised/conflicting outcome IDs obey frozen transaction semantics and no exception is reported as an applied write.

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
