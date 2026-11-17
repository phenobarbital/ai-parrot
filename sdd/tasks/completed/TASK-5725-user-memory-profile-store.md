# TASK-5725: Rank user profiles across all eligible records

**Feature**: FEAT-904 - Working automatic recall for user and episodic memory, proven end to end
**Spec**: `sdd/specs/user-memory-recall-e2e.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5723
**Assigned-to**: unassigned
**Parallel**: true

## Context

Bounded deliverable from approved FEAT-904, spec §§2–5. Implement storage-only M2 using query_terms. Preserve schema, single connection ownership and lock.

## Scope

- Implement storage-only M2 using query_terms. Preserve schema, single connection ownership and lock.
- Filter tenant/agent/user, active status and one validity instant before ranking; case-fold searchable_text for overlap.
- Profile orders kind group/overlap/recency/ID; term recall filters any overlap and orders overlap/recency/ID.
- Retain existing validation and blank/short escaped-literal semantics. Close cursors on success, failure and cancellation.

**NOT in scope**: Other tasks' targets; clients/base.py, conversation memory, review admission, storage schemas or new dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/user/store.py` | MODIFY | Rank user profiles across all eligible records |
| `packages/ai-parrot/tests/memory/user/test_profile.py` | CREATE | Regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against `5012f298d91f06025f0900b7c84df1f5ad4f3db7`; recheck after dependency commits.

### Verified Imports

Standard-library imports are built-in. Pytest/Pydantic/aiosqlite are already declared in the workspace. Preserve existing imports in modified modules; add the listed verified imports used by new test functions (including Path/pytest) when missing.

```python
from pathlib import Path
import pytest
from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.user.models import UserKnowledge, UserKnowledgeCandidate, UserKnowledgeCommand
from parrot.memory.user.store import UserMemoryStore
```

### Dependency-created Imports

from parrot.memory.lexical import query_terms — created by TASK-5723.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore` — `packages/ai-parrot/src/parrot/memory/user/store.py:80`: `class UserMemoryStore()`
- `sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore.recall` — `packages/ai-parrot/src/parrot/memory/user/store.py:124`: `async def recall(self, query: str, *, scope: MemoryRequestScope, limit: int=5) -> list[UserKnowledge]`
- `sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore._require_identity` — `packages/ai-parrot/src/parrot/memory/user/store.py:487`: `def _require_identity(scope: MemoryRequestScope) -> tuple[str, str, str]`
- `sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore._validate_query` — `packages/ai-parrot/src/parrot/memory/user/store.py:494`: `def _validate_query(query: str) -> str`
- `sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore._validate_limit` — `packages/ai-parrot/src/parrot/memory/user/store.py:502`: `def _validate_limit(limit: int) -> None`
- `sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore._escape_like` — `packages/ai-parrot/src/parrot/memory/user/store.py:508`: `def _escape_like(value: str) -> str`
- `sym:packages/ai-parrot/src/parrot/memory/user/models.py#UserKnowledge` — `packages/ai-parrot/src/parrot/memory/user/models.py:71`: `class UserKnowledge(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/user/models.py#UserKnowledgeCandidate` — `packages/ai-parrot/src/parrot/memory/user/models.py:131`: `class UserKnowledgeCandidate(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/user/models.py#UserKnowledgeCommand` — `packages/ai-parrot/src/parrot/memory/user/models.py:186`: `class UserKnowledgeCommand(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#MemoryRequestScope` — `packages/ai-parrot/src/parrot/memory/agent_memory/models.py:52`: `class MemoryRequestScope(BaseModel)`

### Does NOT Exist

- UserMemoryStore.profile is created here; search() and a user_knowledge FTS5 table do not exist.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/user/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/user/test_profile.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore",
    "sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore.recall",
    "sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore._require_identity",
    "sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore._validate_query",
    "sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore._validate_limit",
    "sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore._escape_like",
    "sym:packages/ai-parrot/src/parrot/memory/user/models.py#UserKnowledge",
    "sym:packages/ai-parrot/src/parrot/memory/user/models.py#UserKnowledgeCandidate",
    "sym:packages/ai-parrot/src/parrot/memory/user/models.py#UserKnowledgeCommand",
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#MemoryRequestScope"
  ]
}
```

## Implementation Notes

Imports query_terms created by TASK-5723 in memory/lexical.py.

Keep I/O async and close owned resources in finally. New Python uses strict hints, Google-style docstrings and black (120 columns). Store logs in artifacts/logs/. Do not change dependency manifests or shared conftest.py.



## Implementation Blueprint

Planning scaffolds intentionally leave bounded FILL IN decisions. Completed implementation files must contain no placeholders.

### Steps (in order)

1. Verify contracts and dependency outputs — upstream commits can move anchors.
2. Apply each declared block and complete bounded logic — keep behavior traceable to this task's acceptance criteria.
3. Implement the listed behavior tests and run validation — code inspection alone does not prove acceptance.
4. Inspect the diff and retain evidence — stage only declared implementation targets.

### `packages/ai-parrot/src/parrot/memory/user/store.py` (MODIFY)

```python
# Anchor: _MAX_RESULT_LIMIT = 100
# occurrences: 1; grep -F -c verified at packages/ai-parrot/src/parrot/memory/user/store.py:20
# Anchor:     async def recall(
# occurrences: 1; grep -F -c verified at packages/ai-parrot/src/parrot/memory/user/store.py:124
# ADD import and constant:
from parrot.memory.lexical import query_terms
_PROFILE_KIND_ORDER = {"constraint": 0, "preference": 0, "goal": 1, "fact": 1}
# INSERT before recall on UserMemoryStore:
async def profile(
    self, *, scope: MemoryRequestScope, query: str = "", limit: int = 20
) -> list[UserKnowledge]:
    """Return active, valid scoped knowledge in globally ranked delivery order."""
    # FILL IN: identity/query/limit validation; one captured UTC now and one cursor under _lock.
    # fetchmany(100), <=limit winners, finally cursor.close(); limit zero opens no cursor.
    # Rank kind group ascending, overlap descending, updated_at descending, knowledge_id descending.
    raise NotImplementedError
