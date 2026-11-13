# TASK-5661: SQLite episodic persistence and measured vector ceiling

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: blocked
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5660
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes EpisodicMemory/model_id and baseline backend protocol from TASK-5660

## Context

Implement the bounded M2 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Release Preconditions

G2/Q5: select canonical benchmark evidence and numeric supported ceiling; amend transaction/schema details before production backend release.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- Async local episode backend (`packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py`).
- Real local persistence, scope and degradation (`packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` | CREATE | Async local episode backend |
| `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` | CREATE | Real local persistence, scope and degradation |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from __future__ import annotations
from datetime import datetime
from parrot.memory.episodic.backends.abstract import AbstractEpisodeBackend
from parrot.memory.episodic.models import EpisodicMemory
from parrot.memory.episodic.models import EpisodicMemory, EpisodeSearchResult
from parrot.memory.episodic.models import MemoryNamespace
from pathlib import Path
from typing import Any
import aiosqlite
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py`: 11:class AbstractEpisodeBackend(Protocol):
- `packages/ai-parrot/src/parrot/memory/episodic/models.py`: 55:class EpisodicMemory(BaseModel):
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

- `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py",
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
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory.from_dict",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory.to_dict",
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

### `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` (CREATE)

```python
"""SQLite episode persistence under the accepted local-store contract."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any
import aiosqlite
from parrot.memory.episodic.models import EpisodicMemory, EpisodeSearchResult

class SQLiteEpisodeBackend:
    """Persist scoped episodes using async I/O, WAL and the accepted vector ceiling."""
    def __init__(self, path: Path) -> None:
        """Retain configuration without opening resources or deleting existing data."""
        self.path = path
        # FILL IN: accepted lifecycle/ceiling configuration — G2/AC13.

    async def configure(self) -> None:
        """Open the connection and apply idempotent versioned schema changes."""
        # FILL IN: WAL, busy handling, migrations and partial-open rollback — AC12.
        raise NotImplementedError

    async def close(self) -> None:
        """Drain owned writes and release resources without claiming lost acknowledgements."""
        # FILL IN: cancellation-safe lifecycle — AC07/AC12.
        raise NotImplementedError

    async def store(self, episode: EpisodicMemory) -> str:
        """Persist one episode and acknowledge only after commit."""
        # FILL IN: accepted scoped identity and idempotent persistence — AC12.
        raise NotImplementedError

    async def search_similar(self, embedding: list[float], namespace_filter: dict[str, Any],
                             top_k: int = 5, score_threshold: float = 0.3,
                             include_failures_only: bool = False) -> list[EpisodeSearchResult]:
        """Filter before ranking and expose vector-ceiling degradation explicitly."""
        # FILL IN: exact cosine under measured ceiling; no new index dependency — AC13/AC14.
        raise NotImplementedError

    async def get_recent(self, namespace_filter: dict[str, Any], limit: int = 10,
                         since: datetime | None = None) -> list[EpisodicMemory]:
        """Return scoped recent episodes, applying filters before the limit."""
        # FILL IN: parameterized SQL and stable ordering — AC05.
        raise NotImplementedError

    async def get_failures(self, agent_id: str, tenant_id: str = "default",
                           limit: int = 5) -> list[EpisodicMemory]:
        """Preserve baseline failure retrieval without bypassing scoped store admission."""
        # FILL IN: accepted scoped extension/fallback — AC05.
        raise NotImplementedError

    async def delete_expired(self) -> int:
        """Prune permitted episode data without destroying required replay/archive history."""
        # FILL IN: U4 retention and imported-feedback protection — AC12/AC18.
        raise NotImplementedError

    async def count(self, namespace_filter: dict[str, Any]) -> int:
        """Count only records in the supplied scope."""
        # FILL IN: parameterized scoped count — AC05.
        raise NotImplementedError

    async def update_metadata(self, episode_ids: list[str], patch: dict[str, Any]) -> int:
        """Preserve baseline metadata merge semantics and transactional persistence."""
        # FILL IN: owned IDs and accepted version rules — AC12.
        raise NotImplementedError
```

**Why:** Real async transactions establish durable acknowledgement; explicit vector degradation prevents fast lexical results from concealing a failing vector route.

### `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` (CREATE)

```python
"""Behavioral acceptance tests for SQLite episodic persistence and measured vector ceiling."""
import pytest

def test_persist_reopen_and_failed_write() -> None:
    """Verify persist reopen and failed write."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_scope_before_top_k() -> None:
    """Verify scope before top k."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_measured_ceiling_reports_degradation() -> None:
    """Verify measured ceiling reports degradation."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Real async transactions establish durable acknowledgement; explicit vector degradation prevents fast lexical results from concealing a failing vector route.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` — Async local episode backend; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` — Real local persistence, scope and degradation; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC12: real temporary SQLite store persists data across close/reopen and rolls back failed writes; async I/O and no implicit data relocation.
- [ ] AC13/Q5: exact vector route uses a documented measured ceiling from the canonical benchmark; exceeding it reports degraded state, not a fake FTS performance pass.
- [ ] AC05/AC14: namespace filters precede vector/recent limits and lexical fallback works without paid embedding access.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py -q`

## Test Specification

- `persist_reopen_and_failed_write`: AC12: real temporary SQLite store persists data across close/reopen and rolls back failed writes; async I/O and no implicit data relocation.
- `scope_before_top_k`: AC13/Q5: exact vector route uses a documented measured ceiling from the canonical benchmark; exceeding it reports degraded state, not a fake FTS performance pass.
- `measured_ceiling_reports_degradation`: AC05/AC14: namespace filters precede vector/recent limits and lexical fallback works without paid embedding access.

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
