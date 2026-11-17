# TASK-5284: Port import mutators to copy-on-write publication

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5283
**Assigned-to**: unassigned

---

## Context

Second task on spec §3 **Module 5**. Ports the tools that import content — `insert_markdown`,
`insert_ebook`, `import_pdf` and `import_folder` (`insert_content` and `import_file` delegate and
need no change) — from in-place mutation + `_save_node_markdown` + `_persist`/`_batch` to
`_mutate`/`_write` with bodies staged as blobs.

---

## Scope

- In each ported tool, keep the expensive build (`md_to_tree`, `ebook_tree`, `build_page_index`)
  **outside** the transaction, then call `_mutate(tree_name, apply)` where `apply` deep-copies the
  built subtree, captures the id map, splices into `txn.tree`, stages bodies and runs T3
  classification on `txn.tree` — *because* `apply` may run again after a stale retry and must not
  splice the same objects twice or repeat the build.
- Replace `_save_node_markdown` with `_stage_node_markdown(txn, original_id_to_node, node_markdown)`
  calling `txn.set_body(node, markdown)`; delete `_save_node_markdown`.
- `import_folder`: replace `async with self._batch(...)` / `self._batch_dirty[...] = True`
  (toolkit.py:1067-1069) with `async with self._write(tree_name) as txn:` and splice folder nodes
  into `txn.tree`; the concurrent `insert_content` calls join that transaction through the ContextVar,
  so the folder import publishes exactly once. A folder import is not retried on a stale base — it raises.
- Update `test_folder_import.py` (`test_import_folder_persists_once`, :101 → publishes once) and
  the sidecar assertions in `test_toolkit.py` that check `<node_id>.md` paths (`:260`, `:510`, `:591`):
  assert through `toolkit._content_store.load(name, node_id)` / `body_ref` instead.

**NOT in scope**: node mutators (TASK-5285), `rename_tree` (TASK-5286).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | Port insert_markdown, insert_ebook, import_pdf, import_folder |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` | MODIFY | Adjust sidecar assertions |
| `packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py` | MODIFY | Publishes once |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import copy  # stdlib
```

### Existing Signatures to Use
```python
# knowledge/pageindex/toolkit.py
    async def insert_markdown(...)        # line 819 — md_to_tree :841-845, _pop_node_field :847, _strip_keys_in_place :848,
                                          #   _capture_node_id_object_map :849, splice :850, _save_node_markdown :851, T3 :853, _persist :854
    async def insert_ebook(...)           # line 857 — ebook_tree :872, splice :876, _save_node_markdown :877, T3 :878, _persist :879
    async def import_pdf(...)             # line 930 — build_page_index :954-963, `_node_markdown` pop :968, splice :970, save :971, _persist :972
    def _save_node_markdown(self, tree_name, original_id_to_node, node_markdown) -> None   # line 980 (save :1002)
    async def import_folder(...)          # line 1004 — semaphore :1024, folder splice :1063, `async with self._batch(tree_name):` :1067
    async def _run_t3_classification(self, tree, original_id_to_node) -> None   # line 292
def _pop_node_field(...)                  # line 1273
def _strip_keys_in_place(...)             # line 1306
def _capture_node_id_object_map(subtree) -> dict[str, dict]   # line 1331

# after TASK-5283
    async def _mutate(self, tree_name, apply, *, attempts=3)
    @asynccontextmanager async def _write(self, tree_name) -> AsyncIterator[WriteTransaction]
    WriteTransaction.tree / .set_body(node, markdown)
```

### Does NOT Exist
- ~~`_stage_node_markdown`~~ — added here
- ~~`_save_node_markdown`~~ after this task — deleted

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
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.insert_markdown",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.insert_ebook",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.import_pdf",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.import_folder",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._save_node_markdown"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Return values of the tools are unchanged (`new_node_ids` come from the splice inside `apply`).
- `node_markdown` maps build-time ids to markdown; capture `original_id_to_node` from the **copy**
  spliced in that attempt.
- After this task no ported tool calls `_persist`, `_content_store.save` or `_batch`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_stage_node_markdown` in place of `_save_node_markdown` — *why*: the three import tools share it.
2. Port `insert_markdown`, `insert_ebook`, `import_pdf` to the `apply` pattern below.
3. Port `import_folder` to `_write`.
4. Adjust the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    def _save_node_markdown(' toolkit.py)
# REPLACE _save_node_markdown (toolkit.py:980-1002) with:
    def _stage_node_markdown(
        self,
        txn: WriteTransaction,
        original_id_to_node: dict[str, dict[str, Any]],
        node_markdown: dict[str, str],
    ) -> None:
        """Stage per-node markdown as immutable blobs after a splice into ``txn.tree``."""
        for original_id, markdown in (node_markdown or {}).items():
            node = original_id_to_node.get(original_id)
            if node is not None:
                txn.set_body(node, markdown or "")
```

Pattern for `insert_markdown` (toolkit.py:840-855) — apply the same shape to `insert_ebook` and `import_pdf`:
```python
        subtree = await md_to_tree(md_text=markdown, adapter=self._adapter, doc_name=doc_name or "ingested.md")
        node_markdown = _pop_node_field(subtree, "text")
        _strip_keys_in_place(subtree, ("token_count", "line_num"))

        async def apply(txn: WriteTransaction) -> list[str]:
            fresh = copy.deepcopy(subtree)
            original_id_to_node = _capture_node_id_object_map(fresh)
            new_ids = splice_subtree(txn.tree, fresh, parent_node_id=parent_node_id)
            self._stage_node_markdown(txn, original_id_to_node, node_markdown)
            await self._run_t3_classification(txn.tree, original_id_to_node)
            return new_ids

        new_ids = await self._mutate(tree_name, apply)
        return {"tree_name": tree_name, "new_node_ids": new_ids}
```
`import_folder` (toolkit.py:1023-1069): drop `tree = self._load_tree(tree_name)` (:1023); wrap
`_process_dir(root, parent_node_id)` in `async with self._write(tree_name) as txn:` and splice folder
nodes into `txn.tree` (`# FILL IN`: `_process_dir` needs `txn` — pass it as a parameter).

### FILL IN checklist
- [ ] port `insert_ebook` (keep its return dict)
- [ ] port `import_pdf` (`_node_markdown` pop stays outside `apply`)
- [ ] port `import_folder` with `txn` threaded through `_process_dir`
- [ ] test adjustments (`test_folder_import.py:101`, `test_toolkit.py:260/510/591`)

---

## Acceptance Criteria

- [ ] AC-1: after `insert_markdown`/`insert_ebook`/`import_pdf`, every new node with a body has a `body_ref` whose blob holds the markdown, and no `<node_id>.md` file is written.
- [ ] AC-2: each of those tools bumps the generation by exactly 1.
- [ ] AC-3: `import_folder` over N files bumps the generation by exactly 1.
- [ ] AC-4: `_save_node_markdown` no longer exists; no ported tool calls `_persist` or `_batch`.
- [ ] Existing tests in `test_toolkit.py` and `test_folder_import.py` pass (adjusted where they asserted file paths).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py — replaces test_import_folder_persists_once (:101)
@pytest.mark.asyncio
async def test_import_folder_publishes_once(toolkit, tmp_path):
    # FILL IN: generation before/after differs by exactly 1 for a folder with several files
    ...

# test_toolkit.py
@pytest.mark.asyncio
async def test_insert_markdown_stores_blobs(toolkit):
    # FILL IN: body_ref set, blob content matches, no <node_id>.md on disk
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
9. **Close the task** with `parrot sdd task close TASK-5284 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
