# TASK-5321: Snapshot-bound search and read helpers on `PageIndexToolkit`

**Feature**: FEAT-843 — PageIndex Agentic Retrieval and Citations
**Spec**: `sdd/specs/pageindex-agentic-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Snapshot binding (M4)" and AC-16. The agentic loop must read from ONE pinned tree
snapshot: a re-import during the request must not change candidates, outline, documents,
generation or revision, and an old cursor must keep working while its revision file exists.
The public read tools always call `self._load_tree(tree_name)` (live tree). This task factors
their bodies into private `*_on(tree_name, tree, ...)` helpers that take the tree explicitly,
and adds `_agentic_search` / `_agentic_read_tools` that bind those helpers to a snapshot.
TASK-5325 calls them from `agentic_retrieve`.

---

## Scope

- Extract the bodies of `list_documents`, `outline`, `read_pages`, `read_segments` into
  `_list_documents_on`, `_outline_on`, `_read_pages_on`, `_read_segments_on`, each taking
  `(tree_name, tree, ...)`. The public methods keep their exact signature and docstring and
  become `tree = self._load_tree(tree_name); return await self._x_on(tree_name, tree, ...)`.
- Add `_agentic_search(tree_name, tree) -> HybridPageIndexSearch` — request-local engine with
  the same constructor settings as `_search_for` (`toolkit.py:425`), never stored in `self._search`.
- Add `_agentic_read_tools(tree_name, tree) -> list[ToolkitTool]` — four tools named
  `pageindex_list_documents`, `pageindex_outline`, `pageindex_read_pages`, `pageindex_read_segments`
  whose closures keep the public parameter names, reject any `tree_name` other than the bound one
  (`ValueError`), and call the `*_on` helpers with the bound snapshot.
- Tests in `test_agentic_snapshot.py`.

**NOT in scope**: `agentic_retrieve`, kwargs, ledger/clipping, `llm_dependent_tools` (TASK-5325);
any change to `_read`, `_revision_for`, `_documents_of`, cursor format.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `*_on` helpers, `_agentic_search`, `_agentic_read_tools` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py` | CREATE | Snapshot-binding tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in toolkit.py (verified at HEAD 7d73c97ea9):
from parrot.tools.toolkit import AbstractToolkit          # toolkit.py:35
from .hybrid_search import HybridPageIndexSearch          # toolkit.py:40
from .generation import ..., generation_of                # toolkit.py:39
from .utils import find_node_by_id, get_pdf_name, structure_to_list   # toolkit.py:75
# parse_page_spec is imported in the `from .segments import (...)` block (toolkit.py:49-67, line 62)
# ADD (extend line 35):
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool   # ToolkitTool: tools/toolkit.py:37
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
def _load_tree(self, tree_name) -> dict                                     # :405
def _search_for(self, tree_name) -> HybridPageIndexSearch                   # :425-445 (ctor kwargs to copy)
def _documents_of(self, tree) -> dict[str, dict]                            # :747
def _revision_for(self, tree_name, tree, doc_id, revision=None) -> DocumentRevision   # :756
def _read(self, tree_name, tree, revision, seqs, *, max_chars, cursor) -> ReadResult  # :772 (RevisionMismatchError on foreign cursor)
async def list_documents(self, tree_name) -> list[dict]                     # :842
async def outline(self, tree_name, node_id=None, max_depth=3, max_chars=6000) -> dict   # :865
async def read_pages(self, tree_name, doc_id, pages, max_chars=12000, cursor=None) -> dict   # :924
async def read_segments(self, tree_name, doc_id=None, start=None, end=None, node_id=None, max_chars=12000, cursor=None) -> dict  # :943
async def index_segments(self, tree_name, node_id=None) -> dict             # :983
self._content_store.loader_for(tree_name, tree)                             # content_store.py:470

# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch: __init__(tree=, adapter=, reranker=, model=, default_bm25_k=, content_loader=,
    embedding_store=, embed_fn=, use_vec_rank=, use_embedding_walk=, tree_name=, generation_id=)   # :74 (as called at toolkit.py:430-443)
    async def search(self, query, top_k=10, use_bm25=True, use_llm_walk=True, use_vec=False, use_embedding_walk=None, rerank=False) -> list[dict]  # :310

