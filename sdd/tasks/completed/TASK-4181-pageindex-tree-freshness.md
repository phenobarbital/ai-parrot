# TASK-4181: PageIndex tree freshness check in `_load_tree`

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

In `navigator-agent-server` every Odoo agent builds its own `Bookstore` →
`PageIndexToolkit`, whose `_trees` cache is filled once and never reloaded.
When FEAT-647's upload service re-ingests a book (status `"updated"`), the
writer's own toolkit evicts its cache (via `rename_tree`), but every other
agent keeps serving the stale tree until restart. Spec §2 "Freshness for the
serving agents" / §3 Module 6: `_load_tree` gains an on-disk signature check.

---

## Scope

- Add `self._tree_sigs: dict[str, tuple[int, int]] = {}` next to `self._trees` in `PageIndexToolkit.__init__`.
- Add `_tree_signature(tree_name) -> tuple[int, int] | None` = `(st_mtime_ns, st_size)` of `self._store._path_for(tree_name)`; `None` when missing.
- Add `_remember_tree_signature(tree_name)` that stores the current signature.
- Change `_load_tree`: return the cached tree when (a) the tree is inside an open batch (`self._batch_depth.get(tree_name, 0) > 0`) or (b) the on-disk signature equals the remembered one; otherwise evict (`_trees`, `_search`, content-store cache, `_okf_toolkits`) and reload from disk, remembering the new signature.
- Call `_remember_tree_signature` right after the toolkit's **own** writes (`self._store.save(tree_name, tree)` in `_persist` and in `create_tree`), so the toolkit never reloads a file it just wrote itself.
- Pop `_tree_sigs` wherever `_trees` is popped (`delete_tree`, `rename_tree`'s `finally`).
- Tests.

**Decision (recorded here, binding)**: the toolkit's own saves refresh the
remembered signature (verified: `_persist` writes the in-memory tree to disk
at toolkit.py:214, `create_tree` at :395). Without this, every write would
make the next read reload the same content from disk and throw away the
search engine (`_search`) needlessly.

**NOT in scope**: the direct `self._trees.get(tree_name) or self._store.load(tree_name)`
read in the metadata-filter helper (toolkit.py:570) — leave it; embedding-store
invalidation; any change to `JSONTreeStore` or `NodeContentStore`; Bookstore code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | signature cache + freshness check |
| `packages/ai-parrot/tests/knowledge/pageindex/test_tree_freshness.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit   # verified: pageindex/toolkit.py:54 (used by tests/knowledge/pageindex/test_toolkit.py:12)
from parrot.knowledge.pageindex.store import JSONTreeStore        # verified: pageindex/store.py:23 (already imported in toolkit.py:39)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                                   # :54
    def __init__(self, adapter: PageIndexLLMAdapter, storage_dir: str | Path, reranker=None,
                 lightweight_model=None, model=None, default_bm25_k=20, folder_concurrency=4,
                 content_cache_size=256, embedding_model=None, ..., **kwargs)   # :92
    self._store = JSONTreeStore(storage_dir)                                # :114
    self._content_store = NodeContentStore(storage_dir, cache_size=content_cache_size)  # :115
    self._trees: dict[str, dict[str, Any]] = {}                             # :162
    self._search: dict[str, HybridPageIndexSearch] = {}                     # :163
    self._batch_depth: dict[str, int] = {}                                  # :164
    self._batch_dirty: dict[str, bool] = {}                                 # :165
    self._okf_toolkits: dict[str, Any] = {}                                 # :169
    def _load_tree(self, tree_name: str) -> dict[str, Any]:                 # :179-186
        # if tree_name in self._trees: return self._trees[tree_name]
        # if not self._store.exists(tree_name): raise KeyError(f"Tree {tree_name!r} does not exist")
        # tree = self._store.load(tree_name); self._trees[tree_name] = tree; return tree
    def _search_for(self, tree_name: str) -> HybridPageIndexSearch:         # :188 (calls _load_tree, caches engine in _search)
    def _persist(self, tree_name: str) -> None:                             # :207 — self._store.save(tree_name, tree) at :214
    async def _batch(self, tree_name: str):                                 # :362 (asynccontextmanager; _batch_depth counter)
    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]:  # :377 — self._store.save at :395
    async def delete_tree(self, tree_name: str) -> dict[str, Any]:          # :398 — pops _trees (:402) / _search (:403)
    async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]:  # :410
        # finally (:493-497): for tree_name in affected_names: self._trees.pop(...); self._search.pop(...);
        #   self._content_store._cache_evict_tree(tree_name); self._okf_toolkits.pop(tree_name, None)

# packages/ai-parrot/src/parrot/knowledge/pageindex/store.py
class JSONTreeStore:                                                        # :23
    def _path_for(self, tree_name: str) -> Path:                            # :40 (validates name; <dir>/<name>.json)
    def exists(self, tree_name: str) -> bool
    def load(self, tree_name: str) -> dict[str, Any]
    def save(self, tree_name: str, tree: dict[str, Any]) -> None            # atomic: mkstemp + replace

# packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py
def _cache_evict_tree(self, tree_name: str) -> None:                        # :105 (NodeContentStore)
```
```python
# Test helper pattern: tests/knowledge/pageindex/test_toolkit.py:15 `_adapter()` builds a MagicMock adapter
# with .model, .client (.ask AsyncMock, .default_model), .ask, .ask_structured; construct
# PageIndexToolkit(_adapter(), storage_dir=tmp_path).
```

### Does NOT Exist
- ~~`PageIndexToolkit.invalidate_tree` / `reload_tree` / `evict_tree`~~ — no public eviction API exists; do not add one (out of scope)
- ~~`JSONTreeStore.path_for` / `JSONTreeStore.signature`~~ — only the private `_path_for`
- ~~`self._tree_sigs`~~ — this task creates it
- ~~`invalidate_tree` on the toolkit~~ — the one in `pageindex/embedding_store.py:330` belongs to the embedding store

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_tree_freshness.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._load_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._persist",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.create_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.delete_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.rename_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._search_for",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/store.py#JSONTreeStore._path_for",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore._cache_evict_tree"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `_load_tree` is sync and hot: one `os.stat` per call is acceptable; nothing heavier.
- Never reload while a batch is open — the in-memory tree holds unsaved mutations (`_persist` defers saving while `_batch_depth > 0`).
- `OSError` from `stat` (file vanished between `exists` and `stat`) → treat as missing (`None`).

### References in Codebase
- `toolkit.py:493-497` — the eviction set to mirror (tree, search, content cache, OKF toolkit)

---

## Implementation Blueprint

### Steps (in order)
1. Add `self._tree_sigs` next to `self._trees` — *why*: remembers the signature each cached tree was loaded/written with.
2. Add `_tree_signature` and `_remember_tree_signature` helpers above `_load_tree` — *why*: one place computes the signature.
3. Rewrite `_load_tree` — *why*: reload trees rewritten by another process/instance (AC-14 of the spec).
4. Call `_remember_tree_signature` after both `self._store.save(tree_name, tree)` sites — *why*: the toolkit must not reload its own writes.
5. Pop `_tree_sigs` in `delete_tree` and in `rename_tree`'s `finally` — *why*: keep the signature map consistent with `_trees`.
6. Write tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY — init)
```python
# occurrences: 1 (verified: grep -c '        self._trees: dict\[str, dict\[str, Any\]\] = {}' toolkit.py → 1)
# AFTER — insert below `        self._trees: dict[str, dict[str, Any]] = {}` (verified: toolkit.py:162)
        # FEAT-647: on-disk signature (st_mtime_ns, st_size) of each cached tree,
        # so trees rewritten by another toolkit/process are reloaded on read.
        self._tree_sigs: dict[str, tuple[int, int]] = {}
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY — `_load_tree`)
```python
# occurrences: 1 (verified: grep -c '    def _load_tree(self, tree_name: str) -> dict\[str, Any\]:' toolkit.py → 1)
# REPLACE `_load_tree` (verified: toolkit.py:179-186) with the three methods below
    def _tree_signature(self, tree_name: str) -> tuple[int, int] | None:
        """Return ``(st_mtime_ns, st_size)`` of the tree JSON, or ``None`` when it is missing."""
        try:
            st = self._store._path_for(tree_name).stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _remember_tree_signature(self, tree_name: str) -> None:
        """Record the current on-disk signature of ``tree_name`` (after a load or own write)."""
        sig = self._tree_signature(tree_name)
        if sig is None:
            self._tree_sigs.pop(tree_name, None)
        else:
            self._tree_sigs[tree_name] = sig

    def _load_tree(self, tree_name: str) -> dict[str, Any]:
        cached = self._trees.get(tree_name)
        if cached is not None:
            if self._batch_depth.get(tree_name, 0) > 0:
                return cached
            # FILL IN: when self._tree_signature(tree_name) == self._tree_sigs.get(tree_name), return cached;
            #   otherwise evict exactly like rename_tree's finally (toolkit.py:493-497): pop _trees, _search,
            #   _okf_toolkits, call self._content_store._cache_evict_tree(tree_name), pop _tree_sigs, and log
            #   logger.debug("PageIndex tree %r changed on disk; reloading", tree_name)
            #   — bounded by spec §3 Module 6 (signature = mtime_ns + size; skip inside a batch)
        if not self._store.exists(tree_name):
            raise KeyError(f"Tree {tree_name!r} does not exist")
        tree = self._store.load(tree_name)
        self._trees[tree_name] = tree
        self._remember_tree_signature(tree_name)
        return tree
