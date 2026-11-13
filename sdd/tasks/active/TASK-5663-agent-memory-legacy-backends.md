# TASK-5663: Scope propagation through existing episodic backends

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5660
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes MemoryNamespace.model_id and accepted serialization/filter contract from TASK-5660

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

- Scoped SQL columns/filtering and compatibility (`packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py`).
- Scoped vector and recent/failure routes (`packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py`).
- Scoped serialized records and pre-limit filtering (`packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py`).
- Backend route contract and data migration checks (`packages/ai-parrot/tests/memory/dynamics/test_backend_scope.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py` | MODIFY | Scoped SQL columns/filtering and compatibility |
| `packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py` | MODIFY | Scoped vector and recent/failure routes |
| `packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py` | MODIFY | Scoped serialized records and pre-limit filtering |
| `packages/ai-parrot/tests/memory/dynamics/test_backend_scope.py` | CREATE | Backend route contract and data migration checks |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.memory.episodic.backends.faiss import FAISSBackend
from parrot.memory.episodic.backends.pgvector import PgVectorBackend
from parrot.memory.episodic.backends.redis_vector import RedisVectorBackend
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py:66`: `class PgVectorBackend:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py:145`: `class RedisVectorBackend:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py:54`: `class FAISSBackend:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py:111` — `FAISSBackend.store`: `async def store(self, episode: EpisodicMemory) -> str:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py:144` — `FAISSBackend.search_similar`: `async def search_similar(self, embedding: list[float], namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py:199` — `FAISSBackend.get_recent`: `async def get_recent(self, namespace_filter: dict[str, Any], limit: int=10, since: datetime | None=None) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py:215` — `FAISSBackend.get_failures`: `async def get_failures(self, agent_id: str, tenant_id: str='default', limit: int=5) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py:267` — `PgVectorBackend.store`: `async def store(self, episode: EpisodicMemory) -> str:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py:330` — `PgVectorBackend.search_similar`: `async def search_similar(self, embedding: list[float], namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py:387` — `PgVectorBackend.get_recent`: `async def get_recent(self, namespace_filter: dict[str, Any], limit: int=10, since: datetime | None=None) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py:426` — `PgVectorBackend.get_failures`: `async def get_failures(self, agent_id: str, tenant_id: str='default', limit: int=5) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py:273` — `RedisVectorBackend.store`: `async def store(self, episode: EpisodicMemory) -> str:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py:296` — `RedisVectorBackend.search_similar`: `async def search_similar(self, embedding: list[float], namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py:406` — `RedisVectorBackend.get_recent`: `async def get_recent(self, namespace_filter: dict[str, Any], limit: int=10, since: datetime | None=None) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py:476` — `RedisVectorBackend.get_failures`: `async def get_failures(self, agent_id: str, tenant_id: str='default', limit: int=5) -> list[EpisodicMemory]:`

### Does NOT Exist

- `packages/ai-parrot/tests/memory/dynamics/test_backend_scope.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_backend_scope.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py#FAISSBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py#FAISSBackend.get_failures",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py#FAISSBackend.get_recent",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py#FAISSBackend.search_similar",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py#FAISSBackend.store",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py#PgVectorBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py#PgVectorBackend.get_failures",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py#PgVectorBackend.get_recent",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py#PgVectorBackend.search_similar",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py#PgVectorBackend.store",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py#RedisVectorBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py#RedisVectorBackend.get_failures",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py#RedisVectorBackend.get_recent",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py#RedisVectorBackend.search_similar",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py#RedisVectorBackend.store"
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

### `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class PgVectorBackend:' packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py:66: class PgVectorBackend:
# Scoped SQL columns/filtering and compatibility.
# FILL IN: AC05/AC14: PG/Redis/FAISS preserve tenant/agent/user/session/room/crew/model scope before top-k and fallback limits.
# FILL IN: AC08: existing snapshots/rows are preserved; migrations are additive and backend-specific tests disclose missing service coverage.
# FILL IN: AC12: never advertise transactional review capability unless it is truly implemented; unsupported review-enabled configurations fail visibly.
```

**Why:** Applying identity filters before limits prevents cross-tenant or cross-model leakage and loss of relevant scoped candidates.

### `packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class RedisVectorBackend:' packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py:145: class RedisVectorBackend:
# Scoped vector and recent/failure routes.
# FILL IN: AC05/AC14: PG/Redis/FAISS preserve tenant/agent/user/session/room/crew/model scope before top-k and fallback limits.
# FILL IN: AC08: existing snapshots/rows are preserved; migrations are additive and backend-specific tests disclose missing service coverage.
# FILL IN: AC12: never advertise transactional review capability unless it is truly implemented; unsupported review-enabled configurations fail visibly.
```

**Why:** Applying identity filters before limits prevents cross-tenant or cross-model leakage and loss of relevant scoped candidates.

### `packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class FAISSBackend:' packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py:54: class FAISSBackend:
# Scoped serialized records and pre-limit filtering.
# FILL IN: AC05/AC14: PG/Redis/FAISS preserve tenant/agent/user/session/room/crew/model scope before top-k and fallback limits.
# FILL IN: AC08: existing snapshots/rows are preserved; migrations are additive and backend-specific tests disclose missing service coverage.
# FILL IN: AC12: never advertise transactional review capability unless it is truly implemented; unsupported review-enabled configurations fail visibly.
```

**Why:** Applying identity filters before limits prevents cross-tenant or cross-model leakage and loss of relevant scoped candidates.

### `packages/ai-parrot/tests/memory/dynamics/test_backend_scope.py` (CREATE)

```python
"""Behavioral acceptance tests for Scope propagation through existing episodic backends."""
import pytest

def test_backend_filters_before_limits() -> None:
    """Verify backend filters before limits."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_legacy_data_survives_optional_dimension() -> None:
    """Verify legacy data survives optional dimension."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_unsupported_reviews_fail_visible() -> None:
    """Verify unsupported reviews fail visible."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Applying identity filters before limits prevents cross-tenant or cross-model leakage and loss of relevant scoped candidates.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py` — Scoped SQL columns/filtering and compatibility; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py` — Scoped vector and recent/failure routes; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py` — Scoped serialized records and pre-limit filtering; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_backend_scope.py` — Backend route contract and data migration checks; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC05/AC14: PG/Redis/FAISS preserve tenant/agent/user/session/room/crew/model scope before top-k and fallback limits.
- [ ] AC08: existing snapshots/rows are preserved; migrations are additive and backend-specific tests disclose missing service coverage.
- [ ] AC12: never advertise transactional review capability unless it is truly implemented; unsupported review-enabled configurations fail visibly.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_backend_scope.py -q`

## Test Specification

- `backend_filters_before_limits`: AC05/AC14: PG/Redis/FAISS preserve tenant/agent/user/session/room/crew/model scope before top-k and fallback limits.
- `legacy_data_survives_optional_dimension`: AC08: existing snapshots/rows are preserved; migrations are additive and backend-specific tests disclose missing service coverage.
- `unsupported_reviews_fail_visible`: AC12: never advertise transactional review capability unless it is truly implemented; unsupported review-enabled configurations fail visibly.

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
