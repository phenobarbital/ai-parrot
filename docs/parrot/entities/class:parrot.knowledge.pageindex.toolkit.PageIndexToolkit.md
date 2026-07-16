---
type: Wiki Entity
title: PageIndexToolkit
id: class:parrot.knowledge.pageindex.toolkit.PageIndexToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit exposing search / retrieve / insert tools over PageIndex trees.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# PageIndexToolkit

Defined in [`parrot.knowledge.pageindex.toolkit`](../summaries/mod:parrot.knowledge.pageindex.toolkit.md).

```python
class PageIndexToolkit(AbstractToolkit)
```

Toolkit exposing search / retrieve / insert tools over PageIndex trees.

Args:
    adapter: Heavy LLM adapter. Used for Step-2 markdown generation,
        tree-walk search, and node summarisation via :func:`md_to_tree`.
    storage_dir: Filesystem directory where each tree is persisted as
        ``<tree_name>.json``.
    reranker: Optional :class:`AbstractReranker` instance applied to
        the fused candidate set when ``rerank=True`` is requested.
    lightweight_model: Model id used for the cheaper helper calls —
        Step-1 Chain-of-Thought analysis during text ingest, and during
        ``import_pdf``: TOC-page detection, per-node summaries, doc
        description, title verification, and TOC accuracy checks. A
        second :class:`PageIndexLLMAdapter` is built with this model,
        sharing the same underlying client; ``adapter`` is never
        mutated.
    model: Optional override for the model passed to
        :class:`PageIndexRetriever`. Defaults to ``adapter.model``.
    default_bm25_k: Number of BM25 candidates fetched per query.
    folder_concurrency: Maximum concurrent file ingests during
        ``import_folder``.
    embedding_model: Sentence-Transformers model identifier for
        dense node embeddings (FEAT-237).  Defaults to the
        ``EMBEDDING_DEFAULT_MODEL`` config value when embedding is
        enabled.
    embedding_dimension: Dimensionality of the embedding vectors.
        Must match the selected model's output (or MRL truncation dim).
    embedding_backend: Optional runtime backend for
        ``SentenceTransformerModel`` — ``"onnx"``, ``"openvino"``, or
        ``None`` (default torch).
    use_vec_rank: Enable Phase A dense cosine-similarity ranking signal.
    use_embedding_walk: Enable Phase B embedding-guided beam walk.

## Methods

- `def set_okf_toolkit(self, tree_name: str, okf_toolkit: Any) -> None` — Register an :class:`~parrot.knowledge.pageindex.okf.tools.OKFToolkit`
- `def get_tools(self, permission_context: Any=None, resolver: Any=None) -> list` — Return all tools, including OKF read tools for enriched trees.
- `async def list_trees(self) -> list[str]` — List all PageIndex tree names available in the storage directory.
- `async def create_tree(self, tree_name: str, doc_name: Optional[str]=None) -> dict[str, Any]` — Create a new empty PageIndex tree.
- `async def delete_tree(self, tree_name: str) -> dict[str, Any]` — Delete a tree JSON and every sidecar markdown file for it.
- `async def get_tree(self, tree_name: str) -> dict[str, Any]` — Return the full tree dict for ``tree_name``.
- `async def search(self, tree_name: str, query: str, top_k: int=10, use_bm25: bool=True, use_llm_walk: bool=True, rerank: bool=False, categories: Optional[list[str]]=None, metadata_filter: Optional[dict[str, Any]]=None) -> list[dict[str, Any]]` — Hybrid search over a tree.
- `async def retrieve(self, tree_name: str, query: str, top_k: int=5) -> str` — Hybrid search + per-node markdown aggregation.
- `async def search_documents_scoped(self, tree_names: list[str], query: str, include_tree_context: bool=False, max_trees: int=_MAX_TREES_HARD_CAP) -> dict[str, Any]` — Run an LLM tree-walk against a SUBSET of trees in one call.
- `async def tag_node(self, tree_name: str, node_id: str, categories: Optional[list[str]]=None, metadata: Optional[dict[str, Any]]=None) -> dict[str, Any]` — Add or merge ``categories`` / ``metadata`` tags on a node.
- `async def insert_markdown(self, tree_name: str, markdown: str, parent_node_id: Optional[str]=None, doc_name: Optional[str]=None) -> dict[str, Any]` — Parse ``markdown`` into a PageIndex subtree and splice it in.
- `async def insert_content(self, tree_name: str, content: str, parent_node_id: Optional[str]=None, hint: Optional[str]=None) -> dict[str, Any]` — Two-Step CoT ingest of raw content into the tree.
- `async def import_file(self, tree_name: str, file_path: str, parent_node_id: Optional[str]=None) -> dict[str, Any]` — Read a text file and ingest it via :meth:`insert_content`.
- `async def import_pdf(self, tree_name: str, pdf_path: str, parent_node_id: Optional[str]=None, with_summaries: bool=True, with_doc_description: bool=False) -> dict[str, Any]` — Build a PageIndex subtree from a PDF and splice it into ``tree_name``.
- `async def import_folder(self, tree_name: str, folder_path: str, recursive: bool=True, glob_pattern: str='*', parent_node_id: Optional[str]=None) -> dict[str, Any]` — Recursively import all matching files from ``folder_path``.
- `async def delete_node(self, tree_name: str, node_id: str) -> dict[str, Any]` — Delete a node and all its descendants from the tree.
- `async def add_node(self, tree_name: str, title: str, body: str='', parent_node_id: Optional[str]=None, summary: Optional[str]=None, categories: Optional[list[str]]=None, metadata: Optional[dict[str, Any]]=None) -> dict[str, Any]` — Atomically create a single node and register its content.
- `async def update_node_content(self, tree_name: str, node_id: str, body: str) -> dict[str, Any]` — Overwrite a node's sidecar markdown without touching the tree.
- `async def update_node(self, tree_name: str, node_id: str, title: Optional[str]=None, summary: Optional[str]=None) -> dict[str, Any]` — Rename and/or re-summarize an existing node.
