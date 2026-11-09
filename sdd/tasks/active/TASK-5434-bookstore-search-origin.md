# TASK-5434: Implement BookstoreOrigin with validated bounded excerpts

**Feature**: FEAT-858 — Bookstore Agentic Retrieval
**Spec**: `sdd/specs/bookstore-agentic-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; host wall time depends on provider when applicable)
**Depends-on**: TASK-5428, TASK-5433
**Assigned-to**: unassigned

## Context

Implement this bounded deliverable of the approved FEAT-858 spec. Its behavioral authority
is the spec's §2 and owning §3 module, with §4 validation and §5 acceptance criteria.
Verified source base: `8387cd3e1b604955928064ff51a2fa207deceb36`. No implementation has been performed by this planning task.

## Scope

- Implement the spec M3 constructor and both search entry points; BOOKSTORE is the only shared enum/model change.
- Filter scopes/book IDs before shortlist; return empty without Bookstore.search when filter yields no IDs. Unknown explicit IDs error.
- Normalize node_list and results/node_id shapes; cap/dedupe candidates, run reads with semaphore four and restore input order.
- Validate exact clipped single-segment content against the returned immutable revision using SegmentStore, offsets and find_any_match; never validate against the excerpt itself.
- Emit at most k deduplicated hits, rank after filtering, preserve score and all citation metadata. Use generation-safe decoration from the facade.
- Use shared private collector for search/search_section; request-local skip diagnostics, explicit timeout and cancellation; never call agentic retrieval.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/bookstore.py` | CREATE | Scoped deliverable described above |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot/src/parrot/models/stores.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot-tools/tests/multistoresearch/test_bookstore_origin.py` | CREATE | Task regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations  # verified: Python language; existing library.py:17
import asyncio  # verified: stdlib; existing library.py:19
from typing import Any, Optional, TYPE_CHECKING  # verified: stdlib typing; existing source annotations above
from parrot.models import OriginHit, OriginSection, SearchOriginKind  # verified: packages/ai-parrot/src/parrot/models/__init__.py:109-117; definitions models/stores.py:31,79,106
from parrot.knowledge.pageindex.segment_store import SegmentStore  # verified: packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py:25
from parrot.knowledge.pageindex.citations import find_any_match  # verified: packages/ai-parrot/src/parrot/knowledge/pageindex/citations.py:102
from parrot_tools.multistoresearch.origins.base import SearchOrigin  # verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:18
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:112,179
import pytest  # verified: existing Bookstore test_toolkit.py:5
from pathlib import Path  # verified: stdlib; existing library.py:26
from unittest.mock import AsyncMock, MagicMock  # verified: stdlib; Bookstore conftest.py:13
from typing import TYPE_CHECKING  # verified: stdlib; existing mcp_server.py:29
from typing import Any, Optional  # verified: stdlib; existing library.py:27
```

### Same-task planned import

`from parrot_tools.multistoresearch.origins.bookstore import BookstoreOrigin` — Created by this task in packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/bookstore.py; planned import, not present at base.

### Existing Signatures to Use

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:495
async def search(
        self,
        query: str,
        book_ids: Optional[list[str]] = None,
        max_books: int = 3,
        top_k: int = 5,
        expand_related: bool = False,
    ) -> dict[str, Any]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:434
