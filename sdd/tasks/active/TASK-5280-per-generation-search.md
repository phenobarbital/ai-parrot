# TASK-5280: Per-generation search engine and generation-keyed embedding matrices

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 6**. After a publish the toolkit builds a new
`HybridPageIndexSearch` for the new generation while readers keep the old one, so the id-keyed
indexes (BM25 corpus, embedding matrix and node order) must belong to one generation. It also
fixes `mark_dirty`/`_vec_rank` keying embeddings by `doc_name` instead of the tree name
(`hybrid_search.py:129`, `:217`).

---

## Scope

- `HybridPageIndexSearch.__init__`: add keyword-only `tree_name: Optional[str] = None` and
  `generation_id: int = 0`; expose read-only properties `tree_name` and `generation_id`.
- `mark_dirty` and `_vec_rank` use the tree name when given, falling back to `doc_name` (legacy
  callers such as `PageIndexOrigin` users that pass no tree name keep today's behaviour).
- `NodeEmbeddingStore`: `_matrix_path`/`_order_path` take `generation_id: int = 0` (0 keeps the
  legacy file names, `n > 0` uses `<tree>.g<n>.matrix.npy` / `<tree>.g<n>.node_order.json`);
  `build_tree_matrix` and `load_tree_matrix` take keyword-only `generation_id`; `build_tree_matrix`
  writes both files atomically; `invalidate_tree` removes the legacy pair and every `g<n>` pair.
- Add `NodeEmbeddingStore.prune_tree_matrices(tree_name, keep: set[int]) -> int` that removes the
  matrix/order pairs of every generation not in `keep` — *added at /sdd-task time: without it the
  matrices of superseded generations accumulate forever (one per publish)*.
- Tests in `test_hybrid_search.py` and a new `test_embedding_store.py`.

**NOT in scope**: building engines per generation in the toolkit (TASK-5283).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | MODIFY | tree_name/generation_id, keyed invalidation |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py` | MODIFY | Generation-keyed matrices, atomic writes, prune |
| `packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py` | MODIFY | Engine tests |
| `packages/ai-parrot/tests/knowledge/pageindex/test_embedding_store.py` | CREATE | Embedding store tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex import HybridPageIndexSearch                 # verified: __init__.py:24-43 (__all__)
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore    # verified: embedding_store.py:42 (not in __all__)
```

### Existing Signatures to Use
```python
# knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch:                                       # line 52
    def __init__(self, tree, adapter, reranker=None, model=None, default_bm25_k=20, content_loader=None,
                 embedding_store=None, embed_fn=None, use_vec_rank=False,
                 use_embedding_walk=False)                         # lines 73-85 (`use_embedding_walk: bool = False,` :84)
    self._tree = tree                                              # line 86
    def mark_dirty(self) -> None                                   # line 119 — tree_name = self._tree.get("doc_name") :129
    def replace_tree(self, tree) -> None                           # line 133
    def _vec_rank(self, query: str, top_k: int) -> list[str]       # line 199 — doc_name :217, load_tree_matrix :223,
                                                                   #   build_tree_matrix(tree_name, nodes, self._embed_fn) :229-231

# knowledge/pageindex/embedding_store.py
class NodeEmbeddingStore:                                          # line 42
    self._storage_dir: Path
    def _matrix_path(self, tree_name: str) -> Path                 # line 121 → <dir>/<tree>/embeddings/<tree>.matrix.npy
    def _order_path(self, tree_name: str) -> Path                  # line 125 → .../<tree>.node_order.json
    def build_tree_matrix(self, tree_name, nodes, embed_fn) -> tuple[np.ndarray, list[str]]  # line 204 (np.save :295, write_text :296-298)
    def load_tree_matrix(self, tree_name) -> Optional[tuple[np.ndarray, list[str]]]          # line 306
    def invalidate_tree(self, tree_name: str) -> None              # line 330
```

### Does NOT Exist
- ~~`HybridPageIndexSearch.tree_name` / `.generation_id`~~ — added here
- ~~`NodeEmbeddingStore.prune_tree_matrices`~~ — added here
- ~~a direct `NodeEmbeddingStore` test file~~ — none today (`test_toolkit.py:1264` only fakes the directory)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_embedding_store.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py#HybridPageIndexSearch",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py#NodeEmbeddingStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `np.save` appends `.npy` to a path without that suffix; write the matrix to an open file
  object from `tempfile.mkstemp(dir=..., suffix=".npy")`, then `os.replace` — *because* a bare
  temp name would land at `<tmp>.npy` and the replace would miss it.
- Generation 0 must produce exactly today's file names — *because* `test_toolkit.py:1264` and
  existing trees rely on them.
- `test_mark_dirty_triggers_rebuild` (`test_hybrid_search.py:119`) must keep passing.

---

## Implementation Blueprint

### Steps (in order)
1. Embedding store paths, atomic build, load, invalidate, prune — *why*: the engine calls them.
2. Engine kwargs/properties and the `_index_name` helper; route `mark_dirty`/`_vec_rank` through it.
3. Tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    def _matrix_path(self, tree_name: str) -> Path:' embedding_store.py)
# REPLACE _matrix_path (:121-123) and _order_path (:125-127) with:
    def _matrix_path(self, tree_name: str, generation_id: int = 0) -> Path:
        """Per-tree matrix path; generation 0 keeps the legacy name."""
        suffix = "" if generation_id == 0 else f".g{generation_id}"
        return self._storage_dir / tree_name / "embeddings" / f"{tree_name}{suffix}.matrix.npy"

    def _order_path(self, tree_name: str, generation_id: int = 0) -> Path:
        """Per-tree node-order path; generation 0 keeps the legacy name."""
        suffix = "" if generation_id == 0 else f".g{generation_id}"
        return self._storage_dir / tree_name / "embeddings" / f"{tree_name}{suffix}.node_order.json"

    def prune_tree_matrices(self, tree_name: str, keep: set[int]) -> int:
        """Remove matrix/order pairs of every generation (``g<n>``) not in ``keep``; return files removed."""
        # FILL IN: glob f"{tree_name}.g*.matrix.npy" / ".node_order.json", parse <n>, unlink when n not in keep — AC-4
        raise NotImplementedError
```
`build_tree_matrix` (:204): add `*, generation_id: int = 0` to the signature, use it in both path
calls, and replace `np.save(...)` / `order_path.write_text(...)` (:295-298) with temp-file +
`os.replace` writes (`# FILL IN` — bounded by Key Constraints).
`load_tree_matrix` (:306): add `*, generation_id: int = 0` and pass it to both path helpers.
`invalidate_tree` (:330): after removing the legacy pair, also remove every `g<n>` pair
(`prune_tree_matrices(tree_name, keep=set())`).

### `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        use_embedding_walk: bool = False,' hybrid_search.py)
# AFTER — insert below that line (verified: hybrid_search.py:84)
        *,
        tree_name: Optional[str] = None,
        generation_id: int = 0,
```
In the body (after `self._use_embedding_walk = use_embedding_walk`) store `self._tree_name =
tree_name` and `self._generation_id = generation_id`, then add:
```python
    @property
    def tree_name(self) -> Optional[str]:
        """Tree name the indexes are keyed by (``None`` for legacy callers)."""
        return self._tree_name

    @property
    def generation_id(self) -> int:
        """Generation this engine was built for (0 for legacy trees)."""
        return self._generation_id

    def _index_name(self) -> str:
        """``tree_name`` when given, else the legacy ``doc_name`` key."""
        return self._tree_name or self._tree.get("doc_name") or ""
```
`mark_dirty` (:119): replace `tree_name = self._tree.get("doc_name") or ""` with
`tree_name = self._index_name()`. `_vec_rank` (:199): same at :217, and pass
`generation_id=self._generation_id` to `load_tree_matrix` and `build_tree_matrix`.

### FILL IN checklist
- [ ] `prune_tree_matrices`; AC-4
- [ ] atomic matrix/order writes; Key Constraints

---

## Acceptance Criteria

- [ ] AC-1: generation 0 paths equal today's names; generation 3 paths contain `.g3.`.
- [ ] AC-2: an engine built with `tree_name="t"` invalidates and builds matrices under `t` even when `doc_name` differs.
- [ ] AC-3: `invalidate_tree` removes the legacy pair and every `g<n>` pair.
- [ ] AC-4: `prune_tree_matrices("t", {5})` keeps `g5` and removes `g3`, `g4`.
- [ ] AC-5: `build_tree_matrix` leaves no `.npy` temp file behind; `load_tree_matrix(..., generation_id=n)` reads what it wrote.
- [ ] Existing `test_hybrid_search.py` tests pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_embedding_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_embedding_store.py
import numpy as np

from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore


def _embed(texts):
    return np.ones((len(texts), 4), dtype=np.float32)


def test_matrix_path_has_generation(tmp_path):
    store = NodeEmbeddingStore(storage_dir=tmp_path, model_id="m", dimension=4)
    assert store._matrix_path("t").name == "t.matrix.npy"
    assert store._matrix_path("t", 3).name == "t.g3.matrix.npy"


def test_build_and_load_per_generation(tmp_path):
    store = NodeEmbeddingStore(storage_dir=tmp_path, model_id="m", dimension=4)
    nodes = [{"node_id": "0001", "title": "a", "summary": "b"}]
    store.build_tree_matrix("t", nodes, _embed, generation_id=2)
    assert store.load_tree_matrix("t", generation_id=2) is not None
    assert store.load_tree_matrix("t") is None


def test_invalidate_and_prune(tmp_path):
    # FILL IN: build g3, g4, g5; prune keep={5}; then invalidate_tree removes everything
    ...

# add to test_hybrid_search.py
def test_mark_dirty_uses_tree_name_not_doc_name(tmp_path):
    # FILL IN: engine(tree={"doc_name": "Other", ...}, tree_name="t", embedding_store=Mock()) → invalidate_tree("t")
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-generation-publication --feature-id FEAT-831`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-generation-publication.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
7. **Verify** — run the Validation Commands and `ruff check` on the files you touched.
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`).
9. **Close the task** with `parrot sdd task close TASK-5280 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
