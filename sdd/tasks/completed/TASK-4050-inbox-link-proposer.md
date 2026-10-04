# TASK-4050: Retrieve and verify inbox link proposals

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4047
**Assigned-to**: unassigned

## Context

Implements spec §3 M4 for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- AC5: Combine search(title+tags+claims, include_archived=False), per-tag search_fts, and explicit sym:/file:/backticked-path mentions. Dedupe and exclude own doc/child ids before enforcing max_candidates (default 20, top_k=15).
- Code pages enter only through the verbatim branch, even when search returns them. Preserve verbatim origin on duplicates so deterministic fallback retains them. Build candidates through get_page and recheck final selected targets.
- AC20: A non-LinkSelection value, missing adapter or exception degrades to verbatim-only references. Filter relation vocabulary, candidate membership, duplicate targets (first wins), and log LINK_DROPPED for missing/invalid targets. Self ids are excluded in candidates(exclude_ids); select must never invent the current doc id from title alone.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py` | CREATE | Scoped M4 deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_links.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
```
Verified: packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:42.

```python
from parrot.knowledge.wiki.inbox.links import LinkProposer
```
Verified: planned in TASK-4050: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py#LinkProposer.

```python
from parrot.knowledge.wiki.inbox.models import RELATIONS, LinkCandidate, LinkSelection, ResolvedClassification, VerifiedLink
```
Verified: planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#RELATIONS; planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#LinkCandidate; planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#LinkSelection; planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#ResolvedClassification; planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#VerifiedLink.

```python
from parrot.knowledge.wiki.review import Claim
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/review.py:74.

```python
from parrot.knowledge.wiki.search import WikiCombinedSearch
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/search.py:32.

```python
from parrot.knowledge.wiki.store import BaseWikiStore
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525.

```python
from pathlib import Path
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import logging
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import pytest
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import re
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).


### Existing Signatures to Use

`sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter`

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:42
class PageIndexLLMAdapter:

    def __init__(
        self,
        client: AbstractClient,
        model: Optional[str] = "gemini-3.1-flash-lite-preview",
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
```

`sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter.ask_structured`

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:99
    async def ask_structured(
        self,
        prompt: str,
        output_type: type,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> Any:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#WikiSearchResult`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py:258
class WikiSearchResult(BaseModel):
    node_id: str = Field(..., description='Stable node/page identifier')
    title: str = Field(..., description='Page or node title')
    score: float = Field(..., ge=0.0, le=1.0, description='Normalised relevance score in [0, 1]')
    source: str = Field(..., description="Search leg: 'lexical'/'vector' (WikiStore) or 'pageindex'/'graphindex' (legacy)")
    token_count: int | None = Field(default=None, ge=0, description='Token cost of the full page body (for budgeting)')
    snippet: str = Field(default='', description='Short content excerpt or summary')
    category: WikiPageCategory | None = Field(default=None, description='Wiki page category if known')
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/review.py#Claim`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/review.py:74
class Claim(BaseModel):
    text: str
    grounded: bool | None = None
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/search.py#WikiCombinedSearch`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/search.py:32
class WikiCombinedSearch:

    def __init__(
        self,
        pageindex_toolkit: Any,
        graphindex_toolkit: Any,
        default_weights: Optional[dict[str, float]] = None,
        store: Optional[BaseWikiStore] = None,
        embedder: Optional[Callable[[str], Awaitable[list[float]]]] = None,
        normalize_store_rows: bool = True,
    ) -> None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/search.py#WikiCombinedSearch.search`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/search.py:91
    async def search(
        self,
        query: str,
        mode: str = "combined",
        top_k: int = 10,
        tree_name: Optional[str] = None,
        weights: Optional[dict[str, float]] = None,
        include_archived: bool = False,
    ) -> list[WikiSearchResult]:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.get_page`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:565

```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.search_fts`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:576

```


### Does NOT Exist

- WikiSearchResult.page_id/concept_id do not exist; the result key is node_id.
- select has no doc_id parameter; candidates receives exclude_ids, including the current doc id.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_links.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter.ask_structured",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#WikiSearchResult",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/review.py#Claim",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/search.py#WikiCombinedSearch",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/search.py#WikiCombinedSearch.search",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.get_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.search_fts"
  ]
}
```

## Implementation Notes

Consumes LinkCandidate, LinkSelection, VerifiedLink and ResolvedClassification from TASK-4047.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py` (CREATE)