# packages/ai-parrot/src/parrot/tools/toolkit.py
class ToolkitTool(AbstractTool):
    def __init__(self, name, bound_method, description=None, args_schema=None, **kwargs)   # :42
    # _execute (:142): toolkit hooks run only when bound_method.__self__ is an AbstractToolkit —
    # a plain closure gets no hooks; kwargs are filtered to the closure's signature.
```

### Does NOT Exist
- ~~`PageIndexToolkit._agentic_search`, `_agentic_read_tools`, `_*_on` helpers~~ — you create them.
- ~~a `tree=` parameter on the public read tools~~ — do NOT add one; public signatures stay unchanged.
- ~~`HybridPageIndexSearch.from_tree` / `.clone()`~~ — construct it directly.
- ~~a toolkit-level "pin" / snapshot cache~~ — never mutate `self._trees`, `self._search` or `self._tree_sigs` to simulate pinning.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._search_for",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.list_documents",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.outline",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.read_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.read_segments",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._read",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool"
  ]
}
```

---

## Implementation Notes

- Pure move-refactor of the four bodies: replace each `tree = self._load_tree(tree_name)` with
  the `tree` parameter; nothing else changes — because existing `test_read_tools.py` /
  `test_segment_integration.py` must stay green unchanged.
- Helper names start with `_` so `get_tools()` does not expose them.
- Snapshot cursors: `_revision_for(tree_name, tree, doc_id)` resolves the revision from the
  snapshot tree, so an old cursor keeps matching the old revision; a cursor naming the NEW
  revision raises `RevisionMismatchError` from `_read` (AC-16) — no extra code needed.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the import at `toolkit.py:35` with `ToolkitTool`.
2. For each public read tool, move its body into a `_x_on` helper placed directly ABOVE it, then make the public method delegate.
3. Add `_agentic_search` and `_agentic_read_tools` directly before `index_segments`.
4. Write tests; run them plus `test_read_tools.py` (regression).

### `toolkit.py` (MODIFY) — import
```python
# REPLACE `from parrot.tools.toolkit import AbstractToolkit` (verified: toolkit.py:35)
# occurrences: 1 (verified: grep -cF 'from parrot.tools.toolkit import AbstractToolkit' toolkit.py)
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool
```

