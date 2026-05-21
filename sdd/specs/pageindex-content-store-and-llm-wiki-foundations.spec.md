---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: PageIndex Content Store + LLM-Wiki Foundations

**Feature ID**: FEAT-189
**Date**: 2026-05-21
**Author**: Jesús Lara
**Status**: approved
**Target version**: 0.x (PageIndex is pre-production; no compat guarantees)

---

## 1. Motivation & Business Requirements

### Problem Statement

PageIndex (`packages/ai-parrot/src/parrot/pageindex/`) currently persists a
**ToC tree only** — `compliance.json` carries titles, summaries, page ranges,
and node IDs, but the **per-node markdown content is discarded** at the end
of `build_page_index` (via `remove_structure_text`, `utils.py:442`). The
contract advertised by upstream PageIndex (Vectify AI), and intended for
our toolkit, is:

```
node_id  →  node_content   (raw markdown lives outside the index)
                          ↑
                  LRU-cached filesystem load
```

What we ship today violates that contract:

- `PageIndexToolkit.retrieve(query)` falls back to summaries because no
  raw content is reachable (`toolkit.py:225` chain ends on `summary`).
- `HybridPageIndexSearch._flatten_corpus` (`hybrid_search.py:97`) and
  `_apply_reranker` (`hybrid_search.py:234`) both read `node["text"]`,
  which is always empty in persisted trees. **BM25 + cross-encoder rerank
  are effectively indexing only `title + summary`** — strictly degraded
  signal versus what the implementations expect.

Beyond restoring the contract, the broader vision (Karpathy's "LLM Wiki"
[gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f))
is to make PageIndex usable for **two parallel access patterns**:

1. **Library-style navigation** — walk the index by title/structure when
   the consumer already knows what they're looking for.
2. **Wiki-style retrieval** — RAG-style search over the underlying content
   with BM25 + reranker filtering, scoped by **categories** and arbitrary
   **metadata** (entities, concepts, sources, topics, severity, …).

Both require that real content actually be retrievable, and the index
gain enough metadata for the second pattern to be meaningful. Node-to-node
cross-references (the third LLM-Wiki pillar) are explicitly out of scope
for this spec.

### Goals

- Persist per-node markdown content outside the tree JSON, addressable by
  `node_id`, with an LRU cache in front of disk reads.
- Use `pymupdf4llm.to_markdown(..., page_chunks=True)` (already in the
  dependency tree via `parrot_loaders.pdf.PDFLoader`) for PDF → markdown
  extraction; no new packages.
- Restore correct retrieval: `PageIndexToolkit.retrieve(query)` returns the
  actual markdown of selected nodes, not summaries.
- Improve BM25 + reranker quality non-destructively by feeding them real
  per-node markdown (truncated by configurable limits).
- Add `categories: list[str]` and `metadata: dict[str, Any]` fields to
  every node (default empty, omitted from JSON when empty), plus a
  `tag_node(...)` toolkit method to populate them.
- Allow `search(query, categories=[...], metadata_filter={...})` to filter
  candidates by the new fields before scoring.

### Non-Goals (explicitly out of scope)

- **Node-to-node links / cross-references** — separate follow-up spec.
- **LLM-driven category/metadata auto-population** — this spec only adds
  the fields and the manual/tool-assisted `tag_node` API.
- **Renaming the `nodes` field to `sub_nodes`** — keep current naming
  for backwards-compat with `tree_ops.py`, `find_node_by_id`,
  `md_builder.py`, and existing persisted trees inside the project.
- **On-disk migration of existing trees** — PageIndex is pre-production;
  re-ingest is canonical (`--reset` in the example).
- **Markitdown / unstructured.io fallback** — pymupdf4llm covers the clean
  digital PDF cases we exercise today; alternate extractors can be a
  follow-up.
- **Markdown-first ingest pipeline** that runs `md_to_tree` directly on
  extracted markdown instead of LLM-inferred TOC — bigger lift, separate
  spec.

---

## 2. Architectural Design

### Overview

Introduce a **two-artifact** PageIndex storage model that matches upstream:

```
<storage_dir>/
├── <tree_name>.json              ← INDEX: lean ToC tree
└── <tree_name>/                  ← CONTENT: per-node markdown
    ├── 0000.md
    ├── 0001.md
    └── …
```

Three layered components own this:

- **`NodeContentStore`** (new) — owns the on-disk content directory and
  an LRU cache keyed by `(tree_name, node_id)`. CRUD + bulk delete.
- **`extract_markdown_per_page`** (new) — thin helper around
  `pymupdf4llm.to_markdown(path, page_chunks=True)` that returns
  per-physical-page markdown in the same index space as
  `get_page_tokens(...)`, so `start_index`/`end_index` slicing works
  unchanged.
- **`PageIndexToolkit`** (existing, extended) — constructs a
  `NodeContentStore` in `__init__`, persists per-node markdown after
  `build_page_index`, supplies a `content_loader` callback to
  `HybridPageIndexSearch`, and exposes `tag_node`, plus the new
  filtering kwargs on `search`.

The tree builder (`build_page_index`) is taught to return per-node
markdown alongside the tree as a transient `_node_markdown` mapping;
the toolkit pops it and writes the files. The persisted tree never
carries content inline.

