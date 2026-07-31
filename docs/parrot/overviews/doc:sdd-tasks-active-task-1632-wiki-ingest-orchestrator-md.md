---
type: Wiki Overview
title: 'TASK-1632: Wiki Ingest Orchestrator'
id: doc:sdd-tasks-active-task-1632-wiki-ingest-orchestrator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the core "Ingest" operation from Karpathy's 3-layer architecture.
relates_to:
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.knowledge.wiki.bookkeeper
  rel: mentions
- concept: mod:parrot.knowledge.wiki.ingest
  rel: mentions
- concept: mod:parrot.knowledge.wiki.models
  rel: mentions
- concept: mod:parrot.knowledge.wiki.sources
  rel: mentions
---

# TASK-1632: Wiki Ingest Orchestrator

**Feature**: FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex
**Spec**: `sdd/specs/llmwiki-pageindex-graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1627, TASK-1629, TASK-1630
**Assigned-to**: unassigned

---

## Context

Implements the core "Ingest" operation from Karpathy's 3-layer architecture.
Orchestrates the full pipeline: load source → process via TwoStepIngester →
create/update wiki pages in PageIndex → sync to GraphIndex → update manifest →
update index.md + log.md. This is the most complex module. Implements Spec
§3 Module 6.

---

## Scope

- Implement `WikiIngestOrchestrator` class with:
  - `ingest(source_path, wiki_config) -> IngestReport` — full pipeline
  - `_load_source(source_path) -> str` — read source content (use loaders
    or direct file read for markdown)
  - `_process_source(content, hint) -> IngestedMarkdown` — delegate to
    TwoStepIngester
  - `_create_wiki_pages(ingested, tree_name) -> list[str]` — insert into
    PageIndex tree, return page IDs
  - `_sync_to_graph(page_ids, source_uri) -> None` — create WIKI_PAGE
    nodes in GraphIndex, link to source
  - `_update_bookkeeping(wiki_dir, operation, details) -> None` — delegate
    to WikiBookkeeper
- Implement `IngestReport` model (source_id, pages_created, pages_updated,
  graph_nodes_created, duration_ms)
- Handle reingest: detect stale sources, replace existing pages
- Write unit tests with mocked toolkits

**NOT in scope**: Multi-source batch ingest, toolkit API (TASK-1633)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py` | CREATE | WikiIngestOrchestrator + IngestReport |
| `tests/knowledge/wiki/test_ingest.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.models import WikiConfig, SourceManifestEntry  # TASK-1627
from parrot.knowledge.wiki.sources import SourceCollectionManager  # TASK-1629
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper  # TASK-1630
from parrot.knowledge.pageindex import (
    PageIndexToolkit,  # line 42
    TwoStepIngester,   # line 40
    IngestedMarkdown,  # line 41
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/ingest.py
class TwoStepIngester:  # line 43
    async def ingest(self, content: str, hint: Optional[str] = None) -> IngestedMarkdown:  # line 62

class IngestedMarkdown(BaseModel):  # line 35
    title: str   # line 38
    summary: str  # line 39
    markdown: str  # line 40

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):  # line 50
    async def insert_markdown(self, tree_name, markdown, parent_node_id=None,
                              doc_name=None) -> dict:  # line 692
    async def insert_content(self, tree_name, content, parent_node_id=None,
                             hint=None) -> dict:  # line 730
    async def create_tree(self, tree_name, doc_name=None) -> dict:  # line 377

# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py
class GraphIndexToolkit(AbstractToolkit):  # line 63
    async def create_node(self, kind, title, summary=None, source_uri=None,
                          parent_id=None, domain_tags=None) -> dict:  # line 512
    async def link_nodes(self, source_id, target_id, kind,
                         confidence=None) -> dict:  # line 595
```

### Does NOT Exist

- ~~`parrot.knowledge.wiki.ingest`~~ — does not exist yet; this task creates it
- ~~`WikiIngestOrchestrator`~~ — does not exist yet
- ~~`PageIndexToolkit.ingest_source`~~ — no such method; use `insert_content` or `insert_markdown`
- ~~`GraphIndexToolkit.create_wiki_page`~~ — no such method; use `create_node(kind="wiki_page")`

---

## Implementation Notes

### Pattern to Follow

```python
class WikiIngestOrchestrator:
    def __init__(
        self,
        pageindex_toolkit: PageIndexToolkit,
        graphindex_toolkit: GraphIndexToolkit,
        source_manager: SourceCollectionManager,
        bookkeeper: WikiBookkeeper,
    ) -> None:
        self._pi = pageindex_toolkit
        self._gi = graphindex_toolkit
        self._sources = source_manager
        self._bookkeeper = bookkeeper
        self.logger = logging.getLogger(__name__)

    async def ingest(self, source_path: str, wiki_config: WikiConfig) -> IngestReport:
        # 1. Check if source already tracked and stale
        # 2. Load source content
        # 3. Process via TwoStepIngester (via PageIndexToolkit.insert_content)
        # 4. Create WIKI_PAGE nodes in GraphIndex
        # 5. Link graph nodes to source
        # 6. Update manifest
        # 7. Update bookkeeping (index.md, log.md)
        # 8. Return IngestReport
```

### Key Constraints

- Use `insert_content` (which internally uses TwoStepIngester) for automatic
  processing, or `insert_markdown` for pre-processed content
- GraphIndex node creation uses `kind="wiki_page"` (after TASK-1628 adds it)
- Graph links use EdgeKind.REFERENCES for wiki-page-to-source connections
- All operations must be async
- On ingest failure, log the error but don't leave partial state

---

## Acceptance Criteria

- [ ] Full ingest pipeline works: source → pages → graph → bookkeeping
- [ ] Reingest detects stale sources and updates pages
- [ ] IngestReport captures all metrics
- [ ] Error handling: partial failures logged, no corrupt state
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_ingest.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator, IngestReport

@pytest.fixture
def mock_pi():
    pi = MagicMock()
    pi.insert_content = AsyncMock(return_value={"tree_name": "wiki", "nodes_added": 3})
    pi.create_tree = AsyncMock(return_value={"tree_name": "wiki"})
    return pi

@pytest.fixture
def mock_gi():
    gi = MagicMock()
    gi.create_node = AsyncMock(return_value={"node_id": "wp-001"})
    gi.link_nodes = AsyncMock(return_value={"status": "ok"})
    return gi

class TestWikiIngestOrchestrator:
    @pytest.mark.asyncio
    async def test_ingest_source(self, mock_pi, mock_gi, tmp_path):
        source = tmp_path / "article.md"
        source.write_text("# Test\n\nContent")
        # ... setup source_manager and bookkeeper mocks
        # orch = WikiIngestOrchestrator(mock_pi, mock_gi, ...)
        # report = await orch.ingest(str(source), wiki_config)
        # assert isinstance(report, IngestReport)
        # assert report.pages_created > 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/llmwiki-pageindex-graphindex.spec.md` §3 Module 6
2. **Check dependencies** — TASK-1627, TASK-1629, TASK-1630 must be completed
3. **Read** the TwoStepIngester at `pageindex/ingest.py:43-106` for the two-step pattern
4. **Implement** the orchestrator with mocked tests
5. **Verify** all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
