---
type: Wiki Entity
title: LLMWikiToolkit
id: class:parrot.knowledge.wiki.toolkit.LLMWikiToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Orchestrates PageIndex + GraphIndex + OKF into a persistent LLM wiki.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# LLMWikiToolkit

Defined in [`parrot.knowledge.wiki.toolkit`](../summaries/mod:parrot.knowledge.wiki.toolkit.md).

```python
class LLMWikiToolkit(AbstractToolkit)
```

Orchestrates PageIndex + GraphIndex + OKF into a persistent LLM wiki.

This is the agent-facing surface of FEAT-260.  Construct with three
toolkit dependencies and a :class:`WikiConfig`, then call
``get_tools()`` to obtain the list of LLM-callable tools.

Tool prefix: ``"wiki"`` — all tools are namespaced as
``wiki_<method_name>`` (e.g. ``wiki_ingest_source``, ``wiki_query``).

Attributes:
    tool_prefix: Set to ``"wiki"`` to namespace all tools.
    _pi: Composed ``PageIndexToolkit`` instance.
    _gi: Composed ``GraphIndexToolkit`` instance.
    _okf: Composed ``OKFToolkit`` instance.
    _config: Per-wiki-instance configuration.
    _sources: :class:`SourceCollectionManager` for source tracking.
    _bookkeeper: :class:`WikiBookkeeper` for index/log management.
    _search: :class:`WikiCombinedSearch` for unified retrieval.
    _ingest: :class:`WikiIngestOrchestrator` for ingest pipeline.

Example::

    toolkit = LLMWikiToolkit(pi_toolkit, gi_toolkit, okf_toolkit, config)
    tools = toolkit.get_tools()  # registers 18+ tools with the LLM

## Methods

- `async def ingest_source(self, wiki_name: str, source_path: str, source_type: Optional[str]=None) -> dict[str, Any]` — Ingest a raw source document into the wiki.
- `async def query(self, wiki_name: str, question: str, file_answer: bool=False, mode: str='combined') -> dict[str, Any]` — Query the wiki and optionally file the answer as a new page.
- `async def lint(self, wiki_name: str, fix: bool=False) -> dict[str, Any]` — Run OKF lint and wiki-specific checks on the wiki.
- `async def create_wiki(self, wiki_name: str, description: Optional[str]=None) -> dict[str, Any]` — Create a new wiki with its directory structure.
- `async def list_wikis(self) -> list[dict[str, Any]]` — List all wikis accessible via this toolkit.
- `async def get_wiki_info(self, wiki_name: str) -> dict[str, Any]` — Return metadata about a specific wiki.
- `async def delete_wiki(self, wiki_name: str) -> dict[str, Any]` — Delete a wiki and all its data.
- `async def browse_pages(self, wiki_name: str, category: Optional[str]=None, search: Optional[str]=None) -> list[dict[str, Any]]` — Browse wiki pages, optionally filtered by category or search query.
- `async def read_page(self, wiki_name: str, page_id: str, max_tokens: Optional[int]=None) -> dict[str, Any]` — Read the full content of a wiki page by its ID.
- `async def create_page(self, wiki_name: str, title: str, content: str, category: str='concept', related_pages: Optional[list[str]]=None) -> dict[str, Any]` — Create a new wiki page with the given content.
- `async def update_page(self, wiki_name: str, page_id: str, content: str, reason: Optional[str]=None) -> dict[str, Any]` — Update the content of an existing wiki page.
- `async def delete_page(self, wiki_name: str, page_id: str) -> dict[str, Any]` — Delete a wiki page.
- `async def list_sources(self, wiki_name: str) -> list[dict[str, Any]]` — List all tracked raw sources for a wiki.
- `async def get_source_info(self, wiki_name: str, source_id: str) -> dict[str, Any]` — Get metadata for a single tracked source.
- `async def reingest_source(self, wiki_name: str, source_id: str) -> dict[str, Any]` — Force re-ingest of a source regardless of staleness.
- `async def search(self, wiki_name: str, query: str, mode: str='combined') -> list[dict[str, Any]]` — Search the wiki with a natural-language query.
- `async def search_compact(self, wiki_name: str, query: str, budget_tokens: int=DEFAULT_BUDGET_TOKENS, mode: str='combined') -> dict[str, Any]` — Search and return token-budgeted compact stubs (preferred).
- `async def expand(self, wiki_name: str, page_id: str, rel: Optional[str]=None, budget_tokens: int=DEFAULT_BUDGET_TOKENS) -> dict[str, Any]` — Progressively disclose a page's graph neighbourhood as stubs.
- `async def find_related(self, wiki_name: str, page_id: str, depth: int=2) -> list[dict[str, Any]]` — Find pages related to a given page via graph traversal.
- `async def export_okf(self, wiki_name: str, output_dir: str) -> dict[str, Any]` — Export the wiki as an OKF v0.1 markdown bundle (interchange).
- `async def get_index(self, wiki_name: str) -> str` — Return the current index.md content for a wiki.
- `async def get_log(self, wiki_name: str, last_n: int=50) -> str` — Return the last ``last_n`` entries from log.md.
- `async def rebuild_index(self, wiki_name: str) -> dict[str, Any]` — Regenerate index.md from the current wiki state.
