# TASK-5726: Recall eligible past interactions before result limits

**Feature**: FEAT-904 - Working automatic recall for user and episodic memory, proven end to end
**Spec**: `sdd/specs/user-memory-recall-e2e.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5723
**Assigned-to**: unassigned
**Parallel**: true

## Context

Bounded deliverable from approved FEAT-904, spec §§2–5. Implement the store portion of M3 using its eligibility-before-limit contract.

## Scope

- Implement the store portion of M3 using its eligibility-before-limit contract.
- Reject failures/retractions/exact excluded non-null session before counting matches; None excludes no session.
- Preserve original namespace/null filters, dynamics ranking and identities; never modify recall_similar's public signature or behavior.
- Test paged SQLite and nonpaged fallback, tiny vector ceilings and collaborators that fail if vector/embed/strategy search runs.

**NOT in scope**: Other tasks' targets; clients/base.py, conversation memory, review admission, storage schemas or new dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/store.py` | MODIFY | Recall eligible past interactions before result limits |
| `packages/ai-parrot/tests/memory/episodic/test_store_integration.py` | MODIFY | Regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against `5012f298d91f06025f0900b7c84df1f5ad4f3db7`; recheck after dependency commits.

### Verified Imports

Standard-library imports are built-in. Pytest/Pydantic/aiosqlite are already declared in the workspace. Preserve existing imports in modified modules; add the listed verified imports used by new test functions (including Path/pytest) when missing.

```python
from pathlib import Path
import pytest
from parrot.memory.episodic.models import EpisodeSearchResult, MemoryNamespace
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.store import EpisodicMemoryStore
```

### Dependency-created Imports

from parrot.memory.lexical import query_terms — created by TASK-5723.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore._fallback_lexical_search` — `packages/ai-parrot/src/parrot/memory/episodic/store.py:357`: `async def _fallback_lexical_search(self, query: str, namespace: MemoryNamespace, *, top_k: int, score_threshold: float, include_failures_only: bool, null_dimensions: tuple[str, ...]=()) -> list[EpisodeSearchResult]`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore._lexical_matches` — `packages/ai-parrot/src/parrot/memory/episodic/store.py:401`: `def _lexical_matches(episodes: Sequence[EpisodicMemory], terms: tuple[str, ...], *, score_threshold: float, include_failures_only: bool) -> list[EpisodeSearchResult]`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.recall_similar` — `packages/ai-parrot/src/parrot/memory/episodic/store.py:975`: `async def recall_similar(self, query: str, namespace: MemoryNamespace, top_k: int=5, score_threshold: float=0.3, category: EpisodeCategory | None=None, include_failures_only: bool=False, null_dimensions: tuple[str, ...]=()) -> list[EpisodeSearchResult]`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore._resolve_dynamics_states` — `packages/ai-parrot/src/parrot/memory/episodic/store.py:736`: `async def _resolve_dynamics_states(self, episodes: Sequence[EpisodicMemory]) -> dict[str, MemoryState]`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#_exclude_retracted` — `packages/ai-parrot/src/parrot/memory/episodic/store.py:90`: `def _exclude_retracted(episodes: list[_Recalled]) -> list[_Recalled]`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend` — `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py:229`: `class SQLiteEpisodeBackend(AbstractEpisodeBackend)`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend.get_recent_matching` — `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py:992`: `async def get_recent_matching(self, namespace_filter: dict[str, Any], *, limit: int | None=None, categories: Sequence[str] | None=None, failures_only: bool=False, before_id: str | None=None) -> list[EpisodicMemory]`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodeSearchResult` — `packages/ai-parrot/src/parrot/memory/episodic/models.py:175`: `class EpisodeSearchResult(EpisodicMemory)`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace` — `packages/ai-parrot/src/parrot/memory/episodic/models.py:214`: `class MemoryNamespace(BaseModel)`

### Does NOT Exist

