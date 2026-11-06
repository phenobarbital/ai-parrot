# TASK-5286: rename_tree as a publication of dst with no window and no backup tree

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5285
**Assigned-to**: unassigned

---

## Context

Last task on spec §3 **Module 5**, spec §2 "Rename and swap". Today `rename_tree(overwrite=True)`
moves `dst` to a `--replaced-` backup before moving `src` in (toolkit.py:515-522), so for a moment
`dst` does not exist, and it deletes the backup right after (:534-540). The new flow publishes `dst`
from `src`'s content with one atomic JSON replace.

---

## Scope

- Keep the public signature `rename_tree(src, dst, *, overwrite=False)` and its validation
  (names, `src != dst`, `src` exists, `dst` exists without `overwrite` → `ValueError`, refuse inside
  an open transaction).
- Hold `tree_lock(src)` for the whole operation (blocks writers of `src`); let the
  `WriteTransaction` for `dst` take `dst`'s lock inside `publish()` — *because* the in-process lock is
  not re-entrant, so holding `dst`'s lock here would deadlock. Lock order is always src → dst; a
  crossing rename times out with `TreeLockTimeout` instead of deadlocking.
- Build `WriteTransaction(tree_name=dst, base_tree=<dst's current tree or {"doc_name": src doc_name,
  "structure": []}>, base_signature=<dst signature or None>, ...)`, then set
  `txn.tree = copy.deepcopy(<src tree loaded from disk>)` and `txn.set_body(node, body)` for every node
  with a body (blob via `load_body(src, key)`, else the legacy body as in `_migrate_legacy_bodies`).
- `publish()` (strict OKF projection for `dst` included), `_after_publish(dst, txn)`, then delete
  `src`: JSON, content tree, embedding matrices, lock file, caches.
- Return `{"src": src, "dst": dst, "replaced": replaced, "generation": <new dst id>}`.
- No `--replaced-` tree is ever created. `REPLACED_MARKER` stays exported (Bookstore imports it to
  recover pre-upgrade crashes).
- Tests in `test_toolkit.py` (see Scope list in Test Specification).

**NOT in scope**: Bookstore changes (TASK-5287).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | Rewrite rename_tree |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` | MODIFY | Rename tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# knowledge/pageindex/toolkit.py
REPLACED_MARKER = "--replaced-"; _REPLACED_MARKER = REPLACED_MARKER   # lines 50-51 (keep both)
    async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]   # line 443
        # validation :465-476; backup allocation :478-486; move journal + rollback :488-507;
        # dst→backup :515-516; invalidate src :518-519; src→dst :520-521; rollback :522-524;
        # cache eviction :525-531; backup delete :533-540; post-swap projection :542-547; return :548

# knowledge/bookstore/library.py — caller, must keep working
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, REPLACED_MARKER   # line 30
    await toolkit.rename_tree(tree_name, live_name)                  # line 304 (sweep restores a pre-upgrade backup)
    await toolkit.rename_tree(staging, slug, overwrite=status == "updated")   # line 1146

# after TASK-5279: content_store.load_body(tree, key); after TASK-5283: _after_publish, _migrate_legacy_bodies,
# tree_lock, lock_path; after TASK-5282: WriteTransaction (base_generation captured at construction)
```

### Does NOT Exist
- ~~a `--replaced-` tree created by the new `rename_tree`~~ — never
- ~~`JSONTreeStore.rename` / `NodeContentStore.rename_tree` use in the new flow~~ — the move primitives stay in the stores (their own tests use them) but `rename_tree` no longer calls them

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
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.rename_tree"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `dst`'s generation after an overwrite is `dst.generation + 1` (or 1 for a legacy/absent `dst`),
  never `src.generation + 1` — `WriteTransaction.base_generation` comes from `base_tree`.
- Any failure before `publish()` switches the JSON leaves both trees untouched; delete `src` only
  after a successful publish.