```
**Why this shape**: the missing-tree `KeyError` behavior is unchanged; a tree
whose file was deleted on disk falls through to the existing `KeyError`.
`logger` is the module-level logger (verified: toolkit.py:47,
`logging.getLogger("parrot.knowledge.pageindex.toolkit")`).

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY — own writes)
```python
# occurrences: 2 (verified: grep -c '        self._store.save(tree_name, tree)' toolkit.py → 2) — ambiguous, use context:
# (a) in `_persist` (toolkit.py:211-215):
#         if self._batch_depth.get(tree_name, 0) > 0:
#             self._batch_dirty[tree_name] = True
#             return
#         self._store.save(tree_name, tree)
#   AFTER that save insert:
        self._remember_tree_signature(tree_name)
# (b) in `create_tree` (toolkit.py:393-395):
#         tree = {"doc_name": doc_name or tree_name, "structure": []}
#         self._trees[tree_name] = tree
#         self._store.save(tree_name, tree)
#   AFTER that save insert:
        self._remember_tree_signature(tree_name)
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY — evictions)
```python
# delete_tree — occurrences: 2 (verified: grep -c '        self._search.pop(tree_name, None)' toolkit.py → 2, the substring
#   also matches the 16-space line in rename_tree) — disambiguate with context (toolkit.py:401-403):
#         sidecars_removed = self._content_store.delete_tree(tree_name)
#         self._trees.pop(tree_name, None)
#         self._search.pop(tree_name, None)
# AFTER that 8-space `self._search.pop(tree_name, None)` insert:
        self._tree_sigs.pop(tree_name, None)
# rename_tree finally — occurrences: 1 (verified: grep -c '                self._search.pop(tree_name, None)' toolkit.py → 1; toolkit.py:495)
# AFTER `                self._search.pop(tree_name, None)` insert:
                self._tree_sigs.pop(tree_name, None)
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_tree_freshness.py` (CREATE)
```python
"""FEAT-647 / TASK-4181 — PageIndexToolkit reloads trees rewritten on disk."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from parrot.knowledge.pageindex.toolkit import PageIndexToolkit


def _adapter() -> MagicMock:
    a = MagicMock()
    a.model = "heavy"
    a.client = MagicMock()
    a.client.ask = AsyncMock()
    a.client.default_model = "test-model"
    return a


def _rewrite(path: Path, tree: dict) -> None:
    """Rewrite a tree file the way another process would, bumping mtime."""
    path.write_text(json.dumps(tree), encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


# FILL IN: tests of the Test Specification — bounded by AC-1..AC-5
```

