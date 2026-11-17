# TASK-5283: Toolkit transaction core: _write, _mutate, per-generation engines, create/delete tree

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5280, TASK-5281, TASK-5282
**Assigned-to**: unassigned

---

## Context

First of four tasks on spec §3 **Module 5** (`toolkit.py`). It adds the transaction machinery
every mutator will use (spec §2 "Copy-on-write transaction", step 7 "in-process swap"), the
first-write migration of legacy trees, per-generation search engines, and ports `create_tree` /
`delete_tree`. The existing mutators keep using `_persist`/`_batch` until TASK-5284/5285 port them,
so this task must leave the old path working.

---

## Scope

- `__init__`: add `generation_grace_s: int = 3600` and `lock_timeout_s: float = 30.0` before `**kwargs`;
  keep `self._storage_dir = Path(storage_dir)`.
- Module-level `ContextVar` `_OPEN_TXNS` mapping `(id(toolkit), tree_name)` → `WriteTransaction`, so a
  nested `_write` on the same tree **in the same task context** joins the open transaction
  (children created by `asyncio.gather` inherit it; unrelated requests do not).
- `_write(tree_name)` (async context manager): join or open; on clean exit of the outermost call
  `await txn.publish()` then `_after_publish(tree_name, txn)`; on exception publish nothing.
- `_after_publish(tree_name, txn)`: `_trees[name] = txn.tree`, `_tree_sigs[name] = txn.published_signature`,
  drop `_search[name]`, evict the content cache, drop `_okf_toolkits[name]`, and
  `prune_tree_matrices(name, keep={new_id, base_id})` when an embedding store exists.
- `_mutate(tree_name, apply, *, attempts=3)`: run `apply(txn)` inside `_write`; on
  `StaleGenerationError` evict the cached tree and retry (only when not joined to an outer transaction).
- Legacy migration: when the base tree has no `generation`, `_write` stages every existing body
  before yielding — for each node without `body_ref`: `content_store.load(name, node_id)` (raw
  `<node_id>.md`) or else the flat sidecar with frontmatter stripped — via `txn.set_body`.
- `_project_okf_sidecars` becomes **strict** (no try/except) and returns `bool`; `_persist` wraps
  its call in try/except+`logger.exception` until TASK-5285 removes `_persist`.
- `_search_for`: rebuild when the cached engine's `generation_id` differs from the tree's; pass
  `tree_name`, `generation_id` and `content_loader=self._content_store.loader_for(tree_name, tree)`.
- `create_tree`: publish generation 1 through a `WriteTransaction` (base signature `None`).
- `delete_tree`: under `tree_lock`: delete JSON, content tree, embedding matrices, the lock file; drop every cache entry.
- New tools `get_generation(tree_name)` and `vacuum_tree(tree_name, max_age_s=None)`.
- `retrieve` and `search_documents_scoped` read bodies with `load_node(tree_name, node)`.

**NOT in scope**: porting the mutators (TASK-5284, TASK-5285), `rename_tree` (TASK-5286).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | Transaction core, create/delete tree, new tools |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` | MODIFY | Core tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.generation import (               # TASK-5278 / TASK-5282
    StaleGenerationError, WriteTransaction, generation_of,
)
from parrot.knowledge.pageindex.locks import lock_path, tree_lock  # TASK-5276
from parrot.knowledge.pageindex.okf.projection import _strip_frontmatter  # verified: okf/projection.py:65
from parrot.knowledge.okf.utils import flatten_concept_id_for_filename     # verified: okf/utils.py:18
```

### Existing Signatures to Use
```python
# knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                              # line 54
    def __init__(..., use_vec_rank=False, use_embedding_walk=False, **kwargs)   # lines 92-107
    self._store = JSONTreeStore(storage_dir)                          # line 114
    self._content_store = NodeContentStore(storage_dir, ...)          # line 115
    self._trees / _tree_sigs / _search / _batch_depth / _batch_dirty / _okf_toolkits   # lines 164-172
    def _tree_signature(self, tree_name) -> tuple[int, int] | None    # line 182
    def _load_tree(self, tree_name) -> dict[str, Any]                 # line 198
    def _search_for(self, tree_name) -> HybridPageIndexSearch         # line 218 (engine built :222-233)
    def _persist(self, tree_name) -> None                             # line 237 (projection call :252)
    def _project_okf_sidecars(self, tree_name, tree) -> None          # line 254 (enriched rule :279, swallow :289-291)
    async def create_tree(self, tree_name, doc_name=None) -> dict     # line 408 (direct _store.save :426)
    async def delete_tree(self, tree_name) -> dict                    # line 430
    async def retrieve(self, tree_name, query, top_k=5) -> str        # line 621 (body read :651)
    async def search_documents_scoped(...)                            # line 658 (body read :742)

# knowledge/pageindex/hybrid_search.py (after TASK-5280)
    HybridPageIndexSearch(..., *, tree_name=None, generation_id=0); .generation_id property
# knowledge/pageindex/embedding_store.py (after TASK-5280)
    prune_tree_matrices(tree_name, keep: set[int]) -> int; invalidate_tree(tree_name)
# knowledge/pageindex/content_store.py (after TASK-5279)
    load_node(tree_name, node); loader_for(tree_name, tree=None); sweep_unreferenced(tree_name, tree, *, max_age_s)
# knowledge/pageindex/generation.py (after TASK-5282)
    WriteTransaction(*, tree_name, base_tree, base_signature, store, content_store, storage_dir,
                     lock_timeout_s, grace_s, projector); .tree; .publish(); .published_signature; .base_generation
# tools/toolkit.py — every public coroutine becomes a tool named pageindex_<name>   # lines 575-618
```