Node schema gains two optional fields:

```python
node = {
    "node_id": "0006",
    "title": "Financial Stability",
    "start_index": 21,
    "end_index": 22,
    "summary": "...",
    # NEW (optional, omitted when empty):
    "categories": ["controls", "trust-services-criteria"],
    "metadata": {"tsc": "CC7.2", "confidence": "high"},
    # children:
    "nodes": [...]
}
```

`HybridPageIndexSearch` gains an optional `content_loader: Callable[[str],
Optional[str]]` constructor parameter. When set, BM25 corpus rows include
the per-node markdown (truncated to `_BM25_TEXT_LIMIT`), and reranker
context strings include up to `_RERANK_TEXT_LIMIT` chars of the same.
When unset, behavior is identical to today (`title + summary` only) —
**strict non-regression for callers that don't pass a loader**.

### Component Diagram

```
                      ┌──────────────────────────┐
                      │   PageIndexToolkit       │
                      │   (toolkit.py)           │
                      └────────────┬─────────────┘
                                   │
       ┌───────────────────────────┼───────────────────────────┐
       │                           │                           │
       ▼                           ▼                           ▼
┌──────────────┐         ┌──────────────────┐         ┌─────────────────┐
│ JSONTreeStore│         │ NodeContentStore │         │ HybridPageIndex │
│ (store.py)   │         │ (content_store)  │         │ Search          │
│              │         │  + LRU cache     │         │ (hybrid_search) │
└──────┬───────┘         └────────┬─────────┘         └────────┬────────┘
       │                          │                            │
       │ JSON tree                │ <tree>/<id>.md             │ content_loader
       ▼                          ▼                            ▼
   .json file              <storage>/<tree>/             load(tree, id) ─┐
                                                                          │
                                          ┌───────────────────────────────┘
                                          │
                                          ▼
                              BM25 corpus / reranker docs
                                          ▲
                                          │ extract_markdown_per_page
                                          │
                                  ┌───────┴────────────────┐
                                  │ pymupdf4llm.to_markdown │
                                  │ (page_chunks=True)      │
                                  └─────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `JSONTreeStore` (`pageindex/store.py`) | sibling | Unchanged surface. Defensive strip of `_node_markdown` before `json.dump`. |
| `HybridPageIndexSearch` (`pageindex/hybrid_search.py`) | extended | New optional `content_loader` ctor param. `_flatten_corpus` and `_apply_reranker` consult it. Public `search()` signature unchanged. |
| `PageIndexRetriever` (`pageindex/retriever.py`) | unchanged | Already accepts `pdf_pages` for `start_index`/`end_index` slicing. Toolkit-level retrieval loads from `NodeContentStore` directly; retriever stays as-is. |
| `build_page_index` (`pageindex/builder.py:1549`) | extended | Returns a `_node_markdown` mapping in addition to `doc_name` / `structure`. Existing callers ignoring the new key are unaffected. |
| `pymupdf4llm` (already in `pyproject.toml:235` at `==0.0.27`) | reuse | Called via `to_markdown(path, page_chunks=True)`. No new pin. |
| `parrot_loaders.pdf.PDFLoader` | none (just reference) | Confirms pymupdf4llm is the project's blessed PDF→md path. We do not subclass PDFLoader; we call pymupdf4llm directly to keep page indexing aligned with `get_page_tokens`. |
| `AbstractReranker` (`rerankers/abstract.py:35`) | unchanged | Receives `SearchResult` items as today; their `content` field gains markdown body, nothing else changes. |
| `AbstractToolkit` (`tools/toolkit.py:191`) | base class | `PageIndexToolkit` continues to subclass it; new methods are additive `tool_prefix`-friendly. |

### Data Models

```python
# parrot/pageindex/content_store.py

class NodeContentStore:
    """Per-node markdown content store with bounded LRU cache.

    On-disk layout (one file per node, regardless of nesting):
        <storage_dir>/<tree_name>/<node_id>.md

    Cache key: (tree_name, node_id). Cache invalidation happens on
    save/delete/bulk-delete operations so subsequent loads see fresh data.
    """

    def __init__(
        self,
        storage_dir: str | Path,
        cache_size: int = 256,
    ) -> None: ...

    def save(self, tree_name: str, node_id: str, markdown: str) -> None: ...
    def load(self, tree_name: str, node_id: str) -> Optional[str]: ...
    def has(self, tree_name: str, node_id: str) -> bool: ...
    def delete_node(self, tree_name: str, node_id: str) -> bool: ...
    def delete_tree(self, tree_name: str) -> int: ...      # returns count removed
    def list_node_ids(self, tree_name: str) -> list[str]: ...
    def loader_for(self, tree_name: str) -> Callable[[str], Optional[str]]:
        """Return a closure that resolves node_id → markdown for `tree_name`.

        Suitable for handing to HybridPageIndexSearch as `content_loader`.
        """
```

```python
# parrot/pageindex/pdf_to_markdown.py

