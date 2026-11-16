# TASK-5660: Episode model scope and optional review capability

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: blocked
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5656
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes ReviewBackend capability and MemoryRef canonical scope contract from TASK-5656

## Context

Implement the bounded M2 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Release Preconditions

G2: canonical namespace encoding and SQL/cache migration rules must be frozen; no guessed UUID namespace.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- Persist model dimension and separate ranking fields (`packages/ai-parrot/src/parrot/memory/episodic/models.py`).
- Keep baseline protocol separate from reviews (`packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py`).
- Serialization, complete scope keys and backend compatibility (`packages/ai-parrot/tests/memory/dynamics/test_episode_scope.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/models.py` | MODIFY | Persist model dimension and separate ranking fields |
| `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py` | MODIFY | Keep baseline protocol separate from reviews |
| `packages/ai-parrot/tests/memory/dynamics/test_episode_scope.py` | CREATE | Serialization, complete scope keys and backend compatibility |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.memory.episodic.backends.abstract import AbstractEpisodeBackend
from parrot.memory.episodic.models import EpisodicMemory
from parrot.memory.episodic.models import MemoryNamespace
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/episodic/models.py:214`: `class MemoryNamespace(BaseModel):` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py:11`: `class AbstractEpisodeBackend(Protocol):` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py:18` — `AbstractEpisodeBackend.store`: `async def store(self, episode: EpisodicMemory) -> str:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py:29` — `AbstractEpisodeBackend.search_similar`: `async def search_similar(self, embedding: list[float], namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py:51` — `AbstractEpisodeBackend.get_recent`: `async def get_recent(self, namespace_filter: dict[str, Any], limit: int=10, since: datetime | None=None) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py:69` — `AbstractEpisodeBackend.get_failures`: `async def get_failures(self, agent_id: str, tenant_id: str='default', limit: int=5) -> list[EpisodicMemory]:`
- `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py:106` — `AbstractEpisodeBackend.update_metadata`: `async def update_metadata(self, episode_ids: list[str], patch: dict[str, Any]) -> int:`
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:179` — `EpisodicMemory.to_dict`: `def to_dict(self) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:191` — `EpisodicMemory.from_dict`: `def from_dict(cls, data: dict[str, Any]) -> EpisodicMemory:`
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:246` — `MemoryNamespace.build_filter`: `def build_filter(self) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:283` — `MemoryNamespace.redis_prefix`: `def redis_prefix(self) -> str:`

### Does NOT Exist

- `packages/ai-parrot/tests/memory/dynamics/test_episode_scope.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_episode_scope.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py#AbstractEpisodeBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py#AbstractEpisodeBackend.get_failures",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py#AbstractEpisodeBackend.get_recent",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py#AbstractEpisodeBackend.search_similar",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py#AbstractEpisodeBackend.store",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py#AbstractEpisodeBackend.update_metadata",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory.from_dict",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory.to_dict",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace.build_filter",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace.redis_prefix"
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

### `packages/ai-parrot/src/parrot/memory/episodic/models.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class MemoryNamespace(BaseModel):' packages/ai-parrot/src/parrot/memory/episodic/models.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/models.py:214: class MemoryNamespace(BaseModel):
# Extend MemoryNamespace and EpisodicMemory with optional model_id; preserve old round trips.
# Extend build_filter, redis_prefix and serialization using the accepted canonical encoding.
# Add EpisodeSearchResult.ranking_score, retrievability, stability and review_count separately.
# FILL IN: serialization defaults and validation — AC05/AC14; keep score bounded and no enum change.
```

**Why:** Persisted model scope must survive every serialization path; keeping review capability optional protects existing third-party backends.

### `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class AbstractEpisodeBackend(Protocol):' packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py:11: class AbstractEpisodeBackend(Protocol):
# Keep baseline storage methods backward-compatible when dynamics is off.
# FILL IN: document optional ReviewBackend capability and scoped failure/recent retrieval — AC05/AC12.
# Do not require apply_review on every third-party baseline backend.
```

**Why:** Persisted model scope must survive every serialization path; keeping review capability optional protects existing third-party backends.

### `packages/ai-parrot/tests/memory/dynamics/test_episode_scope.py` (CREATE)

```python
"""Behavioral acceptance tests for Episode model scope and optional review capability."""
import pytest

def test_legacy_and_model_scoped_round_trip() -> None:
    """Verify legacy and model scoped round trip."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_namespace_encoding_no_collisions() -> None:
    """Verify namespace encoding no collisions."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_baseline_backend_without_review() -> None:
    """Verify baseline backend without review."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Persisted model scope must survive every serialization path; keeping review capability optional protects existing third-party backends.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/episodic/models.py` — Persist model dimension and separate ranking fields; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py` — Keep baseline protocol separate from reviews; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_episode_scope.py` — Serialization, complete scope keys and backend compatibility; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC05/AC14: optional model_id survives episode serialization/filter/cache identity; absent fields load legacy episodes without broadening scope.
- [ ] AC12: dynamics-off accepts existing baseline backends; unsupported dynamics configurations fail visibly.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_episode_scope.py -q`

## Test Specification

- `legacy_and_model_scoped_round_trip`: AC05/AC14: optional model_id survives episode serialization/filter/cache identity; absent fields load legacy episodes without broadening scope.
- `namespace_encoding_no_collisions`: AC12: dynamics-off accepts existing baseline backends; unsupported dynamics configurations fail visibly.
- `baseline_backend_without_review`: AC05/AC14: optional model_id survives episode serialization/filter/cache identity; absent fields load legacy episodes without broadening scope.

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