### Does NOT Exist
- ~~`_write`, `_mutate`, `_after_publish`, `get_generation`, `vacuum_tree`~~ — added here
- ~~`_get_or_build_okf_toolkit`~~ — only mentioned in a comment (`toolkit.py:171`)
- ~~a toolkit-level `asyncio.Lock`~~ — exclusion comes from `tree_lock` + the stale check

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
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._load_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._search_for",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._persist",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._project_okf_sidecars",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.create_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.delete_tree"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `_write` publishes only on normal exit: put `await self._publish_and_swap(...)` *after* the
  `try/finally` that resets the ContextVar — *because* code after `yield` inside `finally` would also run on errors.
- The base signature is `self._tree_sigs.get(tree_name)` recorded by `_load_tree` — the signature
  of the version the copy came from, not a fresh stat.
- `_mutate` retries only when it opened the transaction itself; a joined call re-raises at once.
- Tool docstrings are the LLM-facing description: say what `get_generation` returns and that
  `vacuum_tree` only removes files unreferenced by the live generation and older than the grace period.
- `test_tree_freshness.py` (signature reload) must keep passing.

---

## Implementation Blueprint

### Steps (in order)
1. Constructor kwargs + ContextVar + `_write`/`_after_publish`/`_mutate` — *why*: everything else uses them.
2. Strict `_project_okf_sidecars` and the guarded call in `_persist` — *why*: the old path must not start raising.
3. `_search_for`, `create_tree`, `delete_tree`, the two tools, the two body reads.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY) — transaction core
```python
# occurrences: 1 (verified: grep -cF '    def _tree_signature(self, tree_name: str) -> tuple[int, int] | None:' toolkit.py)
# BEFORE — insert above that line (verified: toolkit.py:182)
    @asynccontextmanager
    async def _write(self, tree_name: str) -> AsyncIterator[WriteTransaction]:
        """Open (or join) the copy-on-write transaction for ``tree_name``; publish on clean outermost exit."""
        open_txns = _OPEN_TXNS.get() or {}
        key = (id(self), tree_name)
        if key in open_txns:
            yield open_txns[key]
            return
        base = self._load_tree(tree_name)
        txn = WriteTransaction(
            tree_name=tree_name, base_tree=base, base_signature=self._tree_sigs.get(tree_name),
            store=self._store, content_store=self._content_store, storage_dir=self._storage_dir,
            lock_timeout_s=self._lock_timeout_s, grace_s=self._generation_grace_s,
            projector=self._project_okf_sidecars_for,
        )
        if generation_of(base) is None:
            self._migrate_legacy_bodies(tree_name, txn)
        token = _OPEN_TXNS.set({**open_txns, key: txn})
        try:
            yield txn
        finally:
            _OPEN_TXNS.reset(token)
        await txn.publish()
        self._after_publish(tree_name, txn)

    def _after_publish(self, tree_name: str, txn: WriteTransaction) -> None:
        """Swap in-process state to the generation ``txn`` just published (spec §2 step 7)."""
        # FILL IN — bounded by Scope (_after_publish)

    async def _mutate(self, tree_name: str, apply: Callable[[WriteTransaction], Awaitable[T]], *, attempts: int = 3) -> T:
        """Run ``apply`` in a transaction; retry on StaleGenerationError when not joined."""
        # FILL IN — bounded by Key Constraints (_mutate)
        raise NotImplementedError

    def _migrate_legacy_bodies(self, tree_name: str, txn: WriteTransaction) -> None:
        """Stage every legacy body of a pre-FEAT-831 tree so its first publish assigns ``body_ref``."""
        # FILL IN — bounded by Scope (legacy migration); use _strip_frontmatter on the flat sidecar
```
Add at module level (after the constants at toolkit.py:49-51): `T = TypeVar("T")` and
`_OPEN_TXNS: ContextVar[Optional[dict[tuple[int, str], WriteTransaction]]] = ContextVar("pageindex_open_txns", default=None)`;
add the needed `typing`/`contextvars` imports.