def extract_markdown_per_page(pdf_path: str | Path) -> list[tuple[int, str]]:
    """Return [(physical_page_1based, markdown_text), ...].

    Uses pymupdf4llm.to_markdown(path, page_chunks=True). Page indexing
    is aligned with `get_page_tokens` (1-based, every physical page
    represented). Empty pages are emitted as (page_num, "") so the
    index space stays dense.

    Raises:
        FileNotFoundError: if `pdf_path` does not exist.
        ValueError: if the page count does not match `pymupdf.open(...).page_count`.
    """
```

```python
# Node schema (in-tree JSON shape, additions only)

# Optional, omitted when empty:
node["categories"]: list[str]              # free-form tags
node["metadata"]:  dict[str, Any]          # arbitrary kv pairs
```

### New Public Interfaces

```python
# parrot/pageindex/toolkit.py — additions

class PageIndexToolkit(AbstractToolkit):

    def __init__(
        self,
        adapter: PageIndexLLMAdapter,
        storage_dir: str | Path,
        reranker: Optional[Any] = None,
        lightweight_model: Optional[str] = None,
        model: Optional[str] = None,
        default_bm25_k: int = 20,
        folder_concurrency: int = 4,
        content_cache_size: int = 256,        # NEW
        **kwargs: Any,
    ) -> None: ...

    async def tag_node(
        self,
        tree_name: str,
        node_id: str,
        categories: Optional[list[str]] = None,   # merged as a set
        metadata: Optional[dict[str, Any]] = None,  # shallow merge
    ) -> dict[str, Any]:
        """Add/merge tags on a node. Persists the tree and marks the
        BM25 index dirty for the next search."""

    async def search(
        self,
        tree_name: str,
        query: str,
        top_k: int = 10,
        use_bm25: bool = True,
        use_llm_walk: bool = True,
        rerank: bool = False,
        categories: Optional[list[str]] = None,   # NEW — AND-filter
        metadata_filter: Optional[dict[str, Any]] = None,  # NEW — equality match
    ) -> list[dict[str, Any]]: ...

    async def retrieve(
        self,
        tree_name: str,
        query: str,
        top_k: int = 5,
    ) -> str:
        """Hybrid search + per-node markdown aggregation.

        Loads each result's markdown from NodeContentStore; falls back
        to summary text only when the content sidecar is missing (e.g.
        a tree imported before this feature)."""
```

```python
# parrot/pageindex/hybrid_search.py — additions

class HybridPageIndexSearch:
    def __init__(
        self,
        tree: dict[str, Any],
        adapter: PageIndexLLMAdapter,
        reranker: Optional[Any] = None,
        model: Optional[str] = None,
        default_bm25_k: int = 20,
        content_loader: Optional[Callable[[str], Optional[str]]] = None,  # NEW
    ) -> None: ...
```

```python
# parrot/pageindex/builder.py — extended return shape

async def build_page_index(
    doc: str | BytesIO,
    adapter: PageIndexLLMAdapter,
    options: dict | config | None = None,
    light_adapter: Optional[PageIndexLLMAdapter] = None,
    llm_concurrency: int = DEFAULT_LLM_CONCURRENCY,
) -> dict:
    """
    Returns:
        {
            "doc_name": str,
            "structure": list[dict],
            "_node_markdown": dict[str, str],   # NEW — node_id -> markdown
            "doc_description": Optional[str],   # when requested
        }
    """