### FILL IN checklist
- [ ] `toolkit.py::_load_tree` — signature compare + eviction set; bounded by spec §3 Module 6
- [ ] `test_tree_freshness.py` — the five tests below

---

## Acceptance Criteria

- [ ] AC-1: a tree rewritten on disk by another writer is returned with its new content on the next `_load_tree`, and its `_search` engine is evicted.
- [ ] AC-2: two `PageIndexToolkit` instances on the same `storage_dir`: a `create_tree`/save through instance A is seen by instance B after B had cached the old version.
- [ ] AC-3: inside `async with toolkit._batch(name)` the cached (unsaved) tree is returned even if the file changed.
- [ ] AC-4: the toolkit's own `_persist` / `create_tree` do not cause a reload (cached object identity preserved on the next `_load_tree`).
- [ ] AC-5: a missing tree still raises `KeyError`; `delete_tree` and `rename_tree` clear `_tree_sigs`.
- [ ] Existing `tests/knowledge/pageindex/test_toolkit.py`, `test_tree_ops.py`, `test_store.py` pass unchanged.
- [ ] No linting errors.

- [ ] Lint clean: `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py packages/ai-parrot/tests/knowledge/pageindex/test_tree_freshness.py`
---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_tree_freshness.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_tree_ops.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_store.py -q`

---

## Test Specification

```python
async def test_reload_after_external_rewrite(tmp_path):
    tk = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    await tk.create_tree("book", doc_name="v1")
    assert tk._load_tree("book")["doc_name"] == "v1"
    tk._search["book"] = object()
    _rewrite(tmp_path / "book.json", {"doc_name": "v2", "structure": []})
    assert tk._load_tree("book")["doc_name"] == "v2"
    assert "book" not in tk._search


