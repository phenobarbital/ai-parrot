# TASK-5285: Port node mutators and remove the in-place write path

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5284
**Assigned-to**: unassigned

---

## Context

Third task on spec §3 **Module 5**. Ports `tag_node`, `delete_node`, `add_node`, `update_node`
and `update_node_content` to `_mutate`, then removes the old write path: `_persist`, `_batch`,
`_batch_depth`/`_batch_dirty`, `_tree_signature`, `_remember_tree_signature`.
`update_node_content` starts publishing a generation (today it writes no JSON, toolkit.py:1198-1221).

---

## Scope

- `tag_node`, `update_node`: find the node in `txn.tree` and edit it inside `apply`.
- `delete_node`: `_delete_node(txn.tree, node_id)`; do **not** delete content files — the sweep owns them.
- `add_node`: splice into `txn.tree` and `txn.set_body(inserted_node, body)`; drop the flat-key
  branch (toolkit.py:1172-1189).
- `update_node_content`: `txn.set_body(node, body)` — publishes.
- Remove `_persist`, `_batch`, `_batch_depth`, `_batch_dirty`, `_tree_signature`,
  `_remember_tree_signature`; use `self._store.signature(name)` where a signature is needed
  (`_load_tree`, `create_tree`); drop the batch shortcut in `_load_tree` (:201).
- `rename_tree`'s guard (toolkit.py:469-470, "inside an open batch") → refuse when `_OPEN_TXNS`
  holds a transaction for `src` or `dst` in the current context (TASK-5286 rewrites the rest).
- Tests: `test_tree_freshness.py::test_batch_keeps_cached_tree` (:50) → `test_open_write_keeps_working_copy`;
  in `test_toolkit.py` add `test_update_node_content_publishes`, `test_delete_node_leaves_blobs_for_sweep`,
  `test_add_node_body_ref`, and rename `test_rename_tree_refuses_inside_batch` (:1388) → `_inside_write`.

**NOT in scope**: the rest of `rename_tree` (TASK-5286).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | Port node mutators; remove legacy write path |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` | MODIFY | Mutator tests |
| `packages/ai-parrot/tests/knowledge/pageindex/test_tree_freshness.py` | MODIFY | Replace batch test |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# knowledge/pageindex/toolkit.py
    self._batch_depth / self._batch_dirty                      # lines 169-170
    def _tree_signature(self, tree_name) -> tuple[int, int] | None   # line 182
    def _remember_tree_signature(self, tree_name) -> None      # line 190
    def _load_tree(self, tree_name) -> dict[str, Any]          # line 198 (batch shortcut :201)
    def _persist(self, tree_name) -> None                      # line 237
    async def _batch(self, tree_name)                          # line 393 (decorator on :392)
    async def rename_tree(self, src, dst, *, overwrite=False)  # line 443 (batch guard :469-470)
    async def tag_node(...)                                    # line 765 (edits :797-808, _persist :811)
    async def delete_node(self, tree_name, node_id) -> dict    # line 1077 (tree_ops :1100, content deletes :1102-1106, _persist :1107)
    async def add_node(...)                                    # line 1110 (splice :1160, flat key :1172-1189, save :1190, _persist :1191)
    async def update_node_content(...)                         # line 1198 (save :1218, mark_dirty :1219-1221)
    async def update_node(...)                                 # line 1228 (edits :1254-1258, _persist :1261)

# knowledge/pageindex/store.py (after TASK-5277)
    def signature(self, tree_name) -> tuple[int, int] | None
# after TASK-5283: _mutate, _write, _OPEN_TXNS, WriteTransaction.set_body
```

### Does NOT Exist
- ~~`_persist`, `_batch`, `_batch_depth`, `_batch_dirty`, `_tree_signature`, `_remember_tree_signature`~~ — removed by this task
- ~~content-file deletion in `delete_node`~~ — removed; `sweep_unreferenced` cleans up after the grace period

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
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_tree_freshness.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.tag_node",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.delete_node",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.add_node",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.update_node_content",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.update_node",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._persist",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._batch",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._tree_signature",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._remember_tree_signature",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._load_tree"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `KeyError`/`ValueError` raised inside `apply` (unknown node, empty title) propagate unchanged and publish nothing.
- Return dicts of every tool stay identical.
- After this task `grep -nE '_persist\(|_batch|_tree_signature|_remember_tree_signature|_save_node_markdown' toolkit.py` finds nothing.

---

## Implementation Blueprint

### Steps (in order)
1. Port the five mutators — *why*: they are the last users of `_persist`.
2. Delete the legacy helpers and attributes; switch signature reads to `self._store.signature`.
3. Replace the batch guard in `rename_tree`.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
Pattern (`update_node`, toolkit.py:1248-1262):
```python
        async def apply(txn: WriteTransaction) -> None:
            node = find_node_by_id(txn.tree.get("structure", []), node_id)
            if node is None:
                raise KeyError(f"node_id {node_id!r} not found in tree {tree_name!r}")
            if title is not None:
                if not isinstance(title, str) or not title.strip():
                    raise ValueError("title must be a non-empty string")
                node["title"] = title.strip()
            if summary is not None:
                node["summary"] = summary

        await self._mutate(tree_name, apply)
```
```python
# occurrences: 1 (verified: grep -cF '    def _persist(self, tree_name: str) -> None:' toolkit.py)
# DELETE _persist (toolkit.py:237-252)
# occurrences: 1 (verified: grep -cF '    async def _batch(self, tree_name: str):' toolkit.py)
# DELETE _batch with its @asynccontextmanager decorator (toolkit.py:392-400)
# occurrences: 1 (verified: grep -cF '    def _tree_signature(self, tree_name: str) -> tuple[int, int] | None:' toolkit.py)
# DELETE _tree_signature and _remember_tree_signature (toolkit.py:182-196); replace their uses with
# self._tree_sigs[...] = self._store.signature(...)
```

### FILL IN checklist
- [ ] port `tag_node`, `delete_node`, `add_node`, `update_node_content`
- [ ] remove the legacy helpers and the `_batch_*` attributes (toolkit.py:169-170)
- [ ] `rename_tree` guard via `_OPEN_TXNS`
- [ ] tests listed in Scope

---

## Acceptance Criteria

- [ ] AC-1: `update_node_content` bumps the generation and the new body is served by `retrieve`.
- [ ] AC-2: `delete_node` removes the node from the published tree and leaves its blob on disk.
- [ ] AC-3: `add_node` with a body sets `body_ref`; no `<node_id>.md` or flat-key file is written by it.
- [ ] AC-4: the grep in Key Constraints finds nothing.
- [ ] AC-5: inside an open `_write`, an external rewrite of the JSON does not change `txn.tree`, and the publish raises `StaleGenerationError`.
- [ ] All tests in `test_toolkit.py` and `test_tree_freshness.py` pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_tree_freshness.py -q`

---

## Test Specification

```python
# test_tree_freshness.py — replaces test_batch_keeps_cached_tree (:50)
@pytest.mark.asyncio
async def test_open_write_keeps_working_copy(tmp_path):
    # FILL IN: open toolkit._write(name); rewrite JSON through a second toolkit; txn.tree unchanged;
    # leaving the block raises StaleGenerationError
    ...

# test_toolkit.py
@pytest.mark.asyncio
async def test_update_node_content_publishes(toolkit):
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
9. **Close the task** with `parrot sdd task close TASK-5285 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