```

---

## 3. Module Breakdown

### Module 1: `NodeContentStore`
- **Path**: `packages/ai-parrot/src/parrot/pageindex/content_store.py` (new)
- **Responsibility**: On-disk per-node markdown CRUD + LRU cache. Owns
  the `<storage_dir>/<tree_name>/` directory layout. Provides a
  `loader_for(tree_name)` closure that `HybridPageIndexSearch` can use
  without leaking the store abstraction.
- **Depends on**: stdlib only (`pathlib`, `functools.lru_cache` via a
  small wrapper, since we want per-instance caches keyed by `(tree, id)`).

### Module 2: `extract_markdown_per_page`
- **Path**: `packages/ai-parrot/src/parrot/pageindex/pdf_to_markdown.py` (new)
- **Responsibility**: Stable PDF → list of `(physical_page_1based,
  markdown_text)`. Wraps `pymupdf4llm.to_markdown(path, page_chunks=True)`.
  Validates page count against `pymupdf.open(path).page_count` so a
  mismatch surfaces clearly instead of silently mis-slicing nodes.
- **Depends on**: `pymupdf4llm`, `pymupdf` (both already declared in
  `packages/ai-parrot/pyproject.toml:234-235`).

### Module 3: builder content-emission patch
- **Path**: `packages/ai-parrot/src/parrot/pageindex/builder.py` (existing)
- **Responsibility**: After `tree_parser` produces the structure and
  `write_node_id` assigns IDs, call `extract_markdown_per_page(doc)`,
  walk the structure, and build `_node_markdown[node_id] =
  "".join(markdown_pages[start_index-1:end_index])`. Return that mapping
  in the result dict alongside the existing tree.
- **Depends on**: Module 2.

### Module 4: `JSONTreeStore` defensive sanitizer
- **Path**: `packages/ai-parrot/src/parrot/pageindex/store.py` (existing)
- **Responsibility**: In `save()`, strip the `_node_markdown` key if
  present before serialization. One-line defense — nothing else carries
  reserved underscore-prefixed keys today.
- **Depends on**: none.

### Module 5: `PageIndexToolkit` content wiring + LLM-Wiki fields
- **Path**: `packages/ai-parrot/src/parrot/pageindex/toolkit.py` (existing)
- **Responsibility**:
  - Construct `NodeContentStore` in `__init__` with
    `content_cache_size`.
  - `import_pdf`: after `build_page_index`, persist each
    `_node_markdown` entry, then strip the key before splicing into
    `tree`.
  - `_search_for`: pass `self._content_store.loader_for(tree_name)`
    to `HybridPageIndexSearch`.
  - `retrieve`: load from `NodeContentStore` per node_id, with summary
    fallback when missing.
  - `delete_node`: also delete the markdown file and evict the cache.
  - `create_tree` and any reset path: clear the content directory via
    `NodeContentStore.delete_tree`.
  - New `tag_node` tool method (categories set-merge, metadata shallow
    dict-merge).
  - `search`: add `categories: Optional[list[str]]` and `metadata_filter:
    Optional[dict[str, Any]]` parameters; apply them as a post-filter
    on the result list. (BM25/LLM-walk ranking is unchanged; this is
    a candidate-set filter, not a scorer.)
- **Depends on**: Modules 1, 3, 6.

### Module 6: `HybridPageIndexSearch` content-aware ranking
- **Path**: `packages/ai-parrot/src/parrot/pageindex/hybrid_search.py` (existing)
- **Responsibility**:
  - Add `content_loader: Optional[Callable[[str], Optional[str]]]`
    ctor param.
  - In `_flatten_corpus` (line 87), include `body[:_BM25_TEXT_LIMIT]`
    when the loader is set; existing behavior otherwise.
  - In `_apply_reranker` (line 218), use loader-derived body up to
    `_RERANK_TEXT_LIMIT` (existing constant — `hybrid_search.py:39`).
  - Add new module-level constant `_BM25_TEXT_LIMIT = 4000` (bounded
    so corpus rebuild stays fast even with content-bearing trees).
- **Depends on**: none from this spec; consumed via Module 5.

### Module 7: Example refresh
- **Path**: `examples/pageindex/pageindex_compliance_agent.py` (existing)
- **Responsibility**: After `ensure_tree`, print a one-line summary
  showing that `retrieve()` now returns markdown rather than summaries.
  Add a small `demo_categories` block that calls `tag_node` on two
  nodes and then runs a `search(..., categories=["X"])` to demonstrate
  filtering. No new test infrastructure — the example doubles as a
  manual smoke test.
- **Depends on**: Modules 1, 5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_node_content_store_roundtrip` | 1 | save → load returns identical markdown. |
| `test_node_content_store_lru_eviction` | 1 | With `cache_size=2`, three loads cause the oldest to be evicted; subsequent load re-reads disk. |
| `test_node_content_store_delete_node_invalidates_cache` | 1 | Load → delete → load returns `None` (no stale cache hit). |
| `test_node_content_store_delete_tree_clears_directory` | 1 | `delete_tree(name)` removes the directory and returns the file count. |
| `test_node_content_store_isolated_trees` | 1 | Same `node_id` in two different trees does not collide. |
| `test_extract_markdown_per_page_indexing` | 2 | Fixture 3-page PDF: returned list has length 3, page numbers are `[1,2,3]`, markdown of each page is non-empty for non-blank pages. |
| `test_extract_markdown_per_page_count_mismatch_raises` | 2 | Synthetic mismatch (mocked pymupdf doc) → `ValueError`. |
| `test_builder_emits_node_markdown_keyed_by_node_id` | 3 | Build a tree from a fixture PDF; `result["_node_markdown"]` has one entry per node in `result["structure"]`, each non-empty for nodes with non-empty page ranges. |
| `test_store_strips_node_markdown_on_save` | 4 | `JSONTreeStore.save({"_node_markdown": {...}, ...})` writes a JSON file that does not contain `_node_markdown`. |
| `test_toolkit_import_pdf_persists_sidecar` | 5 | After `import_pdf`, `<storage_dir>/<tree>/<id>.md` exists for every node, and the tree JSON does not contain inline `text` or `_node_markdown`. |
| `test_toolkit_retrieve_returns_markdown_not_summary` | 5 | `retrieve(query)` output contains a substring from the persisted `<id>.md` file (not just the summary). |
| `test_toolkit_retrieve_falls_back_to_summary_when_no_content` | 5 | Manually delete a node's `.md`; `retrieve()` still returns concatenated text using the summary fallback. |
| `test_toolkit_tag_node_set_merge` | 5 | Two `tag_node(..., categories=["a"])` then `tag_node(..., categories=["b"])` produces `{"a", "b"}` (set semantics, sorted on persist). |
| `test_toolkit_tag_node_metadata_shallow_merge` | 5 | Two calls with overlapping keys: second wins; non-overlapping keys preserved. |
| `test_toolkit_delete_node_removes_sidecar` | 5 | `delete_node` removes the `.md` file and evicts the LRU cache. |
| `test_toolkit_search_filters_by_categories` | 5 | Tag two of three nodes with `["X"]`; `search(..., categories=["X"])` returns at most those two regardless of BM25/LLM scoring. |
| `test_toolkit_search_filters_by_metadata` | 5 | Equality match on a `metadata` key returns only matching nodes. |
| `test_hybrid_search_content_loader_enriches_bm25` | 6 | With a loader returning per-node body text containing a unique token, BM25 search for that token returns the right node; without a loader (control), BM25 cannot find it (token absent from title+summary). |
| `test_hybrid_search_content_loader_enriches_reranker` | 6 | Reranker `SearchResult.content` strings include the body up to `_RERANK_TEXT_LIMIT`. |
| `test_hybrid_search_no_loader_matches_baseline` | 6 | Without a `content_loader`, corpus rows are exactly `title + summary` (regression guard). |