- Existing tests to replace, not delete silently: `test_rename_tree_overwrite_replaces_and_removes_backup`
  (:1251), `_overwrite_removes_backup_dir_with_embeddings` (:1264), `_post_swap_reload_failure_is_not_a_rename_failure`
  (:1281), `_overwrite_rolls_back_on_failure` (:1302), `_refuses_inside_batch` (:1388, already renamed by TASK-5285).

---

## Implementation Blueprint

### Steps (in order)
1. Replace the body of `rename_tree` (toolkit.py:465-548) with the flow below — *why*: spec §2 "Rename and swap".
2. Remove the now-unused imports (`secrets`, `shutil`) only if nothing else uses them.
3. Rewrite the listed tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    async def rename_tree(' toolkit.py)
# REPLACE the body after the docstring (toolkit.py:465-548):
        self._store._validate_name(src)
        self._store._validate_name(dst)
        if src == dst:
            raise ValueError("src and dst must differ")
        # FILL IN: refuse when _OPEN_TXNS holds src or dst for this toolkit (ValueError, same message style)
        if not self._store.exists(src):
            raise KeyError(f"Tree {src!r} does not exist")
        replaced = self._store.exists(dst)
        if replaced and not overwrite:
            raise ValueError(f"Tree {dst!r} already exists")

        async with tree_lock(self._storage_dir, src, timeout=self._lock_timeout_s):
            src_tree = self._store.load(src)
            dst_base = self._store.load(dst) if replaced else {"doc_name": src_tree.get("doc_name", dst), "structure": []}
            txn = WriteTransaction(
                tree_name=dst, base_tree=dst_base, base_signature=self._store.signature(dst),
                store=self._store, content_store=self._content_store, storage_dir=self._storage_dir,
                lock_timeout_s=self._lock_timeout_s, grace_s=self._generation_grace_s,
                projector=self._project_okf_sidecars_for,
            )
            txn.tree = copy.deepcopy(src_tree)
            # FILL IN: stage every body of src into txn (load_body for body_ref, else legacy body)
            report = await txn.publish()
            self._after_publish(dst, txn)
            # FILL IN: delete src JSON, content tree, embedding matrices, lock file; pop src caches
        return {"src": src, "dst": dst, "replaced": replaced, "generation": report.generation}
```

### FILL IN checklist
- [ ] open-transaction guard
- [ ] staging src bodies (blob or legacy)
- [ ] deleting src after publish
- [ ] replacement tests

---

## Acceptance Criteria

- [ ] AC-1: during `rename_tree(src, dst, overwrite=True)` a thread polling `toolkit._store.exists(dst)` every 1 ms never sees `False`.
- [ ] AC-2: no tree name containing `--replaced-` exists after an overwrite rename.
- [ ] AC-3: after the rename `dst` serves `src`'s structure and bodies, `src` no longer exists, and `dst`'s generation is its previous id + 1.
- [ ] AC-4: a projector failure during the rename leaves both `src` and `dst` exactly as before.
- [ ] AC-5: renaming a pre-upgrade `--replaced-` tree back to its live name (Bookstore sweep path) works.
- [ ] `test_rename_tree_reprojects_okf_sidecars`, `_basic`, `_refuses_existing_dst_without_overwrite`, `_invalidates_search_engine_cache`, `_exposed_as_tool` pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`

---

## Test Specification

```python
# test_toolkit.py — replacements
@pytest.mark.asyncio
async def test_rename_tree_no_backup_tree(toolkit):
    # FILL IN: overwrite rename; assert not any("--replaced-" in n for n in await toolkit.list_trees())
    ...

@pytest.mark.asyncio
async def test_rename_tree_no_window(toolkit):
    # FILL IN: threading.Thread polling exists(dst) while awaiting rename_tree(..., overwrite=True)
    ...

@pytest.mark.asyncio
async def test_rename_tree_projection_failure_keeps_both(toolkit, monkeypatch):
    # FILL IN: replaces _post_swap_reload_failure... and _overwrite_rolls_back_on_failure
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
9. **Close the task** with `parrot sdd task close TASK-5286 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