### `toolkit.py` (MODIFY) — delegation pattern (repeat for all four)
```python
# AT `    async def read_pages(` (verified: toolkit.py:924) — occurrences: 1
    async def _read_pages_on(
        self, tree_name: str, tree: dict[str, Any], doc_id: str, pages: str,
        max_chars: int = 12000, cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        """``read_pages`` over an explicit tree (live or a request snapshot)."""
        # FILL IN: the current body of read_pages from `revision = await asyncio.to_thread(...)` on, unchanged

    async def read_pages(
        self, tree_name: str, doc_id: str, pages: str, max_chars: int = 12000, cursor: Optional[str] = None
    ) -> dict[str, Any]:
        """<keep the existing docstring verbatim>"""
        tree = self._load_tree(tree_name)
        return await self._read_pages_on(tree_name, tree, doc_id, pages, max_chars=max_chars, cursor=cursor)
```
Anchors (each occurrences: 1, verified with `grep -cF`): `    async def list_documents(self, tree_name: str) -> list[dict[str, Any]]:` (:842),
`    async def outline(` (:865), `    async def read_pages(` (:924), `    async def read_segments(` (:943).
**Why**: one code path for live and snapshot reads keeps the selection rules identical (spec: "reuse the existing selection rules").

### `toolkit.py` (MODIFY) — snapshot helpers
```python
# BEFORE `    async def index_segments(self, tree_name: str, node_id: Optional[str] = None) -> dict[str, Any]:`
# (verified: toolkit.py:983) — occurrences: 1
    def _agentic_search(self, tree_name: str, tree: dict[str, Any]) -> HybridPageIndexSearch:
        """Build a request-local engine with snapshot-bound content loading and existing search settings."""
        generation_id = (tree.get("generation") or {}).get("id", 0)
        return HybridPageIndexSearch(
            tree=tree,
            adapter=self._adapter,
            reranker=self._reranker,
            model=self._model,
            default_bm25_k=self._default_bm25_k,
            content_loader=self._content_store.loader_for(tree_name, tree),
            embedding_store=self._embedding_store,
            embed_fn=self._embed_fn,
            use_vec_rank=self._use_vec_rank,
            use_embedding_walk=self._use_embedding_walk,
            tree_name=tree_name,
            generation_id=generation_id,
        )

    def _agentic_read_tools(self, tree_name: str, tree: dict[str, Any]) -> list[ToolkitTool]:
        """Build four request-local tools bound to this tree snapshot and its revisions.

        Preserve public names/schema, reject another tree_name, never dispatch to live read methods."""
        bound = tree_name

        def _check(name: str) -> None:
            if name != bound:
                raise ValueError(f"this retrieval is bound to tree {bound!r}, not {name!r}")

        async def list_documents(tree_name: str) -> list[dict[str, Any]]:
            _check(tree_name)
            return await self._list_documents_on(bound, tree)

        # FILL IN: outline / read_pages / read_segments closures with the SAME parameter names and
        #          defaults as the public methods, each calling _check then its *_on helper — AC-16

        tools: list[ToolkitTool] = []
        for public, fn in (
            (self.list_documents, list_documents),
            # FILL IN: (self.outline, outline), (self.read_pages, read_pages), (self.read_segments, read_segments)
        ):
            fn.__doc__ = public.__doc__
            tools.append(ToolkitTool(name=f"{self.tool_prefix}_{public.__name__}", bound_method=fn,
                                     description=public.__doc__))
        return tools
```
**Why**: closures (not bound methods) make `ToolkitTool._execute` skip toolkit hooks and the
live tree; copying `__doc__` keeps the model-facing description identical. Do NOT cache these
tools — they hold one request's snapshot.

### `test_agentic_snapshot.py` (CREATE)
```python
"""FEAT-843 — snapshot-bound search/read helpers (AC-16)."""
import copy

import pytest

from parrot.knowledge.pageindex.segments import RevisionMismatchError
# FILL IN: reuse the fixtures pattern of tests/knowledge/pageindex/test_read_tools.py:20-75
#          (_adapter, _stub_tiktoken autouse, toolkit, _fake_build, paged_toolkit) — copy them, do not import test modules

# FILL IN: test_public_read_tools_unchanged_signatures (inspect.signature equality vs before)
# FILL IN: test_snapshot_tools_named_like_public (names == {pageindex_list_documents, pageindex_outline, pageindex_read_pages, pageindex_read_segments})
# FILL IN: test_snapshot_rejects_other_tree_name -> ValueError
# FILL IN: test_reimport_does_not_change_snapshot: snap = copy.deepcopy(toolkit._load_tree("t")); re-import with
#          different pages; snapshot list_documents/outline/read_pages keep old revision + generation;
#          old cursor continues; a cursor naming the new revision -> RevisionMismatchError — AC-16
# FILL IN: test_agentic_search_not_cached: engine not in toolkit._search after _agentic_search
```

### FILL IN checklist
- [ ] four `_x_on` helpers + delegating public methods
- [ ] remaining three closures and tool tuples
- [ ] all tests

---

## Acceptance Criteria

- [ ] AC-16 (helpers part): snapshot tools/search keep old generation, revision, documents and outline after a re-import; another `tree_name` is rejected; a new-revision cursor is rejected; shared caches untouched.
- [ ] Existing read-tool tests pass unchanged.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_read_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py -q`

---

## Test Specification

Blueprint stubs; spec §4 integration row "re-import after stage-1 pinning…" (helper half).

---

## Agent Instructions

1. Re-verify anchors with `grep -cF` (TASK-5325 also edits `toolkit.py` after you).
2. `ruff check --fix` the touched files; run validation with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit: `feat(pageindex-agentic-retrieval): TASK-5321 — snapshot-bound readers`.

---

## Completion Note

*(Agent fills this in when done)*