### Integration Tests

| Test | Description |
|---|---|
| `test_pdf_ingest_to_retrieval_roundtrip` | Ingest a small fixture PDF, run `retrieve("known phrase from page 2")`, assert the returned text contains the phrase verbatim. |
| `test_ingest_then_tag_then_filtered_search` | Ingest fixture PDF, `tag_node(...)` two nodes, `search(..., categories=["controls"])`, assert only those nodes appear. |
| `test_reset_clears_sidecar_and_tree` | Ingest, then re-ingest with `--reset` semantics; assert content directory was wiped and rebuilt. |

### Test Data / Fixtures

```python
# tests/fixtures/pageindex/

# A short, fast-to-process PDF with a clear TOC and small recital section.
# 3-5 pages keeps unit tests fast (no real LLM calls — use a deterministic
# fake adapter).
SAMPLE_PDF = "tiny_toc.pdf"

@pytest.fixture
def fake_pageindex_adapter():
    """A PageIndexLLMAdapter double that returns canned structured responses
    for toc_detector, toc_extractor, generate_toc_init, generate_node_summary.
    Tests assert structure/wiring, not LLM quality."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `NodeContentStore` exists at
      `parrot/pageindex/content_store.py` with the surface defined in §2,
      and `pytest tests/unit/pageindex/test_content_store.py -v` passes.
- [ ] `extract_markdown_per_page` exists at
      `parrot/pageindex/pdf_to_markdown.py` and `pytest
      tests/unit/pageindex/test_pdf_to_markdown.py -v` passes.
- [ ] After `PageIndexToolkit.import_pdf(...)`, the file
      `<storage_dir>/<tree_name>/<node_id>.md` exists for every node in
      the persisted tree.
- [ ] The persisted `<tree_name>.json` does NOT contain `_node_markdown`
      and does NOT contain inline `text` fields on any node.
- [ ] `PageIndexToolkit.retrieve(query)` returns markdown loaded from
      `NodeContentStore`, verified by an integration test that asserts a
      verbatim substring of the source markdown appears in the output.
- [ ] When `NodeContentStore` is empty for a tree (sidecar missing),
      `retrieve` falls back to summaries without raising.
- [ ] `HybridPageIndexSearch` accepts an optional `content_loader`;
      with it set, BM25 corpus rows include up to `_BM25_TEXT_LIMIT`
      chars of per-node markdown, and reranker context includes up to
      `_RERANK_TEXT_LIMIT`. Without a loader, behavior is byte-identical
      to today (regression-tested).
- [ ] Node JSON may carry optional `categories: list[str]` and
      `metadata: dict[str, Any]`; both default empty and are omitted
      from JSON when empty.
- [ ] `PageIndexToolkit.tag_node(tree, id, categories=..., metadata=...)`
      merges categories as a set and metadata as a shallow dict,
      persists the tree, and marks the BM25 index dirty.
- [ ] `PageIndexToolkit.search(query, categories=[...])` returns only
      candidates whose node has ALL listed categories.
- [ ] `PageIndexToolkit.search(query, metadata_filter={"k": "v"})`
      returns only candidates whose node's `metadata[k] == v`.
- [ ] `PageIndexToolkit.delete_node(...)` removes the corresponding
      `.md` and evicts the LRU cache entry.
- [ ] `--reset` flow in `examples/pageindex/pageindex_compliance_agent.py`
      clears both the tree JSON and the content directory.
- [ ] No new external dependencies introduced (verified by `pip diff`
      of the `pyproject.toml`).
- [ ] All previously-passing tests under `tests/unit/pageindex/` and
      `tests/integration/pageindex/` still pass.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every entry here was verified by reading the file at the cited line
> on 2026-05-21. Implementation agents MUST NOT reference imports,
> attributes, or methods not listed here without re-verifying.

### Verified Imports

```python
# All confirmed importable as of 2026-05-21 on branch `dev`:
from parrot.pageindex.builder import build_page_index             # builder.py:1549
from parrot.pageindex.hybrid_search import HybridPageIndexSearch  # hybrid_search.py:42
from parrot.pageindex.llm_adapter import PageIndexLLMAdapter      # llm_adapter.py (existing)
from parrot.pageindex.retriever import PageIndexRetriever         # retriever.py (existing)
from parrot.pageindex.store import JSONTreeStore                  # store.py:23
from parrot.pageindex.utils import (
    add_node_text,            # utils.py:456
    find_node_by_id,          # utils.py:309
    get_nodes,                # utils.py:232
    get_page_tokens,          # utils.py:89
    remove_structure_text,    # utils.py:442
    structure_to_list,        # utils.py:250
    write_node_id,            # utils.py:218
)
from parrot.rerankers.abstract import AbstractReranker            # rerankers/abstract.py:35
from parrot.stores.models import Document, SearchResult           # stores/models.py:7,40
from parrot.tools.toolkit import AbstractToolkit                  # tools/toolkit.py:191