```python
"""Retrieve, select and reverify document relations."""
import logging
import re
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.wiki.review import Claim
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.inbox.models import (
    RELATIONS, LinkCandidate, LinkSelection, ResolvedClassification, VerifiedLink,
)
# FILL IN: compiled regex matching explicit sym:/file: ids and backticked paths (AC5).
_VERBATIM_RE: re.Pattern[str]

class LinkProposer:
    """Select only existing pages from a bounded candidate set."""
    def __init__(self, store: BaseWikiStore, search: WikiCombinedSearch, adapter: PageIndexLLMAdapter | None,
                 *, max_candidates: int = 20, top_k: int = 15) -> None:
        """Bind retrieval and optional model selection dependencies."""
        self.store = store
        self.search = search
        self.adapter = adapter
        self.max_candidates = max_candidates
        self.top_k = top_k
        self.logger = logging.getLogger(__name__)
    async def candidates(self, text: str, classification: ResolvedClassification, claims: list[Claim],
                         exclude_ids: set[str]) -> list[LinkCandidate]:
        """Retrieve and dedupe candidates, excluding own pages before the cap."""
        # FILL IN: AC5 retrieval sources, explicit code mentions and excludes.
        raise NotImplementedError
    async def select(self, text: str, classification: ResolvedClassification,
                     candidates: list[LinkCandidate]) -> list[VerifiedLink]:
        """Validate selected relations and re-read targets, degrading on model failure."""
        # FILL IN: isinstance guard and AC5/20 filtering, including fallback target rechecks.
        raise NotImplementedError
    @staticmethod
    def deterministic_links(candidates: list[LinkCandidate]) -> list[VerifiedLink]:
        """Return references for verbatim candidates, with reason verbatim mention."""
        # FILL IN: verbatim-only, deduped in input order (AC5).
        raise NotImplementedError
```

**Why**: Reverify fallback links as well as model-selected links so deleted targets cannot become edges.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_links.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.inbox.links import LinkProposer


def test_candidates_cap_and_exclusion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dedupe more than 30 hits, exclude own pages and honor the cap."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_code_pages_only_on_verbatim_mention(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Search cannot introduce unmentioned code pages."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_select_verifies_ids_and_relations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop invented, deleted and invalid-relation targets."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_select_degrades_without_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing, raising and malformed adapters return only verified verbatim links."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_select_drops_duplicates_and_self_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise own-id exclusion through candidates then select and keep first duplicates."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_links.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] AC5: Combine search(title+tags+claims, include_archived=False), per-tag search_fts, and explicit sym:/file:/backticked-path mentions. Dedupe and exclude own doc/child ids before enforcing max_candidates (default 20, top_k=15).
- [ ] Code pages enter only through the verbatim branch, even when search returns them. Preserve verbatim origin on duplicates so deterministic fallback retains them. Build candidates through get_page and recheck final selected targets.
- [ ] AC20: A non-LinkSelection value, missing adapter or exception degrades to verbatim-only references. Filter relation vocabulary, candidate membership, duplicate targets (first wins), and log LINK_DROPPED for missing/invalid targets. Self ids are excluded in candidates(exclude_ids); select must never invent the current doc id from title alone.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_links.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Use a fake search and mutable in-memory fake store; delete a candidate between retrieval and selection.
- For deliberately malformed relation payloads, bypass Pydantic validation in the fake response explicitly; normal LinkChoice creation must still reject bad relations.
- Verify self-links through the full candidates→select boundary because the fixed select signature contains no doc_id parameter.

## Agent Instructions

1. Use `$sdd-start TASK-4050`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.


### Completion Note (orchestrator)
Seat: sonnet (native). Merged cleanly; merge-tier validation green (55 passed). No defects confirmed.
