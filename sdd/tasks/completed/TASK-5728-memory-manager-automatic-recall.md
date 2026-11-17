# TASK-5728: Wire profile and interaction recall into the manager

**Feature**: FEAT-904 - Working automatic recall for user and episodic memory, proven end to end
**Spec**: `sdd/specs/user-memory-recall-e2e.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5725, TASK-5726, TASK-5727
**Assigned-to**: unassigned
**Parallel**: true

## Context

Bounded deliverable from approved FEAT-904, spec §§2–5. Integrate M2/M3 in the manager, preserving public interfaces, warning arguments and review admission.

## Scope

- Integrate M2/M3 in the manager, preserving public interfaces, warning arguments and review admission.
- Bound long query text before profile(), keep enabled/identified-user guards, and return [] on ordinary store failures.
- Run interaction recall per scope, defensively filter, deduplicate and apply the final lane result limit.
- Update autospecced collaborators for profile/recall_interactions; use explicitly empty mock recall results.

**NOT in scope**: Other tasks' targets; clients/base.py, conversation memory, review admission, storage schemas or new dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/unified/manager.py` | MODIFY | Wire profile and interaction recall into the manager |
| `packages/ai-parrot/tests/memory/unified/test_manager.py` | MODIFY | Regression coverage |
| `packages/ai-parrot/tests/memory/unified/test_manager_real_store.py` | MODIFY | Regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against `5012f298d91f06025f0900b7c84df1f5ad4f3db7`; recheck after dependency commits.

### Verified Imports

Standard-library imports are built-in. Pytest/Pydantic/aiosqlite are already declared in the workspace. Preserve existing imports in modified modules; add the listed verified imports used by new test functions (including Path/pytest) when missing.

```python
from pathlib import Path
import pytest
from parrot.memory.user.store import _MAX_QUERY_CHARS
from parrot.memory.user.models import UserKnowledge
from parrot.memory.unified.models import MemoryCandidate
from parrot.memory.agent_memory.models import MemoryRequestScope
```

### Dependency-created Imports

No unimplemented import is assumed before its dependency is complete.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/memory/user/store.py:19`: `_MAX_QUERY_CHARS = 2_048`; import this existing bound rather than duplicating it.

- `sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._get_user_candidates` — `packages/ai-parrot/src/parrot/memory/unified/manager.py:689`: `async def _get_user_candidates(self, query: str, scope: MemoryRequestScope) -> list[MemoryCandidate]`
- `sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._user_candidate` — `packages/ai-parrot/src/parrot/memory/unified/manager.py:864`: `def _user_candidate(knowledge: UserKnowledge, scope: MemoryRequestScope) -> MemoryCandidate`
- `sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._get_episodic_candidates` — `packages/ai-parrot/src/parrot/memory/unified/manager.py:594`: `async def _get_episodic_candidates(self, query: str, scope: MemoryRequestScope) -> list[MemoryCandidate]`
- `sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._recall_scopes` — `packages/ai-parrot/src/parrot/memory/unified/manager.py:805`: `def _recall_scopes(scope: MemoryRequestScope) -> list[tuple[MemoryNamespace, tuple[str, ...]]]`
- `sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._visible_to_scope` — `packages/ai-parrot/src/parrot/memory/unified/manager.py:815`: `def _visible_to_scope(episode: Any, scope: MemoryRequestScope) -> bool`
- `sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.prepare_context` — `packages/ai-parrot/src/parrot/memory/unified/manager.py:206`: `async def prepare_context(self, query: str, *, scope: MemoryRequestScope) -> MemoryContext`
- `sym:packages/ai-parrot/src/parrot/memory/user/models.py#UserKnowledge` — `packages/ai-parrot/src/parrot/memory/user/models.py:71`: `class UserKnowledge(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryCandidate` — `packages/ai-parrot/src/parrot/memory/unified/models.py:20`: `class MemoryCandidate(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#MemoryRequestScope` — `packages/ai-parrot/src/parrot/memory/agent_memory/models.py:52`: `class MemoryRequestScope(BaseModel)`

### Does NOT Exist

