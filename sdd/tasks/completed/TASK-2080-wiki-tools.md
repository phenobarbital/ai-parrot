# TASK-2080: Create wiki AbstractTool wrappers

**Feature**: FEAT-403 — MCP Local Server Core + WikiToolkit MCP
**Spec**: `sdd/specs/mcp-local-server-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2076, TASK-2077, TASK-2078
**Assigned-to**: unassigned

---

## Context

This task creates six `AbstractTool` subclasses that wrap wikitoolkit's
store and authoring layer. These tools will be registered with the
StdioMCPServer in TASK-2081 to expose wiki operations as native MCP tools.

Implements spec Module 5.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` with:
  - `WikiQueryTool` — search via `store.search_fts()` + `pack_results()`
  - `WikiPageTool` — read page via `store.get_page()`
  - `WikiRelatedTool` — edges via `store.neighbors()`
  - `WikiRememberTool` — save knowledge (delegates to inline authoring)
  - `WikiNoteTool` — append note to page (read-modify-write pattern)
  - `WikiStatusTool` — plane stats via `store.stats()`
  - `create_wiki_tools(store, root, config)` factory function
- Pydantic input schemas for each tool
- Write unit tests with mocked store

**NOT in scope**: MCP server wiring (TASK-2081), CLI command (TASK-2081), installer (TASK-2082).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | CREATE | Six wiki tools + factory |
| `packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Core tools
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: abstract.py:233,198

# Wiki store layer
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store, WikiPageRecord  # verified: store.py:289,1217
from parrot.knowledge.wiki.context import pack_results, DEFAULT_BUDGET_TOKENS  # verified: context.py:131,36
from parrot.knowledge.wiki.project import WikiProjectConfig, find_project_root, load_project_config  # verified: project.py:122,239,266

# Pydantic
from pydantic import BaseModel, Field
```

### Existing Signatures to Call
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):  # line 289
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict]  # line 331
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict]  # line 344
    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict]  # line 354
    async def stats(self) -> dict[str, Any]  # line 368
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int  # line 308

# packages/ai-parrot/src/parrot/knowledge/wiki/context.py
DEFAULT_BUDGET_TOKENS = 1200  # line 36
def pack_results(results, budget_tokens=DEFAULT_BUDGET_TOKENS, ...) -> ...  # line 131
```

### Does NOT Exist (CRITICAL)
- ~~`BaseWikiStore.query()`~~ — NOT a method. Use `search_fts()` (line 344).
- ~~`BaseWikiStore.status()`~~ — the method is called `stats()` (line 368), NOT `status()`.
- ~~`BaseWikiStore.add_note()`~~ — NOT a method. Notes are appended by: (1) read page, (2) modify body, (3) `upsert_pages()`. See `cli.py:1741`.
- ~~`WikiToolkit.add_note()`~~ — NOT a method on toolkit. Note logic is inline in `cli.py:1741`.
- ~~`parrot.knowledge.wiki.tools`~~ — does not exist yet; this task creates it.

---

## Implementation Notes

### Tool Pattern
Each tool follows the standard `AbstractTool` subclass pattern:
```python
class WikiQueryTool(AbstractTool):
    name = "wiki_query"
    description = "Search the codebase knowledge graph..."
    args_schema = WikiQueryInput

    def __init__(self, store: BaseWikiStore):
        super().__init__()
        self._store = store

    async def _execute(self, question: str, budget_tokens: int = 1200) -> str:
        results = await self._store.search_fts(question)
        packed = pack_results(results, budget_tokens=budget_tokens)
        return packed