import pymupdf                # declared in pyproject.toml:234 (==1.27.1)
import pymupdf4llm            # declared in pyproject.toml:235 (==0.0.27)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/pageindex/store.py
class JSONTreeStore:                                              # line 23
    def list_names(self) -> list[str]: ...                        # line 46
    def exists(self, tree_name: str) -> bool: ...                 # line 56
    def load(self, tree_name: str) -> dict[str, Any]: ...         # line 59
    def save(self, tree_name: str, tree: dict[str, Any]) -> None: ...   # line 65
    def delete(self, tree_name: str) -> bool: ...                 # line 84
```

```python
# packages/ai-parrot/src/parrot/pageindex/hybrid_search.py
_RRF_K = 60                                                       # line 38
_RERANK_TEXT_LIMIT = 2000                                         # line 39

class HybridPageIndexSearch:                                      # line 42
    def __init__(
        self,
        tree: dict[str, Any],
        adapter: PageIndexLLMAdapter,
        reranker: Optional[Any] = None,
        model: Optional[str] = None,
        default_bm25_k: int = 20,
    ): ...                                                        # line 53

    def _flatten_corpus(self) -> tuple[list[str], list[str]]: ... # line 87
        # NB: reads `node.get("text") or ""` at line 97 — this spec replaces
        # that read with `content_loader(node_id)` when a loader is set.

    def _bm25_rank(self, query: str, top_k: int) -> list[str]: ...# line 116

    async def search(
        self,
        query: str,
        top_k: int = 10,
        use_bm25: bool = True,
        use_llm_walk: bool = True,
        rerank: bool = False,
    ) -> list[dict[str, Any]]: ...                                # line 161

    async def _apply_reranker(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]: ...                                # line 218
        # NB: reads `(node.get("text") or "")[:_RERANK_TEXT_LIMIT]` at line 234.
```

```python
# packages/ai-parrot/src/parrot/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                          # line 42
    name = "pageindex"
    tool_prefix = "pageindex"

    def __init__(
        self,
        adapter: PageIndexLLMAdapter,
        storage_dir: str | Path,
        reranker: Optional[Any] = None,
        lightweight_model: Optional[str] = None,
        model: Optional[str] = None,
        default_bm25_k: int = 20,
        folder_concurrency: int = 4,
        **kwargs: Any,
    ): ...                                                        # line 69

    async def create_tree(...): ...                               # line 157
    async def search(...): ...                                    # line 179
    async def retrieve(...): ...                                  # line 202
    async def import_pdf(...): ...                                # line 296
    async def delete_node(...): ...                               # line 414
```

```python
# packages/ai-parrot/src/parrot/pageindex/builder.py
DEFAULT_LLM_CONCURRENCY = 16                                      # line 61
_LLM_SEMAPHORE: ContextVar[Optional[asyncio.Semaphore]] = ...     # line 64

async def _limited_gather(coros, *, return_exceptions=False) -> list: ...  # line 69

async def build_page_index(
    doc: str | BytesIO,
    adapter: PageIndexLLMAdapter,
    options: dict | config | None = None,
    light_adapter: Optional[PageIndexLLMAdapter] = None,
    llm_concurrency: int = DEFAULT_LLM_CONCURRENCY,
) -> dict: ...                                                    # line 1549
    # Currently returns {doc_name, structure, doc_description?}.
    # This spec extends it to also return _node_markdown.

async def generate_summaries_for_structure(structure, adapter) -> Any: ...  # line 1514
```

```python
# packages/ai-parrot/src/parrot/rerankers/abstract.py
class AbstractReranker(ABC):                                      # line 35
    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[SearchResult],
        top_n: Optional[int] = None,
    ) -> list[RerankedDocument]: ...                              # line 50
```

```python
# packages/ai-parrot/src/parrot/stores/models.py
class SearchResult(BaseModel):                                    # line 7
    id: str                                                       # line 17
    content: str                                                  # line 18
    metadata: Dict[str, Any] = Field(default_factory=dict)        # line 19
    score: float                                                  # line 20
    ensemble_score: float = None                                  # line 28
    search_source: str = None                                     # line 29
    similarity_rank: Optional[int] = None                         # line 30
    mmr_rank: Optional[int] = None                                # line 31
```

```python
# packages/ai-parrot/src/parrot/pageindex/utils.py
def get_page_tokens(doc: str | BytesIO) -> list[tuple[str, int]]: ...  # line 89
    # Returns [(raw_text, token_count), ...] indexed by physical PDF page
    # (1-based once converted via start_index/end_index).