- recall_interactions and private interaction_mode do not exist; this task creates them.

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
      "path": "packages/ai-parrot/tests/memory/episodic/test_store_integration.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore._fallback_lexical_search",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore._lexical_matches",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.recall_similar",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore._resolve_dynamics_states",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#_exclude_retracted",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend.get_recent_matching",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodeSearchResult",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace"
  ]
}
```

## Implementation Notes

Consumes query_terms and serializes episodic/store.py after its TASK-5723 writer.

Keep I/O async and close owned resources in finally. New Python uses strict hints, Google-style docstrings and black (120 columns). Store logs in artifacts/logs/. Do not change dependency manifests or shared conftest.py.

TASK-5723 replaces the whitespace-token anchor. Recheck its output; do not restore the old assignment.

## Implementation Blueprint

Planning scaffolds intentionally leave bounded FILL IN decisions. Completed implementation files must contain no placeholders.

### Steps (in order)

1. Verify contracts and dependency outputs — upstream commits can move anchors.
2. Apply each declared block and complete bounded logic — keep behavior traceable to this task's acceptance criteria.
3. Implement the listed behavior tests and run validation — code inspection alone does not prove acceptance.
4. Inspect the diff and retain evidence — stage only declared implementation targets.

### `packages/ai-parrot/src/parrot/memory/episodic/store.py` (MODIFY)

```python
# Anchor:     async def recall_similar(
# occurrences: 1; grep -F -c verified at packages/ai-parrot/src/parrot/memory/episodic/store.py:975
# INSERT next to recall_similar on EpisodicMemoryStore:
async def recall_interactions(
    self, query: str, namespace: MemoryNamespace, *, top_k: int = 3,
    score_threshold: float = 0.3, exclude_session_id: str | None = None,
    null_dimensions: tuple[str, ...] = (),
) -> list[EpisodeSearchResult]:
    """Recall nonfailure interactions lexically, independent of vector/index candidate limits."""
    # FILL IN: validate top_k/threshold; zero or empty normalized terms returns [].
    # Invoke private lexical interaction mode; never embeddings or strategy search.
    # Preserve rank_episodes with _resolve_dynamics_states over eligible original identities.
    raise NotImplementedError
# MODIFY private signature; default mode off preserves warning callers:
async def _fallback_lexical_search(
    self, query: str, namespace: MemoryNamespace, *, top_k: int,
    score_threshold: float, include_failures_only: bool,
    null_dimensions: tuple[str, ...] = (), interaction_mode: bool = False,
    exclude_session_id: str | None = None,
) -> list[EpisodeSearchResult]:
    """Page lexical matches with interaction-only exclusions applied before the result limit."""
    # FILL IN: mode on filters namespace, retractions, failures and exact session before top_k.
    # Advance before_id from raw page's final row, even when all rows were excluded.
    # Continue until enough eligible matches or exhaustion; never fixed overfetch.
    # Backend without paging: apply identical eligibility before slicing.
    # Mode off retains prior failure/category/retraction filtering order and limits.
    raise NotImplementedError
```

**Why**: Independent lexical retrieval bypasses vector/hybrid candidate ceilings without altering warnings.

### `packages/ai-parrot/tests/memory/episodic/test_store_integration.py` (MODIFY)

```python
# Anchor: class TestDefaultBehaviorUnchanged:
# occurrences: 1; grep -F -c verified at packages/ai-parrot/tests/memory/episodic/test_store_integration.py:43
# INSERT new tests at module scope before this definition; preserve it.
@pytest.mark.asyncio
async def test_recall_lane_survives_excluded_matches_across_pages(tmp_path: Path) -> None:
    """More than two excluded pages cannot hide an older eligible interaction."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_interaction_recall_bypasses_vector_and_strategy_caps(tmp_path: Path) -> None:
    """Injected embeddings and strategies are never called by interaction recall."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_recall_exclusions_exhaust_without_widening_scope(tmp_path: Path) -> None:
    """All-excluded populations terminate; inputs validate; scope stays narrow."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_warning_retraction_order_is_unchanged(tmp_path: Path) -> None:
    """Warning top-k retraction ordering remains unchanged."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError
```

**Why**: Preserve existing regressions while adding focused behavior checks.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/episodic/store.py`: complete the bounded block and satisfy all relevant ACs.
- [ ] `packages/ai-parrot/tests/memory/episodic/test_store_integration.py`: complete the bounded block and satisfy all relevant ACs.

## Acceptance Criteria

- [ ] **AC-1**: An eligible episode behind >512 excluded matches is found; all-excluded retrieval terminates at exhaustion.
- [ ] **AC-2**: No user/tenant/agent scope widening; null dimensions remain enforced.
- [ ] **AC-3**: Negative top_k and thresholds outside 0..1 raise ValueError; zero/empty terms return []; cancellation propagates.
- [ ] **AC-4**: Newest retracted failure at top_k=1 retains old warning result; pre-limit retraction filtering is interaction-only.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/episodic/test_store_integration.py -q`

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

Implemented by seat gpt-5.6-sol (codex), 1 attempt, 0 review fixes. Merge-tier validation: 104 passed. Closed via close_task.sh.