- profile and recall_interactions are dependency-created. There is no public drain_memory_writes method.

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
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_manager_real_store.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._get_user_candidates",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._user_candidate",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._get_episodic_candidates",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._recall_scopes",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._visible_to_scope",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.prepare_context",
    "sym:packages/ai-parrot/src/parrot/memory/user/models.py#UserKnowledge",
    "sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryCandidate",
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#MemoryRequestScope"
  ]
}
```

## Implementation Notes

Consumes profile from TASK-5725 and recall_interactions from TASK-5726; tests consume TASK-5727's split packed sections and references.

Keep I/O async and close owned resources in finally. New Python uses strict hints, Google-style docstrings and black (120 columns). Store logs in artifacts/logs/. Do not change dependency manifests or shared conftest.py.



## Implementation Blueprint

Planning scaffolds intentionally leave bounded FILL IN decisions. Completed implementation files must contain no placeholders.

### Steps (in order)

1. Verify contracts and dependency outputs — upstream commits can move anchors.
2. Apply each declared block and complete bounded logic — keep behavior traceable to this task's acceptance criteria.
3. Implement the listed behavior tests and run validation — code inspection alone does not prove acceptance.
4. Inspect the diff and retain evidence — stage only declared implementation targets.

### `packages/ai-parrot/src/parrot/memory/unified/manager.py` (MODIFY)

```python
# Anchor: knowledge = await self.user_memory_store.recall(query, scope=scope)
# occurrences: 1; grep -F -c verified at packages/ai-parrot/src/parrot/memory/unified/manager.py:694
# Anchor: def _user_candidate(knowledge: UserKnowledge, scope: MemoryRequestScope) -> MemoryCandidate:
# occurrences: 1; grep -F -c verified at packages/ai-parrot/src/parrot/memory/unified/manager.py:864
# Anchor: top_k = self.config.episodic_max_warnings
# occurrences: 1; grep -F -c verified at packages/ai-parrot/src/parrot/memory/unified/manager.py:610
# ADD verified import:
from parrot.memory.user.store import _MAX_QUERY_CHARS
# REPLACE profile call inside existing guarded try:
knowledge = await self.user_memory_store.profile(
    scope=scope, query=query[:_MAX_QUERY_CHARS], limit=self.config.user_max_records
)
# REPLACE the user-candidate return expression:
return [
    self._user_candidate(item, scope, relevance=1.0 - index / len(knowledge))
    for index, item in enumerate(knowledge)
]
# MODIFY helper, retaining @staticmethod and existing formatted text/fields:
def _user_candidate(
    knowledge: UserKnowledge, scope: MemoryRequestScope, relevance: float
) -> MemoryCandidate:
    """Translate one ranked profile record without experiential dynamics."""
    # FILL IN: retain existing fields, substitute the relevance argument for hard-coded 1.0.
    raise NotImplementedError
# EXTEND existing episodic candidate method:
async def _get_episodic_candidates(
    self, query: str, scope: MemoryRequestScope
) -> list[MemoryCandidate]:
    """Retrieve warnings and earlier-session recall under unchanged visibility."""
    # FILL IN: retain warning gather/filter/score policy and original arguments.
    # If max recall >0, call recall_interactions per _recall_scopes entry with
    # exclude_session_id=scope.session_id and top_k=config.episodic_max_recall.
    # Propagate cancellation; log and skip ordinary per-scope failures.
    # Recheck visibility/nonfailure/session; exclude warning IDs and deduplicate by episode ID.
    # Sort by existing score key, slice lane limit, build original MemoryRef and lane="recall".
    raise NotImplementedError
```

**Why**: Descending relevance preserves profile order; recall references must retain their original recorded namespace.

### `packages/ai-parrot/tests/memory/unified/test_manager.py` (MODIFY)

```python
# Anchor: class TestUnifiedMemoryManager:
# occurrences: 1; grep -F -c verified at packages/ai-parrot/tests/memory/unified/test_manager.py:53
# INSERT new tests at module scope before this definition; preserve it.
@pytest.mark.asyncio
async def test_user_candidates_keep_profile_order_through_assembler(tmp_path: Path) -> None:
    """Profile ordering survives candidate sorting and packing."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_episodic_recall_lane_excludes_current_session_and_failures(tmp_path: Path) -> None:
    """Only visible earlier-session nonfailures enter recall."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_episodic_recall_lane_disabled_at_zero(tmp_path: Path) -> None:
    """Zero prevents recall calls/refs while warnings remain unchanged."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_recall_lane_refs_enter_delivered_exposure(tmp_path: Path) -> None:
    """Only packed original recall refs enter delivered exposure."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError
```

**Why**: Preserve existing regressions while adding focused behavior checks.

### `packages/ai-parrot/tests/memory/unified/test_manager_real_store.py` (MODIFY)

```python
# Anchor: async def test_unified_records_real_episode(manager, backend, namespace) -> None:
# occurrences: 1; grep -F -c verified at packages/ai-parrot/tests/memory/unified/test_manager_real_store.py:60
# Preserve the existing real-store fixtures and record test.
# FILL IN: update warning-only fixtures that assumed nonfailures were always absent.
# Explicitly disable the new lane only for tests whose purpose is legacy warning isolation.
# Add real-store coverage that delivered recall references keep original namespace and identity.
```

**Why**: Update assumptions affected by the new default lane without weakening unrelated real-store regressions.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/unified/manager.py`: complete the bounded block and satisfy all relevant ACs.
- [ ] `packages/ai-parrot/tests/memory/unified/test_manager.py`: complete the bounded block and satisfy all relevant ACs.
- [ ] `packages/ai-parrot/tests/memory/unified/test_manager_real_store.py`: complete the bounded block and satisfy all relevant ACs.

## Acceptance Criteria

- [ ] **AC-1**: Every eligible identified-user request uses profile with configured limit/query bound and preserves delivery order.
- [ ] **AC-2**: Recall excludes current-session/failure/hidden/warning-duplicate episodes; zero skips recall calls entirely.
- [ ] **AC-3**: Both lanes retain original MemoryRef identities; only fully packed content reaches delivered exposure.
- [ ] **AC-4**: Ordinary per-scope failures preserve other results; cancellation propagates; no-eligible-recall enabled/disabled prompts agree.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/unified/test_manager.py packages/ai-parrot/tests/memory/unified/test_manager_real_store.py -q`

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

Implemented by seat gpt-5.6-terra (codex), 1 attempt, 0 review fixes. Merge-tier validation: 40 passed. Closed via close_task.sh.
