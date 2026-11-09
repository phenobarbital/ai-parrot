# TASK-5431: Report and repair library drift and missing judgements

**Feature**: FEAT-858 — Bookstore Agentic Retrieval
**Spec**: `sdd/specs/bookstore-agentic-retrieval.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h; host wall time depends on provider when applicable)
**Depends-on**: TASK-5430
**Assigned-to**: unassigned

## Context

Implement this bounded deliverable of the approved FEAT-858 spec. Its behavioral authority
is the spec's §2 and owning §3 module, with §4 validation and §5 acceptance criteria.
Verified source base: `8387cd3e1b604955928064ff51a2fa207deceb36`. No implementation has been performed by this planning task.

## Scope

- Implement Bookstore.doctor and CatalogStore.judgement_count per spec M4.
- Scan reserved trees before sweep and preserve action/error reporting; compare live derive_toc digest and entries under the book operation lock.
- Repair structural fields only, preserve manual descriptive fields, clear unproven source_sha256, and invalidate graph for repaired structural drift.
- Report orphan_card without reconstructing missing content; busy/error cases remain explicit. Document identical-TOC content drift limitation.
- Count judgement rows touching either endpoint across scopes, including rel=none. Only explicit relate invokes relation work; empty targets never trigger all-books behavior.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot/tests/knowledge/bookstore/test_doctor.py` | CREATE | Task regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pathlib import Path  # verified: stdlib; existing library.py:26
import pytest  # verified: existing Bookstore test_toolkit.py:5
from unittest.mock import AsyncMock, MagicMock  # verified: stdlib; Bookstore conftest.py:13
from parrot.knowledge.bookstore.config import LibraryLocation  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:33
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:112,179
from parrot.knowledge.bookstore.carding import derive_toc  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:124
from parrot.knowledge.bookstore.catalog import CatalogStore  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:163
from typing import Any, Optional  # verified: stdlib; existing library.py:27
```

### Existing Signatures to Use

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:338
def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:711
async def relate_books(
        self,
        book_ids: Optional[list[str]] = None,
        *,
        use_llm: bool = True,
        communities: bool = True,
        communities_only: bool = False,
        force: bool = False,
        resolution: float = 1.0,
    ) -> RelateSummary:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:293
async def _sweep_reserved_trees(self, scope: str) -> None:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:163
class CatalogStore:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:641
def judged_pairs(self, src: str) -> set[str]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:124
def derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str]:
```


### Dependency-produced contracts

- TASK-5430: serializes overlapping writes to packages/ai-parrot/src/parrot/knowledge/bookstore/library.py

Those newly created symbols/files are planned contracts, not claims that they exist at this base. Read prerequisite commits before implementation.

### Does NOT Exist

- Bookstore.doctor and CatalogStore.judgement_count do not exist at the base; judged_pairs counts outgoing only.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_doctor.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.resolve_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.relate_books",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._sweep_reserved_trees",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore.judged_pairs",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py#derive_toc",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/config.py#LibraryLocation",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#BookstoreError"
  ]
}
```

## Implementation Notes

TASK-5430: serializes overlapping writes to packages/ai-parrot/src/parrot/knowledge/bookstore/library.py

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Implement Bookstore.doctor and CatalogStore.judgement_count per spec M4. **Why**: Report contains reserved/books/unjudged_book_ids/errors and optional relate_summary with the exact statuses in spec §2.
2. Scan reserved trees before sweep and preserve action/error reporting; compare live derive_toc digest and entries under the book operation lock. **Why**: Repair is deterministic and updates structural fields safely while preserving manual metadata and invalidating unproven graph state.
3. Repair structural fields only, preserve manual descriptive fields, clear unproven source_sha256, and invalidate graph for repaired structural drift. **Why**: Orphan/busy/error cases are reported without pretending repair succeeded; active imports survive sweep.
4. Report orphan_card without reconstructing missing content; busy/error cases remain explicit. Document identical-TOC content drift limitation. **Why**: No LLM is called for repair; --relate targets only unjudged IDs and zero targets cause no relation call.
5. Count judgement rows touching either endpoint across scopes, including rel=none. Only explicit relate invokes relation work; empty targets never trigger all-books behavior. **Why**: Report contains reserved/books/unjudged_book_ids/errors and optional relate_summary with the exact statuses in spec §2.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'class Bookstore:' packages/ai-parrot/src/parrot/knowledge/bookstore/library.py)
# Container/attachment anchor: class Bookstore:
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:179; merge scoped edits, never replace the whole container.
async def doctor(self, scope: Optional[str] = None, *, repair: bool = False,
                 relate: bool = False, use_llm: bool = True) -> dict[str, Any]:
    """Report recovery, structural drift and missing judgements; optionally repair or relate."""
    # FILL IN: collect request-local report, use book operation locks, reread before upsert,
    # count both judgement endpoints, guard empty relation targets; AC-1..AC-4.
    raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'class CatalogStore:' packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py)
# Container/attachment anchor: class CatalogStore:
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:163; merge scoped edits, never replace the whole container.
def judgement_count(self, book_id: str) -> int:
    """Count judgement rows touching either endpoint, including rel=none."""
    # FILL IN: parameterized COUNT query through existing connection management; AC-4.
    # No schema migration, no exclusion of negative judgements.
    raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/tests/knowledge/bookstore/test_doctor.py` (CREATE)

```python
"""Deterministic regression coverage for this FEAT-858 task."""
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError

@pytest.mark.asyncio
async def test_repair_structural_drift(tmp_path: Path) -> None:
    """Repair updates only proven fields and clears unproven source identity."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_orphan_and_busy_reports(tmp_path: Path) -> None:
    """Doctor reports unrepairable and locked books truthfully."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_judgements_and_empty_targets(tmp_path: Path) -> None:
    """Both endpoints and negative judgements count; no targets means no relate call."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_doctor.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: Report contains reserved/books/unjudged_book_ids/errors and optional relate_summary with the exact statuses in spec §2.
- [ ] AC-2: Repair is deterministic and updates structural fields safely while preserving manual metadata and invalidating unproven graph state.
- [ ] AC-3: Orphan/busy/error cases are reported without pretending repair succeeded; active imports survive sweep.
- [ ] AC-4: No LLM is called for repair; --relate targets only unjudged IDs and zero targets cause no relation call.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_doctor.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_relations.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.


## Agent Instructions

1. Run `$sdd-start TASK-5431` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

Seat gpt-5.6-terra (codex), 1 attempt, 378s. Merged; bookstore tests 228 passed (test_integration_graph.py sqlite env failures, untouched). Review recorded; diff not read line by line.