def write_node_id(data: Any, node_id: int = 0) -> int: ...        # line 218
def get_nodes(structure: Any) -> list[dict]: ...                  # line 232
def structure_to_list(structure: Any) -> list[dict]: ...          # line 250
def find_node_by_id(data: Any, node_id: str) -> Optional[dict]: ...  # line 309
def remove_structure_text(data: Any) -> Any: ...                  # line 442
def add_node_text(node: Any, pdf_pages: list[tuple[str, int]]) -> None: ...  # line 456
```

```python
# Third-party (verified at runtime, version pin from pyproject.toml:235):
import pymupdf4llm
pymupdf4llm.to_markdown(
    doc,                           # pymupdf.Document or path str
    pages=None,
    page_chunks=False,             # NB: set True for per-page output
    page_separators=False,
    margins=0,
    table_strategy='lines_strict',
    # ... (many more options; see help(pymupdf4llm.to_markdown))
) -> str | list[dict]              # str when page_chunks=False (default),
                                   # list[dict] (one per page) when True.
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `NodeContentStore` | `PageIndexToolkit.__init__` | Construction in `__init__` | `toolkit.py:69` |
| `NodeContentStore.loader_for(name)` | `HybridPageIndexSearch.__init__` | New `content_loader` kwarg | `hybrid_search.py:53` |
| `NodeContentStore.load(...)` | `PageIndexToolkit.retrieve` | Per-result load + concat | `toolkit.py:202` |
| `NodeContentStore.save(...)` | `PageIndexToolkit.import_pdf` | After `build_page_index`, before splice | `toolkit.py:296` |
| `NodeContentStore.delete_node(...)` | `PageIndexToolkit.delete_node` | After tree-level delete | `toolkit.py:414` |
| `extract_markdown_per_page(doc)` | `build_page_index` | Called after `tree_parser`, before return | `builder.py:1549` |
| `tag_node` | `PageIndexToolkit` (new method) | Tool surface | — |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.pageindex.content_store`~~ — does not exist (this spec creates it).
- ~~`parrot.pageindex.pdf_to_markdown`~~ — does not exist (this spec creates it).
- ~~`NodeContentStore` anywhere in the codebase~~ — new class.
- ~~`extract_markdown_per_page`~~ — not a real function yet.
- ~~`PageIndexToolkit.tag_node`~~ — not implemented; only the JSONStore /
  search / retrieve methods exist (`toolkit.py:42-420`).
- ~~`HybridPageIndexSearch(..., content_loader=...)`~~ — constructor does
  NOT accept that argument today; this spec adds it (`hybrid_search.py:53`).
- ~~`node["sub_nodes"]`~~ — our trees use `node["nodes"]` for children
  (consistent across `tree_ops.py`, `find_node_by_id`, `md_builder.py`).
  Do not rename. The user's referenced upstream JSON example uses
  `sub_nodes`; that's a naming difference we are intentionally keeping.
- ~~`build_page_index(..., extract_markdown=True, ...)`~~ — there is no
  such flag. The new `_node_markdown` return is unconditional; toolkit
  callers decide whether to persist it.
- ~~`pymupdf4llm.to_markdown(..., per_page=True)`~~ — wrong kwarg name;
  the real one is `page_chunks=True` (verified via
  `help(pymupdf4llm.to_markdown)` at version 0.0.27).
- ~~`SearchResult.body` / `SearchResult.text`~~ — neither exists; the
  field carrying content is `content: str` (`stores/models.py:18`).
- ~~`AbstractReranker.score(...)`~~ — not a real method; the contract is
  `async def rerank(query, documents, top_n=None)` returning
  `list[RerankedDocument]` (`rerankers/abstract.py:50`).
- ~~`PageIndexLLMAdapter.extract_markdown(...)`~~ — no such method;
  markdown extraction is non-LLM (pymupdf4llm) and lives in the new
  `pdf_to_markdown.py` module.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Async-first** for toolkit methods (`async def tag_node`, etc.) even
  though `NodeContentStore` itself is sync (file I/O is fast and bounded;
  wrapping a small LRU disk read in async would add noise without
  benefit).
- **Logger pattern**: `self.logger = logging.getLogger("parrot.pageindex")`
  inside each new class — matches the rest of the module
  (`builder.py:51`, `hybrid_search.py:28`).
- **Pydantic / dataclass-free** for `NodeContentStore` — it's a plain
  class with cache state; no need for a Pydantic model.
- **No new global state** beyond what already exists. Each
  `PageIndexToolkit` instance owns its own `NodeContentStore`.
- **Defensive sanitization**: `JSONTreeStore.save` strips
  `_node_markdown` if it leaks through, but the toolkit is the
  primary guard (pop before splice).
- **BM25 corpus rebuild is lazy**: `mark_dirty()` already exists
  (`hybrid_search.py:64`). After `tag_node` or any mutation, call
  `engine.mark_dirty()` so the next search picks up new content/filters.

### Known Risks / Gotchas

- **Page count alignment**: `pymupdf4llm.to_markdown(..., page_chunks=True)`
  emits one entry per processed page; if `pages=` is passed, the index
  space diverges from `get_page_tokens`. Always call without `pages=`.
  `extract_markdown_per_page` validates the returned length matches
  `pymupdf.open(path).page_count` and raises a clear `ValueError` on
  mismatch.
- **Per-node duplication on disk**: with per-node (not per-leaf) granularity,
  parent nodes carry the union of their children's text. For an 88-page
  PDF with 10 top-level sections × ~5 children each, the on-disk content
  directory can reach ~10× the source markdown size. This is accepted by
  the user (simpler retrieval > smaller disk).
- **LRU cache invalidation on `tag_node`**: tagging doesn't change
  markdown content, but it DOES change `metadata` / `categories` which
  the BM25 corpus reads from the tree (not the cache). `tag_node` calls
  `engine.mark_dirty()`; cache stays as-is.
- **Reranker absence is silent**: `_apply_reranker` already wraps
  `self._reranker.rerank(...)` in try/except (`hybrid_search.py:245`).
  Adding more content does not change that contract.
- **`pymupdf4llm` quirks on tables**: with `table_strategy='lines_strict'`
  (its default), heavy-table PDFs can produce messy markdown. For the
  SOC 2 / GDPR class of docs this is acceptable; if a user later reports
  garbled tables, a configurable `table_strategy` knob on
  `extract_markdown_per_page` is a follow-up.
- **Categories filter is AND-semantics**: `search(categories=["a", "b"])`
  returns nodes that have BOTH "a" AND "b". OR-semantics is a follow-up
  if needed (`categories_any` / `categories_all`).
- **Metadata filter is equality-only** for v1. Range queries / wildcards
  are not in scope; advertise the limit in the docstring.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pymupdf4llm` | `==0.0.27` (already pinned at `pyproject.toml:235`) | PDF → per-page markdown via `to_markdown(path, page_chunks=True)`. |
