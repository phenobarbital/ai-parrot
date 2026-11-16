# TASK-5723: Normalize lexical memory query terms

**Feature**: FEAT-904 - Working automatic recall for user and episodic memory, proven end to end
**Spec**: `sdd/specs/user-memory-recall-e2e.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1–2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true

## Context

Bounded deliverable from approved FEAT-904, spec §§2–5. Implement spec M1 and its three deterministic tests: Unicode word extraction, case-folding, minimum length 3, stable deduplication.

## Scope

- Implement spec M1 and its three deterministic tests: Unicode word extraction, case-folding, minimum length 3, stable deduplication.
- Replace only the lexical fallback term assignment; preserve score and retrieval/filter order.

**NOT in scope**: Other tasks' targets; clients/base.py, conversation memory, review admission, storage schemas or new dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/lexical.py` | CREATE | Normalize lexical memory query terms |
| `packages/ai-parrot/src/parrot/memory/episodic/store.py` | MODIFY | Normalize lexical memory query terms |
| `packages/ai-parrot/tests/memory/test_lexical.py` | CREATE | Regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against `5012f298d91f06025f0900b7c84df1f5ad4f3db7`; recheck after dependency commits.

### Verified Imports

Standard-library imports are built-in. Pytest/Pydantic/aiosqlite are already declared in the workspace. Preserve existing imports in modified modules; add the listed verified imports used by new test functions (including Path/pytest) when missing.

```python
import re
from pathlib import Path
import pytest
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
```

### Dependency-created Imports

from parrot.memory.lexical import query_terms — created by this task.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore._fallback_lexical_search` — `packages/ai-parrot/src/parrot/memory/episodic/store.py:357`: `async def _fallback_lexical_search(self, query: str, namespace: MemoryNamespace, *, top_k: int, score_threshold: float, include_failures_only: bool, null_dimensions: tuple[str, ...]=()) -> list[EpisodeSearchResult]`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_episode` — `packages/ai-parrot/src/parrot/memory/episodic/store.py:190`: `async def record_episode(self, namespace: MemoryNamespace, situation: str, action_taken: str, outcome: EpisodeOutcome, outcome_details: str | None=None, error_type: str | None=None, error_message: str | None=None, category: EpisodeCategory=EpisodeCategory.TOOL_EXECUTION, importance: int | None=None, related_tools: list[str] | None=None, related_entities: list[str] | None=None, metadata: dict[str, Any] | None=None, generate_reflection: bool=True, ttl_days: int | None=None, episode_id: str | None=None) -> EpisodicMemory`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.recall_similar` — `packages/ai-parrot/src/parrot/memory/episodic/store.py:975`: `async def recall_similar(self, query: str, namespace: MemoryNamespace, top_k: int=5, score_threshold: float=0.3, category: EpisodeCategory | None=None, include_failures_only: bool=False, null_dimensions: tuple[str, ...]=()) -> list[EpisodeSearchResult]`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend` — `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py:229`: `class SQLiteEpisodeBackend(AbstractEpisodeBackend)`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodeCategory` — `packages/ai-parrot/src/parrot/memory/episodic/models.py:34`: `class EpisodeCategory(str, Enum)`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodeOutcome` — `packages/ai-parrot/src/parrot/memory/episodic/models.py:25`: `class EpisodeOutcome(str, Enum)`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace` — `packages/ai-parrot/src/parrot/memory/episodic/models.py:214`: `class MemoryNamespace(BaseModel)`

### Does NOT Exist

- parrot.memory.lexical/query_terms do not exist; this task creates them.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/lexical.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/test_lexical.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore._fallback_lexical_search",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_episode",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.recall_similar",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodeCategory",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodeOutcome",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace"
  ]
}
```

## Implementation Notes

Independent: creates lexical.py/test_lexical.py; later interaction-store task serializes its episodic/store.py modification.

Keep I/O async and close owned resources in finally. New Python uses strict hints, Google-style docstrings and black (120 columns). Store logs in artifacts/logs/. Do not change dependency manifests or shared conftest.py.



## Implementation Blueprint

Planning scaffolds intentionally leave bounded FILL IN decisions. Completed implementation files must contain no placeholders.

### Steps (in order)

1. Verify contracts and dependency outputs — upstream commits can move anchors.
2. Apply each declared block and complete bounded logic — keep behavior traceable to this task's acceptance criteria.
3. Implement the listed behavior tests and run validation — code inspection alone does not prove acceptance.
4. Inspect the diff and retain evidence — stage only declared implementation targets.

### `packages/ai-parrot/src/parrot/memory/lexical.py` (CREATE)

```python
"""Shared Unicode-aware lexical normalization for memory retrieval."""
import re

MIN_TERM_LENGTH = 3


def query_terms(text: str) -> tuple[str, ...]:
    """Return distinct case-folded words of length at least three in first-seen order."""
    # FILL IN: use re.findall(r"\w+", text.casefold()), filter length and deduplicate in order.
    raise NotImplementedError
```

**Why**: One pure helper keeps normalization identical across memory stores.

### `packages/ai-parrot/src/parrot/memory/episodic/store.py` (MODIFY)

```python
# Anchor: terms = tuple(term for term in query.casefold().split() if term)
# occurrences: 1; grep -F -c verified at packages/ai-parrot/src/parrot/memory/episodic/store.py:368
# ADD import beside memory imports; REPLACE only the anchor assignment inside lexical fallback.
from parrot.memory.lexical import query_terms
terms = query_terms(query)
```

**Why**: Keep substring scoring, paging and filtering order; change only term normalization.

### `packages/ai-parrot/tests/memory/test_lexical.py` (CREATE)

```python
"""Shared normalization and real episodic fallback regression tests."""
from pathlib import Path
import pytest
from parrot.memory.lexical import query_terms
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore

def test_query_terms_strips_punctuation_and_short_terms() -> None:
    """Spanish punctuation yields cuál, capital and australia."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

def test_query_terms_blank_and_duplicates() -> None:
    """Blank input yields no terms; duplicate case variants retain first-seen order."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_fallback_lexical_search_ignores_punctuation(tmp_path: Path) -> None:
    """A real stored Australia episode matches australia?."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError
```

**Why**: Use a temporary SQLite store and finally cleanup to prove the fallback actually uses the helper.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/lexical.py`: complete the bounded block and satisfy all relevant ACs.
- [ ] `packages/ai-parrot/src/parrot/memory/episodic/store.py`: complete the bounded block and satisfy all relevant ACs.
- [ ] `packages/ai-parrot/tests/memory/test_lexical.py`: complete the bounded block and satisfy all relevant ACs.

## Acceptance Criteria

- [ ] **AC-1**: The Spanish example produces ('cuál', 'capital', 'australia'); blank/punctuation-only text produces ().
- [ ] **AC-2**: The real fallback matches punctuation-bearing queries and removes two-letter search terms.
- [ ] **AC-3**: No embedding/tokenizer dependency, schema or warning-policy change is introduced.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/test_lexical.py -q`

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