async def test_second_instance_sees_update(tmp_path):
    a = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    b = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    await a.create_tree("book", doc_name="v1")
    assert b._load_tree("book")["doc_name"] == "v1"
    _rewrite(tmp_path / "book.json", {"doc_name": "v2", "structure": []})
    assert b._load_tree("book")["doc_name"] == "v2"


async def test_batch_keeps_cached_tree(tmp_path):
    tk = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    await tk.create_tree("book", doc_name="v1")
    tk._load_tree("book")
    async with tk._batch("book"):
        _rewrite(tmp_path / "book.json", {"doc_name": "external", "structure": []})
        assert tk._load_tree("book")["doc_name"] == "v1"


async def test_own_write_does_not_reload(tmp_path):
    tk = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    await tk.create_tree("book", doc_name="v1")
    first = tk._load_tree("book")
    first["doc_name"] = "v1b"
    tk._persist("book")
    assert tk._load_tree("book") is first


async def test_missing_and_delete(tmp_path):
    tk = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    # FILL IN: KeyError for an unknown tree; after create + delete_tree, "book" not in tk._tree_sigs
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug teams-telegram-uploader-bookstore --feature-id FEAT-647`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/teams-telegram-uploader-bookstore.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/teams-telegram-uploader-bookstore.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4181 teams-telegram-uploader-bookstore verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

## Completion Note

Implemented by engine seat; merged. Tests run via PYTHONPATH with main-checkout .so files (merge-tier validation failed on a worktree import env issue, not code). Pre-existing unrelated failures: pageindex test_adapter x2, test_okf_ontology.