| `pymupdf` | `==1.27.1` (already pinned at `pyproject.toml:234`) | Used by `extract_markdown_per_page` for page-count validation. |

No new dependencies introduced.

---

## 8. Open Questions

> Questions that genuinely require a call before or during implementation.

- [x] **PDF → markdown extractor** — *Resolved during conversation*:
      use `pymupdf4llm.to_markdown(path, page_chunks=True)` directly
      (same library `parrot_loaders.PDFLoader` already uses; already
      pinned in `pyproject.toml`).
- [x] **Content granularity (per-node vs per-leaf)** — *Resolved during
      conversation*: per-node. Every node has its own `.md` file
      regardless of nesting depth. Simpler retrieval; disk cost accepted.
- [x] **Hierarchy field name (`nodes` vs `sub_nodes`)** — *Resolved
      during conversation*: keep `nodes`. Pervasive across `tree_ops.py`,
      `find_node_by_id`, `md_builder.py`, and existing persisted trees.
      Document the divergence from upstream's example JSON in the toolkit
      docstring.
- [x] **LRU cache scope** — *Resolved during conversation*: per-toolkit
      instance, keyed by `(tree_name, node_id)`, default `maxsize=256`,
      configurable via `content_cache_size` ctor param.
- [x] **Migration path for existing trees** — *Resolved during
      conversation*: none. PageIndex is pre-production. Re-ingest via
      `--reset` is canonical.
- [ ] **Categories taxonomy** — *Owner: TBD*: should `tag_node` validate
      categories against a configurable allow-list, or stay fully
      free-form? v1 will ship free-form; revisit if practice shows we
      want normalisation (singular/plural, case, etc.).: free-form
- [ ] **Metadata filter operator surface** — *Owner: TBD*: equality-only
      for v1. If we later need ranges (`{"effective_date": {">=": "..."}}`)
      or `in` semantics, this needs a small DSL. Out of scope for now.
- [ ] **Default `_BM25_TEXT_LIMIT`** — *Owner: implementation*: spec
      proposes `4000`. Implementer should validate that BM25 rebuild on
      a 100-node tree stays under ~500ms with this limit; tune down if
      needed.
- [ ] **Should `delete_tree` (the bulk variant on `NodeContentStore`)
      also evict cache entries for that tree from the LRU?** — *Owner:
      implementation*: yes — implementer should add eviction. Recorded
      here so it doesn't get forgotten.

---

## Worktree Strategy

- **Default isolation**: `per-spec` — all tasks in this spec run
  sequentially in one worktree at `.claude/worktrees/feat-189-pageindex-content-store-and-llm-wiki-foundations`.
- **Why not parallel**: every module after Module 1 touches files that
  Module 1's API shapes. The toolkit and hybrid-search edits depend on
  the `NodeContentStore` surface stabilising first. Parallel branches
  would generate trivial merge conflicts on `toolkit.py` for no speedup.
- **Cross-feature dependencies**: none. This spec is self-contained on
  top of `dev` after the recent perf-and-correctness commits
  (light-adapter routing, bounded LLM concurrency, batch-probe
  `find_toc_pages`, `verify_toc` sampling, empty-group guard).
- **Suggested task order**:
  1. Module 1 (`NodeContentStore`)  — pure new code, no dependencies.
  2. Module 2 (`extract_markdown_per_page`) — pure new code.
  3. Module 4 (`JSONTreeStore` strip) — trivial guard.
  4. Module 3 (builder content emission) — depends on Module 2.
  5. Module 6 (`HybridPageIndexSearch.content_loader`) — depends on
     Module 1's `loader_for` shape.
  6. Module 5 (toolkit wiring + `tag_node` + filter kwargs) — depends
     on Modules 1, 3, 6.
  7. Module 7 (example refresh + manual smoke).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-21 | Jesús Lara | Initial draft. |