`_project_okf_sidecars` (toolkit.py:254): delete the `try/except` around `project_sidecars`
(:289-291) and return `True` when it projected, `False` when the tree is not OKF-enriched.
Add `def _project_okf_sidecars_for(self, tree: dict[str, Any], tree_name: str) -> bool:` returning
`self._project_okf_sidecars(tree_name, tree)` (argument order of the projector contract).
In `_persist` (toolkit.py:252) wrap the call in `try/except Exception: logger.exception(...)`.

### `toolkit.py` (MODIFY) — engines, tree lifecycle, tools
```python
# occurrences: 1 (verified: grep -cF '    def _search_for(self, tree_name: str) -> HybridPageIndexSearch:' toolkit.py)
# FILL IN in _search_for (toolkit.py:218-235): reuse the cached engine only when
# engine.generation_id == (tree.get("generation") or {}).get("id", 0); otherwise build with
# tree_name=tree_name, generation_id=<that id>, content_loader=self._content_store.loader_for(tree_name, tree)
```
`create_tree` (toolkit.py:408): replace the direct `self._store.save` (:426) with a
`WriteTransaction(..., base_tree={"doc_name": ..., "structure": []}, base_signature=None, ...)`,
`await txn.publish()`, `self._after_publish(tree_name, txn)`.
`delete_tree` (toolkit.py:430): run the deletions inside `async with tree_lock(self._storage_dir,
tree_name, timeout=self._lock_timeout_s)`, add `invalidate_tree`, `lock_path(...).unlink(missing_ok=True)`,
`self._okf_toolkits.pop(...)`, `self._content_store._cache_evict_tree(...)`.
`retrieve` (:651) and `search_documents_scoped` (:742): `self._content_store.load_node(tree_name, node)`.

```python
# new tools — insert after get_tree (toolkit.py:550-552)
    async def get_generation(self, tree_name: str) -> dict[str, Any]:
        """Return the live generation of a PageIndex tree: ``{tree_name, id, published_at, parent}``
        (``id`` is ``None`` for a tree not written since the generation upgrade)."""
        # FILL IN

    async def vacuum_tree(self, tree_name: str, max_age_s: Optional[int] = None) -> dict[str, Any]:
        """Remove body files no longer referenced by the live generation of a tree and older than the
        grace period (default: the toolkit's ``generation_grace_s``). Returns ``{tree_name, removed}``."""
        # FILL IN: under tree_lock; sweep_unreferenced on the freshly loaded tree; prune matrices
```

### FILL IN checklist
- [ ] `_after_publish`; AC-2
- [ ] `_mutate` retry; AC-3
- [ ] `_migrate_legacy_bodies`; AC-4
- [ ] `_search_for` per generation; AC-5
- [ ] `create_tree` / `delete_tree`; AC-1, AC-6
- [ ] `get_generation` / `vacuum_tree`; AC-7

---

## Acceptance Criteria

- [ ] AC-1: `create_tree` writes `generation.id == 1`.
- [ ] AC-2: after a `_mutate` that sets a body, the cached tree is the published candidate, the old dict obtained before is unchanged, and its body still resolves through `loader_for(name, old_dict)`.
- [ ] AC-3: nested `_write` calls on one tree publish once; a `StaleGenerationError` from an external rewrite is retried by `_mutate` and succeeds.
- [ ] AC-4: the first `_mutate` on a legacy tree (no `generation`, `<node_id>.md` bodies) gives every node with a legacy body a `body_ref` whose blob equals the legacy text (frontmatter stripped).
- [ ] AC-5: `_search_for` returns a new engine after a publish; the previous instance still holds the previous tree.
- [ ] AC-6: `delete_tree` removes the JSON, `bodies/`, `embeddings/` and the lock file.
- [ ] AC-7: `get_generation` and `vacuum_tree` are exposed as `pageindex_get_generation` / `pageindex_vacuum_tree`.
- [ ] Existing `test_toolkit.py` and `test_tree_freshness.py` tests pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_tree_freshness.py -q`

---

## Test Specification

```python
# add to packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py (reuse its `toolkit` fixture)
@pytest.mark.asyncio
async def test_create_tree_publishes_generation_one(toolkit):
    await toolkit.create_tree("g")
    assert (await toolkit.get_generation("g"))["id"] == 1

@pytest.mark.asyncio
async def test_write_nested_joins(toolkit):
    await toolkit.create_tree("g")
    async with toolkit._write("g"):
        async with toolkit._write("g"):
            pass
    assert (await toolkit.get_generation("g"))["id"] == 2

@pytest.mark.asyncio
async def test_reader_keeps_generation(toolkit):
    # FILL IN: old = await toolkit.get_tree(name); _mutate sets a body; old is unchanged
    ...

@pytest.mark.asyncio
async def test_first_write_migrates_legacy_bodies(tmp_path):
    # FILL IN: hand-write a legacy tree JSON + 0001.md; tag_node-free path: await toolkit._mutate(name, noop)
    ...

@pytest.mark.asyncio
async def test_delete_tree_removes_bodies_and_lock(toolkit):
    # FILL IN
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
9. **Close the task** with `parrot sdd task close TASK-5283 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
