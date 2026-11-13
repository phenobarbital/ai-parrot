# TASK-5665: Scoped recall, shared ranking and cache invalidation

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5664, TASK-5659, TASK-5663
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes review-driven invalidation and overlapping store.py from TASK-5664; Consumes rank_candidates from TASK-5659; Consumes scope-correct backend retrieval from TASK-5663

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

- Consistent experiential candidate ranking (`packages/ai-parrot/src/parrot/memory/episodic/recall.py`).
- Full-scope version-aware keys and invalidation (`packages/ai-parrot/src/parrot/memory/episodic/cache.py`).
- Warnings/preferences/room routes share ranking and scope (`packages/ai-parrot/src/parrot/memory/episodic/store.py`).
- Scope, fallback, ranking and invalidation tests (`packages/ai-parrot/tests/memory/dynamics/test_recall.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/recall.py` | MODIFY | Consistent experiential candidate ranking |
| `packages/ai-parrot/src/parrot/memory/episodic/cache.py` | MODIFY | Full-scope version-aware keys and invalidation |
| `packages/ai-parrot/src/parrot/memory/episodic/store.py` | MODIFY | Warnings/preferences/room routes share ranking and scope |
| `packages/ai-parrot/tests/memory/dynamics/test_recall.py` | CREATE | Scope, fallback, ranking and invalidation tests |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.memory.episodic.cache import EpisodeRedisCache
from parrot.memory.episodic.recall import HybridBM25Strategy
from parrot.memory.episodic.recall import RecallStrategy
from parrot.memory.episodic.store import EpisodicMemoryStore
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/episodic/recall.py:22`: `class RecallStrategy(Protocol):` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/cache.py:25`: `class EpisodeRedisCache:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:57`: `class EpisodicMemoryStore:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/cache.py:51` — `EpisodeRedisCache._key`: `def _key(self, namespace: MemoryNamespace, suffix: str='') -> str:`
- `packages/ai-parrot/src/parrot/memory/episodic/cache.py:99` — `EpisodeRedisCache.get_recent`: `async def get_recent(self, namespace: MemoryNamespace, limit: int=10) -> list[EpisodicMemory] | None:`
- `packages/ai-parrot/src/parrot/memory/episodic/cache.py:123` — `EpisodeRedisCache.get_failures`: `async def get_failures(self, namespace: MemoryNamespace, limit: int=5) -> list[EpisodicMemory] | None:`
- `packages/ai-parrot/src/parrot/memory/episodic/cache.py:172` — `EpisodeRedisCache.invalidate`: `async def invalidate(self, namespace: MemoryNamespace) -> None:`
- `packages/ai-parrot/src/parrot/memory/episodic/recall.py:30` — `RecallStrategy.search`: `async def search(self, query: str, query_embedding: list[float], backend: AbstractEpisodeBackend, namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]:`
- `packages/ai-parrot/src/parrot/memory/episodic/recall.py:277` — `HybridBM25Strategy.search`: `async def search(self, query: str, query_embedding: list[float], backend: AbstractEpisodeBackend, namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:86` — `EpisodicMemoryStore.__init__`: `def __init__(self, backend: AbstractEpisodeBackend, embedding_provider: EpisodeEmbeddingProvider | None=None, reflection_engine: ReflectionEngine | None=None, redis_cache: EpisodeRedisCache | None=None, default_ttl_days: int=90, importance_scorer: ImportanceScorer | None=None, recall_strategy: RecallStrategy | None=None) -> None:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:106` — `EpisodicMemoryStore.record_episode`: `async def record_episode(self, namespace: MemoryNamespace, situation: str, action_taken: str, outcome: EpisodeOutcome, outcome_details: str | None=None, error_type: str | None=None, error_message: str | None=None, category: EpisodeCategory=EpisodeCategory.TOOL_EXECUTION, importance: int | None=None, related_tools: list[str] | None=None, related_entities: list[str] | None=None, metadata: dict[str, Any] | None=None, generate_reflection: bool=True, ttl_days: int | None=None) -> EpisodicMemory:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:235` — `EpisodicMemoryStore.record_tool_episode`: `async def record_tool_episode(self, namespace: MemoryNamespace, tool_name: str, tool_args: dict[str, Any], tool_result: Any, user_query: str | None=None) -> EpisodicMemory:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:377` — `EpisodicMemoryStore.recall_similar`: `async def recall_similar(self, query: str, namespace: MemoryNamespace, top_k: int=5, score_threshold: float=0.3, category: EpisodeCategory | None=None, include_failures_only: bool=False) -> list[EpisodeSearchResult]:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:436` — `EpisodicMemoryStore.get_failure_warnings`: `async def get_failure_warnings(self, namespace: MemoryNamespace, current_query: str | None=None, max_warnings: int=5) -> str:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:522` — `EpisodicMemoryStore.get_user_preferences`: `async def get_user_preferences(self, namespace: MemoryNamespace, limit: int=10) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:544` — `EpisodicMemoryStore.get_room_context`: `async def get_room_context(self, namespace: MemoryNamespace, limit: int=10, categories: list[EpisodeCategory] | None=None) -> list[EpisodicMemory]:`

### Does NOT Exist

- `packages/ai-parrot/tests/memory/dynamics/test_recall.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/recall.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/cache.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_recall.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/cache.py#EpisodeRedisCache",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/cache.py#EpisodeRedisCache._key",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/cache.py#EpisodeRedisCache.get_failures",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/cache.py#EpisodeRedisCache.get_recent",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/cache.py#EpisodeRedisCache.invalidate",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/recall.py#HybridBM25Strategy.search",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/recall.py#RecallStrategy",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/recall.py#RecallStrategy.search",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.__init__",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.get_failure_warnings",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.get_room_context",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.get_user_preferences",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.recall_similar",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_episode",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_tool_episode"
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

### `packages/ai-parrot/src/parrot/memory/episodic/recall.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class RecallStrategy(Protocol):' packages/ai-parrot/src/parrot/memory/episodic/recall.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/recall.py:22: class RecallStrategy(Protocol):
# Consistent experiential candidate ranking.
# FILL IN: AC05: cache keys and every recent/failure/room/legacy-preference route include full relevant scope; invalidation follows committed version/state changes.
# FILL IN: AC14: apply one shared rank policy before text formatting across experiential routes; preserve raw similarity and deterministic ties.
# FILL IN: AC14: SDD fallback runs without a paid embedding service; user facts use their own validity policy and are never FSRS-decayed here.
```

**Why:** Complete scope/version cache keys and commit-driven invalidation keep retrieval consistent with corrected or reviewed state.

### `packages/ai-parrot/src/parrot/memory/episodic/cache.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class EpisodeRedisCache:' packages/ai-parrot/src/parrot/memory/episodic/cache.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/cache.py:25: class EpisodeRedisCache:
# Full-scope version-aware keys and invalidation.
# FILL IN: AC05: cache keys and every recent/failure/room/legacy-preference route include full relevant scope; invalidation follows committed version/state changes.
# FILL IN: AC14: apply one shared rank policy before text formatting across experiential routes; preserve raw similarity and deterministic ties.
# FILL IN: AC14: SDD fallback runs without a paid embedding service; user facts use their own validity policy and are never FSRS-decayed here.
```

**Why:** Complete scope/version cache keys and commit-driven invalidation keep retrieval consistent with corrected or reviewed state.

### `packages/ai-parrot/src/parrot/memory/episodic/store.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class EpisodicMemoryStore:' packages/ai-parrot/src/parrot/memory/episodic/store.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/store.py:57: class EpisodicMemoryStore:
# Warnings/preferences/room routes share ranking and scope.
# FILL IN: AC05: cache keys and every recent/failure/room/legacy-preference route include full relevant scope; invalidation follows committed version/state changes.
# FILL IN: AC14: apply one shared rank policy before text formatting across experiential routes; preserve raw similarity and deterministic ties.
# FILL IN: AC14: SDD fallback runs without a paid embedding service; user facts use their own validity policy and are never FSRS-decayed here.
```

**Why:** Complete scope/version cache keys and commit-driven invalidation keep retrieval consistent with corrected or reviewed state.

### `packages/ai-parrot/tests/memory/dynamics/test_recall.py` (CREATE)

```python
"""Behavioral acceptance tests for Scoped recall, shared ranking and cache invalidation."""
import pytest

def test_cache_full_scope_and_invalidation() -> None:
    """Verify cache full scope and invalidation."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_ranking_consistent_across_routes() -> None:
    """Verify ranking consistent across routes."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_offline_fallback_no_embedding_provider() -> None:
    """Verify offline fallback no embedding provider."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Complete scope/version cache keys and commit-driven invalidation keep retrieval consistent with corrected or reviewed state.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/episodic/recall.py` — Consistent experiential candidate ranking; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/episodic/cache.py` — Full-scope version-aware keys and invalidation; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/episodic/store.py` — Warnings/preferences/room routes share ranking and scope; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_recall.py` — Scope, fallback, ranking and invalidation tests; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC05: cache keys and every recent/failure/room/legacy-preference route include full relevant scope; invalidation follows committed version/state changes.
- [ ] AC14: apply one shared rank policy before text formatting across experiential routes; preserve raw similarity and deterministic ties.
- [ ] AC14: SDD fallback runs without a paid embedding service; user facts use their own validity policy and are never FSRS-decayed here.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_recall.py -q`

## Test Specification

- `cache_full_scope_and_invalidation`: AC05: cache keys and every recent/failure/room/legacy-preference route include full relevant scope; invalidation follows committed version/state changes.
- `ranking_consistent_across_routes`: AC14: apply one shared rank policy before text formatting across experiential routes; preserve raw similarity and deterministic ties.
- `offline_fallback_no_embedding_provider`: AC14: SDD fallback runs without a paid embedding service; user facts use their own validity policy and are never FSRS-decayed here.

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