```

### WikiNoteTool — Read-Modify-Write Pattern
The note tool must replicate the logic from `cli.py:1741-1790`:
1. `get_page(page_id, include_body=True)` to read current body
2. Append the note text with a timestamp header to the body
3. Create a `WikiPageRecord` with the updated body
4. `upsert_pages([record])` to save

### WikiRememberTool
For simplicity, implement remember inline rather than requiring a full
`WikiToolkit` instance. The core logic is:
1. Create a `WikiPageRecord` with category, title, and fact as body
2. `upsert_pages([record])` to save
3. Optionally link to `link_page_id` if provided

### Tool Descriptions (for LLM)
These descriptions are critical — they determine when the LLM selects the tool:
- `wiki_query`: "Search the codebase knowledge graph for files, modules, symbols, or concepts. Returns ranked page stubs with IDs for drill-down. Use BEFORE grep/find/Read on large repos."
- `wiki_page`: "Read a full wiki page by ID — file summaries, API outlines, content. Use IDs returned by wiki_query."
- `wiki_related`: "Follow typed edges (contains, references) from a wiki page to discover connected files and modules."
- `wiki_remember`: "Save durable knowledge to the knowledge graph — decisions, gotchas, cross-file relationships. Survives across sessions."
- `wiki_note`: "Append a dated note to an existing wiki page."
- `wiki_status`: "Check knowledge graph health: page count, staleness, last build time."

### Key Constraints
- Tools receive the store instance via constructor (injected by factory)
- All tools are async
- Return strings or JSON-serialized dicts (the adapter handles MCP conversion)

---

## Acceptance Criteria

- [ ] Six tools importable from `parrot.knowledge.wiki.tools`
- [ ] `create_wiki_tools(store, root, config)` returns list of 6 tools
- [ ] `wiki_query` calls `store.search_fts()` + `pack_results()` correctly
- [ ] `wiki_page` calls `store.get_page()` correctly
- [ ] `wiki_related` calls `store.neighbors()` correctly
- [ ] `wiki_remember` creates a page via `store.upsert_pages()`
- [ ] `wiki_note` reads page, appends note, upserts back
- [ ] `wiki_status` calls `store.stats()`
- [ ] All tools have proper `args_schema` Pydantic models
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.wiki.tools import (
    WikiQueryTool, WikiPageTool, WikiRelatedTool,
    WikiRememberTool, WikiNoteTool, WikiStatusTool,
    create_wiki_tools,
)


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.search_fts.return_value = [
        {"concept_id": "page-1", "title": "Test Page", "score": 0.9}
    ]
    store.get_page.return_value = {
        "concept_id": "page-1", "title": "Test Page", "body": "Content here"
    }
    store.neighbors.return_value = [
        {"concept_id": "page-2", "title": "Related", "rel": "references"}
    ]
    store.stats.return_value = {"total_pages": 100, "last_build": "2026-08-01"}
    store.upsert_pages.return_value = 1
    return store


class TestWikiQueryTool:
    @pytest.mark.asyncio
    async def test_query_returns_results(self, mock_store):
        tool = WikiQueryTool(mock_store)
        result = await tool._execute(question="test query")
        mock_store.search_fts.assert_called_once()
        assert isinstance(result, str)

class TestWikiPageTool:
    @pytest.mark.asyncio
    async def test_get_page(self, mock_store):
        tool = WikiPageTool(mock_store)
        result = await tool._execute(page_id="page-1")
        mock_store.get_page.assert_called_once_with("page-1", include_body=True)

class TestWikiRelatedTool:
    @pytest.mark.asyncio
    async def test_get_related(self, mock_store):
        tool = WikiRelatedTool(mock_store)
        result = await tool._execute(page_id="page-1")
        mock_store.neighbors.assert_called_once()

class TestWikiRememberTool:
    @pytest.mark.asyncio
    async def test_remember_saves(self, mock_store):
        tool = WikiRememberTool(mock_store)
        result = await tool._execute(fact="Important finding", category="decision")
        mock_store.upsert_pages.assert_called_once()

class TestWikiNoteTool:
    @pytest.mark.asyncio
    async def test_note_appends(self, mock_store):
        tool = WikiNoteTool(mock_store)
        result = await tool._execute(page_id="page-1", text="A note")
        mock_store.get_page.assert_called_once()
        mock_store.upsert_pages.assert_called_once()

class TestWikiStatusTool:
    @pytest.mark.asyncio
    async def test_status_returns_stats(self, mock_store):
        tool = WikiStatusTool(mock_store)
        result = await tool._execute()
        mock_store.stats.assert_called_once()

class TestFactory:
    def test_create_wiki_tools(self, mock_store):
        tools = create_wiki_tools(mock_store)
        assert len(tools) == 6
        names = {t.name for t in tools}
        assert names == {"wiki_query", "wiki_page", "wiki_related",
                         "wiki_remember", "wiki_note", "wiki_status"}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2076, 2077, 2078 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — especially the "Does NOT Exist" section
4. **Read `cli.py:1741-1790`** for the note append pattern before implementing WikiNoteTool
5. **Update status** in `sdd/tasks/index/mcp-local-server-wikitoolkit.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2080-wiki-tools.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-03
**Notes**: Created six `AbstractTool` subclasses (`WikiQueryTool`,
`WikiPageTool`, `WikiRelatedTool`, `WikiRememberTool`, `WikiNoteTool`,
`WikiStatusTool`) plus their Pydantic `args_schema` input models
(verbatim from the spec's Data Models section) and the
`create_wiki_tools(store, root, config)` factory in
`parrot/knowledge/wiki/tools.py`. Each tool passes `name`/`description`
explicitly to `super().__init__()` (not relying on `__doc__` fallback —
`AbstractTool.__init__` overwrites `self.description` with
`description or self.__class__.__doc__ or ...`, so the class attribute
alone would be silently discarded; also added matching docstrings for
readability). `wiki_query` calls `store.search_fts()` then
`pack_results()`, returning `packed.text` (a plain string, matching the
test's `isinstance(result, str)` assertion). `wiki_remember` mirrors
`cli.py:remember`'s deterministic `mem-<sha1>` id scheme (title+category
hash) and optionally calls `store.add_edges()` when `link_page_id` is
given. `wiki_note` replicates the read-modify-write pattern from
`cli.py:1741-1790` verbatim (no `store.add_note()` exists). Both use a
simplified `asserted_by="agent:mcp"` instead of the CLI's full
`_authoring_identity()` resolution, per the task's explicit simplification
note. All 10 unit tests pass (6 from the task's Test Specification +
4 extra for not-found/error paths); `ruff check` clean on both files.

**Deviations from spec**: none in substance — `super().__init__(name=...,
description=...)` (explicit kwargs) is used instead of the bare
`super().__init__()` shown in the task's illustrative snippet, to avoid
the constructor's docstring-fallback overwriting the class-level
`description`; this is a correctness fix, not a design change.