# MODIFY existing recall body while retaining its public signature:
async def recall(self, query: str, *, scope: MemoryRequestScope, limit: int = 5) -> list[UserKnowledge]:
    """Return any-term matches ranked across all active, valid records of the trusted user."""
    # FILL IN: full eligible-population bounded scan, any-term filtering before limit.
    # Blank/no surviving terms use prior escaped literal SQL branch; close that cursor too.
    raise NotImplementedError
```

**Why**: Output limits must never truncate the ranked population; an old preference or unique match can be beyond 100 rows.

### `packages/ai-parrot/tests/memory/user/test_profile.py` (CREATE)

```python
"""Full-population profile and explicit recall tests using real temporary SQLite."""
from pathlib import Path
import pytest
from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.user.models import UserKnowledgeCandidate, UserKnowledgeCommand
from parrot.memory.user.store import UserMemoryStore

@pytest.mark.asyncio
async def test_profile_returns_all_active_for_unrelated_question(tmp_path: Path) -> None:
    """Unrelated queries still return active scoped knowledge."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_profile_orders_kind_group_then_overlap_then_recency(tmp_path: Path) -> None:
    """Kinds, overlap, timestamp and ID establish total order."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_profile_ranks_older_preference_beyond_first_page(tmp_path: Path) -> None:
    """An older preference precedes 200 newer facts."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_recall_finds_unique_match_beyond_first_page(tmp_path: Path) -> None:
    """Term and short literal matches survive beyond 200 newer rows."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_profile_and_recall_scan_with_bounded_memory(tmp_path: Path) -> None:
    """Batches and winners are bounded and agree with a full-sort oracle."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_profile_excludes_pending_superseded_and_expired(tmp_path: Path) -> None:
    """Status, validity and scope filter before ranking."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_profile_requires_user_identity_and_bounded_limit(tmp_path: Path) -> None:
    """Missing identity, long queries, invalid limits and zero are handled."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_recall_matches_any_term_of_a_question(tmp_path: Path) -> None:
    """Any normalized term matches, ranked by overlap then recency."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_recall_blank_and_short_literal_queries_unchanged(tmp_path: Path) -> None:
    """Blank and short literal SQL semantics are preserved."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError
```

**Why**: Use stable timestamps/IDs and a full-sort oracle; instrument batches to reject fetchall/input cutoffs.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/user/store.py`: complete the bounded block and satisfy all relevant ACs.
- [ ] `packages/ai-parrot/tests/memory/user/test_profile.py`: complete the bounded block and satisfy all relevant ACs.

## Acceptance Criteria

- [ ] **AC-1**: All nine cases pass, including >200 rows, stable tie-breaks, Unicode, scope isolation and validity boundaries.
- [ ] **AC-2**: Use fetchmany(100) and <=limit retained winners; no raw LIMIT 100 or full-population fetchall.
- [ ] **AC-3**: Zero returns before cursor creation; missing identity and invalid parameters raise existing ValueError contracts.
- [ ] **AC-4**: Existing user store tests pass; no FTS, schema migration or manager changes.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/user/test_profile.py packages/ai-parrot/tests/memory/user/test_store.py -q`

## Test Specification

Use named blueprint cases as the acceptance matrix. Cover the adversarial boundaries in Scope/ACs and preserve existing regressions.

## Agent Instructions

1. Use the host session and feature worktree provisioned by `parrot sdd worktree ensure --slug user-memory-recall-e2e --feature-id FEAT-904`; never implement on dev.
2. Read the spec and confirm every dependency is done in `sdd/tasks/index/user-memory-recall-e2e.json`.
3. Re-verify contracts and use sdd-start lifecycle; never silently expand target files.
4. Activate the shared venv and set PYTHONPATH=packages/ai-parrot/src for worktree tests; never uv sync there.
5. Run scoped validation and applicable lint; retain logs in artifacts/logs/.
6. Commit implementation, then use parrot sdd task finalize with real TaskCompletionEvidence and exact implementation HEAD.
7. Inspect generated Completion Note and active-to-completed move; commit only task SDD state. Do not hand-edit completion state or push from the worker.

## Completion Note

Pending; the task finalizer generates this after implementation and validation.


## Completion Note

Implemented by seat gpt-5.6-terra (codex), 1 attempt, 0 review fixes. Merge-tier validation: 104 passed. Closed via close_task.sh.
