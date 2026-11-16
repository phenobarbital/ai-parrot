# TASK-5592: Experience index generations and project configuration

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5591
**Assigned-to**: unassigned

## Context

Implement Module 2 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Add WikiProjectConfig.experience using ExperienceConfig; build one index from repo/global/primary shared definitions. Schema-check and redact each source; attach shared provenance in loader-owned in-memory metadata, never from event JSON. Snapshot under a bounded stable index.lock, build isolated generations, publish marker last; read previous generation after crashes. Include triggers stubs and runtime bounds in the published fastpath data without loading Pydantic on hooks. Set ExperienceEvent._shared_attestation only for validated shared-directory events, and OR trusted-source provenance when duplicate event IDs occur across sources so input ordering cannot change trust. Do not add metadata keys to the executable-to-stubs triggers map; publish configuration in a separate bounded generation metadata file consumed consistently by hooks. Each trigger stub includes lesson_id, state, solution_rev, trigger executable/subcommand, normalized error tokens, fix executable/subcommand, escaped advice, and recording session; the matcher and transitions must use those exact keys.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py` | CREATE | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from __future__ import annotations
from parrot.knowledge.wiki.experience.fastpath import safe_open
from parrot.knowledge.wiki.experience.index import ExperienceIndex
from parrot.knowledge.wiki.experience.models import ExperienceConfig
from parrot.knowledge.wiki.experience.models import ExperienceConfig, validate_event
from parrot.knowledge.wiki.experience.reducer import reduce_events
from parrot.knowledge.wiki.project import find_shared_root
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.launcher import parrot_home
from pathlib import Path
from pydantic import Field
from typing import Any
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord` — `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:606`
```python
class WikiPageRecord(BaseModel):
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store` — `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:3288`
```python
def create_wiki_store(
    storage_dir: str | Path,
    wiki_name: str = "",
    backend: str = "sqlite",
    **kwargs: Any,
) -> BaseWikiStore:
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.upsert_pages` — `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2325`
```python
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.upsert_attrs` — `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2506`
```python
    async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int:
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.search_fts` — `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2938`
```python
    async def search_fts(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig` — `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:589`
```python
class WikiProjectConfig(BaseModel):
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root` — `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1563`
```python
def find_shared_root(start: Path | None = None) -> Path | None:
```

- `sym:packages/ai-parrot/src/parrot/launcher.py#parrot_home` — `packages/ai-parrot/src/parrot/launcher.py:26`
```python
def parrot_home(env: Mapping[str, str] | None = None) -> Path:
```

### Dependency Interfaces

index: TASK-5591: consumes the reducer contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/reducer.py

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/project.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.search_fts",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.upsert_attrs",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.upsert_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store",
    "sym:packages/ai-parrot/src/parrot/launcher.py#parrot_home"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Add WikiProjectConfig.experience using ExperienceConfig; build one index from repo/global/primary shared definitions. Schema-check and redact each source; attach shared provenance in loader-owned in-memory metadata, never from event JSON. Snapshot under a bounded stable index.lock, build isolated generations, publish marker last; read previous generation after crashes. Include triggers stubs and runtime bounds in the published fastpath data without loading Pydantic on hooks. Set ExperienceEvent._shared_attestation only for validated shared-directory events, and OR trusted-source provenance when duplicate event IDs occur across sources so input ordering cannot change trust. Do not add metadata keys to the executable-to-stubs triggers map; publish configuration in a separate bounded generation metadata file consumed consistently by hooks. Each trigger stub includes lesson_id, state, solution_rev, trigger executable/subcommand, normalized error tokens, fix executable/subcommand, escaped advice, and recording session; the matcher and transitions must use those exact keys.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py` (CREATE)

```python
"""index experience component."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.project import find_shared_root
from parrot.knowledge.wiki.experience.models import ExperienceConfig, validate_event
from parrot.knowledge.wiki.experience.reducer import reduce_events
from parrot.knowledge.wiki.experience.fastpath import safe_open
from parrot.launcher import parrot_home

class ExperienceIndex:
    """The single reduced index, in the repo plane: wiki.db + triggers.json built from the union"""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

    def __init__(self, plane_dir: Path, *, read_only: bool=False) -> None:
        """Implement __init__ according to the spec contract."""
        # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

    def sources(self) -> list[Path]:
        """Repo events.jsonl, $PARROT_HOME/experience/events.jsonl, <shared-root>/sdd/experience/lessons/*.jsonl."""
        # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

    def is_stale(self) -> bool:
        """True when any source's (size, mtime_ns) differs from the marker of the published generation."""
        # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

    async def rebuild(self) -> int:
        """Under index.lock (bounded wait; give up → return -1): snapshot all sources, reduce,"""
        # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

    async def search(self, query: str, limit: int=10) -> list[dict[str, Any]]:
        """BM25 over the reduced store via search_fts (store.py:2938); ranking only."""
        # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.
```

**Why**: This file owns the index behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/knowledge/wiki/project.py:589 at 0c5acf0915.
# Anchor: class WikiProjectConfig(BaseModel):
from pydantic import Field
from parrot.knowledge.wiki.experience.models import ExperienceConfig
# Inside WikiProjectConfig:
experience: ExperienceConfig = Field(default_factory=ExperienceConfig)
# Keep the existing namespace and ledger fields unchanged.
```

**Why**: This file owns the index behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.experience.index import ExperienceIndex

@pytest.mark.asyncio
async def test_index_rebuild_generation_publish(tmp_path: Path) -> None:
    """Verify index rebuild generation publish. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_index_sources_union_dedup(tmp_path: Path) -> None:
    """Verify index sources union dedup. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_index_shared_provenance(tmp_path: Path) -> None:
    """Verify index shared provenance. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_index_source_removal_staleness(tmp_path: Path) -> None:
    """Verify index source removal staleness. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the index behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: union dedup, source deletion/change staleness, external worktrees, bounded lock contention, process concurrency, interruption before publication, forged local attestations, page attributes and FTS.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py -q`

## Test Specification

Required behavioral cases: union dedup, source deletion/change staleness, external worktrees, bounded lock contention, process concurrency, interruption before publication, forged local attestations, page attributes and FTS.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5592` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