async def read_segments(
        self,
        book_id: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        node_id: Optional[str] = None,
        max_chars: int = 12000,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py:87
def load_revision(self, tree_name: str, doc_id: str, revision: str) -> Optional[DocumentRevision]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/citations.py:102
def find_any_match(segment_text: str, excerpt: str) -> bool:
```

```python
# verified: packages/ai-parrot/src/parrot/models/stores.py:79
class OriginHit(BaseModel):
```

```python
# verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:18
class SearchOrigin(ABC):
```


### Dependency-produced contracts

- TASK-5428: consumes Bookstore._decorate_citations and guarded read_segments
- TASK-5433: consumes SearchOrigin.search_section and toolkit section normalization

Those newly created symbols/files are planned contracts, not claims that they exist at this base. Read prerequisite commits before implementation.

### Does NOT Exist

- BookstoreOrigin and SearchOriginKind.BOOKSTORE do not exist at the base; OriginHit has no citation field.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/bookstore.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/models/stores.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/multistoresearch/test_bookstore_origin.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.search",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.read_segments",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py#SegmentStore.load_revision",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/citations.py#find_any_match",
    "sym:packages/ai-parrot/src/parrot/models/stores.py#OriginHit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py#SearchOrigin",
    "sym:packages/ai-parrot/src/parrot/models/stores.py#OriginSection",
    "sym:packages/ai-parrot/src/parrot/models/stores.py#SearchOriginKind",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py#SegmentStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#BookstoreError"
  ]
}
```

## Implementation Notes

TASK-5428: consumes Bookstore._decorate_citations and guarded read_segments; TASK-5433: consumes SearchOrigin.search_section and toolkit section normalization

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Implement the spec M3 constructor and both search entry points; BOOKSTORE is the only shared enum/model change. **Why**: Both stage-1 shapes and empty/unknown/scope filters behave as §2 requires; no unfiltered fallback escapes a filter.
2. Filter scopes/book IDs before shortlist; return empty without Bookstore.search when filter yields no IDs. Unknown explicit IDs error. **Why**: Every emitted excerpt equals stored text at its pinned address with correct offsets, including sub-500 budgets and nonzero starts.
3. Normalize node_list and results/node_id shapes; cap/dedupe candidates, run reads with semaphore four and restore input order. **Why**: Semaphore/k/per-node limits, deduplication and stable ranks hold; failed evidence is counted in per-call section notes.
4. Validate exact clipped single-segment content against the returned immutable revision using SegmentStore, offsets and find_any_match; never validate against the excerpt itself. **Why**: Timeout cancels child work, no agentic loop runs, missing bm25s errors stay origin-isolated, and existing imports/origin kinds remain compatible.
5. Emit at most k deduplicated hits, rank after filtering, preserve score and all citation metadata. Use generation-safe decoration from the facade. **Why**: Both stage-1 shapes and empty/unknown/scope filters behave as §2 requires; no unfiltered fallback escapes a filter.
6. Use shared private collector for search/search_section; request-local skip diagnostics, explicit timeout and cancellation; never call agentic retrieval. **Why**: Every emitted excerpt equals stored text at its pinned address with correct offsets, including sub-500 budgets and nonzero starts.

### `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/bookstore.py` (CREATE)

```python
"""Stage-1 Bookstore origin returning revision-pinned single-segment evidence."""
from __future__ import annotations
import asyncio
from typing import Any, Optional, TYPE_CHECKING
from parrot.models import OriginHit, OriginSection, SearchOriginKind
from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.citations import find_any_match
from parrot_tools.multistoresearch.origins.base import SearchOrigin
if TYPE_CHECKING:
    from parrot.knowledge.bookstore.library import Bookstore, BookstoreError

class BookstoreOrigin(SearchOrigin):
    """Bounded stage-1 search with immutable citation metadata."""
    kind = SearchOriginKind.BOOKSTORE
    supports_fts = False

    def __init__(self, bookstore: Bookstore, *, scope: Optional[str] = None,
                 book_ids: Optional[list[str]] = None, max_books: int = 3,
                 top_k: int = 5, excerpt_chars: int = 600, name: str = "bookstore",
                 description: Optional[str] = None, timeout: Optional[float] = None) -> None:
        """Configure filters and bounds; reject invalid limits, scope and timeout."""
        # FILL IN: validate and initialize fields according to spec §2; AC-1, AC-3.
        raise NotImplementedError

    async def search(self, query: str, k: int) -> list[OriginHit]:
        """Return at most k evidence hits in stable native order."""
        # FILL IN: use common collector with the configured direct-call timeout; AC-3, AC-4.
        raise NotImplementedError

    async def search_section(self, query: str, k: int) -> OriginSection:
        """Return hits and request-local skip counts; backend failures still raise."""
        # FILL IN: same collector, no last_note field; AC-3, AC-4.
        raise NotImplementedError

    async def _collect(self, query: str, k: int) -> OriginSection:
        """Filter, search, read and validate one bounded origin request."""
        # FILL IN: spec §2 origin protocol, immutable revision lookup and cancellation;
        # bounded by AC-1..AC-4. Do not concatenate text from different segments.
        raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'from .wiki import ParrotWikiOrigin' packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py)
# Container/attachment anchor: from .wiki import ParrotWikiOrigin
# verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py:12; merge scoped edits, never replace the whole container.
# Add `from .bookstore import BookstoreOrigin` next to origin imports;
# include "BookstoreOrigin" in __all__. The module is created in this task.
# FILL IN: verify importing existing origins does not eagerly import heavy Bookstore; AC-4.
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/src/parrot/models/stores.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'class SearchOriginKind(Enum):' packages/ai-parrot/src/parrot/models/stores.py)
# Container/attachment anchor: class SearchOriginKind(Enum):
# verified: packages/ai-parrot/src/parrot/models/stores.py:31; merge scoped edits, never replace the whole container.
# Add only this member inside SearchOriginKind:
BOOKSTORE = "bookstore"
# FILL IN: preserve all other enum values and Citation/OriginHit/OriginSection fields; AC-4.
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot-tools/tests/multistoresearch/test_bookstore_origin.py` (CREATE)

```python
"""Deterministic Bookstore origin evidence and isolation tests."""
from parrot_tools.multistoresearch.origins.bookstore import BookstoreOrigin
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from parrot.models import OriginHit, OriginSection, SearchOriginKind

@pytest.mark.asyncio
async def test_scope_and_dual_result_shapes(tmp_path: Path) -> None:
    """Filtered searches normalize LLM/BM25 candidates without scope leakage."""
    # FILL IN: synthetic cards and both result shapes; AC-1.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_pinned_clipped_excerpts(tmp_path: Path) -> None:
    """Evidence is verified against stored revision text, including clipping below 500."""
    # FILL IN: actual temporary segment revisions, invalid offsets and stale revisions; AC-2.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_limits_notes_and_cancellation(tmp_path: Path) -> None:
    """Concurrent reads preserve caps/order and per-request diagnostics."""
    # FILL IN: controlled scheduling, all-skipped case, timeout cancellation, no agentic call; AC-3, AC-4.
    raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/bookstore.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/src/parrot/models/stores.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot-tools/tests/multistoresearch/test_bookstore_origin.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: Both stage-1 shapes and empty/unknown/scope filters behave as §2 requires; no unfiltered fallback escapes a filter.
- [ ] AC-2: Every emitted excerpt equals stored text at its pinned address with correct offsets, including sub-500 budgets and nonzero starts.
- [ ] AC-3: Semaphore/k/per-node limits, deduplication and stable ranks hold; failed evidence is counted in per-call section notes.
- [ ] AC-4: Timeout cancels child work, no agentic loop runs, missing bm25s errors stay origin-isolated, and existing imports/origin kinds remain compatible.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/multistoresearch/test_bookstore_origin.py -q`
- `pytest packages/ai-parrot-tools/tests/multistoresearch/test_pageindex_origin.py -q`
- `pytest packages/ai-parrot-tools/tests/multistoresearch/test_wiki_origin.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.


## Agent Instructions

1. Run `$sdd-start TASK-5434` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

Populated by the task finalizer after implementation, validation and the exact implementation commit.
