---
type: Wiki Overview
title: 'TASK-1633: LLMWikiToolkit'
id: doc:sdd-tasks-active-task-1633-llmwiki-toolkit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The main agent-facing toolkit. Composes PageIndexToolkit + GraphIndexToolkit
  +
relates_to:
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.tools
  rel: mentions
- concept: mod:parrot.knowledge.wiki.bookkeeper
  rel: mentions
- concept: mod:parrot.knowledge.wiki.ingest
  rel: mentions
- concept: mod:parrot.knowledge.wiki.models
  rel: mentions
- concept: mod:parrot.knowledge.wiki.search
  rel: mentions
- concept: mod:parrot.knowledge.wiki.sources
  rel: mentions
- concept: mod:parrot.knowledge.wiki.toolkit
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

# TASK-1633: LLMWikiToolkit

**Feature**: FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex
**Spec**: `sdd/specs/llmwiki-pageindex-graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1627, TASK-1628, TASK-1629, TASK-1630, TASK-1631, TASK-1632
**Assigned-to**: unassigned

---

## Context

The main agent-facing toolkit. Composes PageIndexToolkit + GraphIndexToolkit +
OKFToolkit and wires them to the wiki-specific modules (ingest, search,
bookkeeper, sources). All public async methods become agent tools with
`tool_prefix = "wiki"`. Implements Spec §3 Module 7 and §2 New Public
Interfaces.

---

## Scope

- Implement `LLMWikiToolkit` extending `AbstractToolkit` with:
  - Core ops: `ingest_source`, `query`, `lint`
  - Wiki management: `create_wiki`, `list_wikis`, `get_wiki_info`, `delete_wiki`
  - Page ops: `browse_pages`, `read_page`, `create_page`, `update_page`, `delete_page`
  - Source ops: `list_sources`, `get_source_info`, `reingest_source`
  - Search: `search`, `find_related`
  - Bookkeeping: `get_index`, `get_log`, `rebuild_index`
- Set `tool_prefix = "wiki"` so tools are namespaced as `wiki_ingest_source`, etc.
- Compose private toolkit attributes: `_pi`, `_gi`, `_okf`
- Compose helper instances: `_ingest_orch`, `_search`, `_bookkeeper`, `_sources`
- Wire `query` to use combined search, synthesize answer via LLM, optionally
  file answer as a new wiki page
- Wire `lint` to delegate to OKFToolkit.lint_knowledge_base() plus
  wiki-specific checks
- Write unit tests with mocked dependencies

**NOT in scope**: Bot integration (TASK-1634), package init (TASK-1635)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | CREATE | LLMWikiToolkit |
| `tests/knowledge/wiki/test_toolkit.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit  # line 207
from parrot.knowledge.wiki.models import (
    WikiConfig, WikiPageCategory, WikiSearchResult, WikiLintReport,
)
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
from parrot.knowledge.pageindex import PageIndexToolkit  # __init__.py
from parrot.knowledge.pageindex.okf.tools import OKFToolkit  # line 46
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):  # line 207
    tool_prefix: Optional[str] = None  # line 258
    prefix_separator: str = "_"  # line 261
    def __init__(self, **kwargs):  # line 278
    def get_tools(self, permission_context=None, resolver=None) -> List[AbstractTool]:  # line 385

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):  # line 50
    tool_prefix: str = "pageindex"  # line 86
    async def list_trees(self) -> list[str]:  # line 373
    async def create_tree(self, tree_name, doc_name=None) -> dict:  # line 377
    async def search(self, tree_name, query, top_k=10, ...) -> list[dict]:  # line 414
    async def delete_tree(self, tree_name) -> dict:  # line 398
    async def insert_markdown(self, tree_name, markdown, ...) -> dict:  # line 692

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py
class OKFToolkit:  # line 46
    async def lint_knowledge_base(self, stale_days=90) -> dict:  # line 287
    async def find_by_type(self, concept_type, query) -> list[dict]:  # line 106
    async def list_concepts(self, concept_type=None) -> list[dict]:  # line 143
```

### Does NOT Exist

- ~~`parrot.knowledge.wiki.toolkit`~~ — does not exist yet; this task creates it
- ~~`LLMWikiToolkit`~~ — does not exist yet
- ~~`AbstractToolkit.compose`~~ — no such method; composition is manual via __init__
- ~~`OKFToolkit.tool_prefix`~~ — OKFToolkit does NOT set tool_prefix (inherits None)
- ~~`AbstractToolkit.register_sub_toolkit`~~ — no such method

---

## Implementation Notes

### Pattern to Follow

```python
class LLMWikiToolkit(AbstractToolkit):
    tool_prefix: str = "wiki"

    def __init__(
        self,
        pageindex_toolkit: PageIndexToolkit,
        graphindex_toolkit: GraphIndexToolkit,
        okf_toolkit: OKFToolkit,
        config: WikiConfig,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._pi = pageindex_toolkit
        self._gi = graphindex_toolkit
        self._okf = okf_toolkit
        self._config = config
        self._sources = SourceCollectionManager(config.storage_dir / "sources")
        self._bookkeeper = WikiBookkeeper()
        self._search = WikiCombinedSearch(
            pageindex_toolkit, graphindex_toolkit, config.search_weights
        )
        self._ingest = WikiIngestOrchestrator(
            pageindex_toolkit, graphindex_toolkit,
            self._sources, self._bookkeeper,
        )
        self.logger = logging.getLogger(__name__)

    async def ingest_source(self, wiki_name: str, source_path: str,
                            source_type: Optional[str] = None) -> dict:
        """Ingest a raw source document into the wiki."""
        report = await self._ingest.ingest(source_path, self._config)
        return report.model_dump()
```

### Key Constraints

- All public async methods become agent tools via AbstractToolkit
- Each method must have a clear docstring (becomes the tool description for LLM)
- Methods must return dicts (JSON-serializable for tool responses)
- `query` with `file_answer=True` must call `create_page` after synthesis
- `lint` must merge OKF report with wiki-specific checks

---

## Acceptance Criteria

- [ ] `tool_prefix = "wiki"` produces tools like `wiki_ingest_source`
- [ ] All 18+ async methods implemented per Spec §2 New Public Interfaces
- [ ] Each method has a docstring (for LLM tool descriptions)
- [ ] `create_wiki` sets up directory structure with sources/, wiki/, index.md, log.md
- [ ] `query` uses combined search and synthesizes answer
- [ ] `query` with `file_answer=True` creates a wiki page from the answer
- [ ] `lint` combines OKF lint report with wiki-specific checks
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_toolkit.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
from parrot.knowledge.wiki.models import WikiConfig

@pytest.fixture
def wiki_toolkit(tmp_path):
    config = WikiConfig(wiki_name="test", storage_dir=tmp_path)
    pi = MagicMock()
    gi = MagicMock()
    okf = MagicMock()
    return LLMWikiToolkit(pi, gi, okf, config)

class TestLLMWikiToolkit:
    def test_tool_prefix(self, wiki_toolkit):
        assert wiki_toolkit.tool_prefix == "wiki"

    @pytest.mark.asyncio
    async def test_create_wiki(self, wiki_toolkit, tmp_path):
        result = await wiki_toolkit.create_wiki("my-wiki")
        assert (tmp_path / "wiki").exists() or result.get("status") == "created"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/llmwiki-pageindex-graphindex.spec.md` §2 + §3 Module 7
2. **Check dependencies** — ALL previous tasks (1627-1632) must be completed
3. **Implement** all methods listed in Spec §2 New Public Interfaces
4. **Ensure** every method has a docstring for LLM tool descriptions
5. **Verify** all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
