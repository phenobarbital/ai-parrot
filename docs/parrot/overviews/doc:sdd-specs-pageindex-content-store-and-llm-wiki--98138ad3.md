---
type: Wiki Overview
title: 'Feature Specification: PageIndex Content Store + LLM-Wiki Foundations'
id: doc:sdd-specs-pageindex-content-store-and-llm-wiki-foundations-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: PageIndex (`packages/ai-parrot/src/parrot/pageindex/`) currently persists
  a
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.rerankers.abstract
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_loaders
  rel: mentions
- concept: mod:parrot_loaders.pdf
  rel: mentions
---

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

…(truncated)…
