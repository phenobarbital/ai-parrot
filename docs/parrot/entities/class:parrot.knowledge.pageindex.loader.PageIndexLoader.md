---
type: Wiki Entity
title: PageIndexLoader
id: class:parrot.knowledge.pageindex.loader.PageIndexLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build a PageIndex tree from a list of files.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# PageIndexLoader

Defined in [`parrot.knowledge.pageindex.loader`](../summaries/mod:parrot.knowledge.pageindex.loader.md).

```python
class PageIndexLoader(AbstractLoader)
```

Build a PageIndex tree from a list of files.

Args:
    source: Path, directory, or list of paths/directories to ingest.
        Resolved the same way :class:`AbstractLoader` resolves sources,
        filtered by :pyattr:`extensions`.
    storage_dir: **Required.** Directory where the tree JSON and per-node
        markdown sidecars are persisted (via :class:`PageIndexToolkit`).
    tree_name: Name of the single aggregate tree all files are imported
        into. Must match ``[A-Za-z0-9_-]{1,128}``.
    client: An ``AbstractClient`` used to drive the PageIndex LLM calls.
        Ignored when ``adapter`` is supplied. When both ``client`` and
        ``adapter`` are ``None`` a default client is created via
        :meth:`AbstractLoader.get_default_llm`.
    model: Heavy model id for the adapter (tree-walk, summaries, Step-2
        markdown generation).
    lightweight_model: Optional cheaper model id for the toolkit's helper
        calls (TOC detection, Step-1 analysis, summaries).
    adapter: A pre-built :class:`PageIndexLLMAdapter`. Takes precedence over
        ``client`` / ``model``.
    with_summaries: Generate per-node LLM summaries when importing PDFs.
    with_doc_description: Generate a one-sentence document description when
        importing PDFs.
    reset_tree: When ``True`` (default) an existing tree with the same name
        is deleted before ingestion so each ``load()`` is reproducible.
        Set ``False`` to append to an existing tree.
    **kwargs: Forwarded to :class:`AbstractLoader`.

Raises:
    ValueError: If ``storage_dir`` is not provided.

## Methods

- `async def load(self, source: Optional[Any]=None, split_documents: bool=False, **kwargs: Any) -> List[Document]` — Import every file into one tree and return per-node Documents.
- `async def build_tree(self, source: Optional[Any]=None) -> dict` — Build the tree and return the native tree dict.
- `def tree(self) -> Optional[dict]` — The most recently built tree dict, or ``None`` before ``load()``.
