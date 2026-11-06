# TASK-5287: Bookstore: grace period, vacuum on sweep, compatibility with the new rename

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5286
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 8**. Bookstore builds its own `PageIndexToolkit` per scope and
publishes a reindex through `create_tree(staging)` → import → `rename_tree(staging, slug,
overwrite=...)` (`library.py:1042-1153`). After TASK-5286 that rename never leaves the book
without a live tree. This task passes the Bookstore grace period to the toolkit and makes the
reserved-tree sweep also vacuum the books it visits.

---

## Scope

- `_toolkit(scope)` (`library.py:233-242`): pass `generation_grace_s=_STAGING_MAX_AGE_S`.
- `_sweep_reserved_trees(scope)` (`library.py:291-313`): keep restoring a pre-upgrade
  `--replaced-` tree when the live one is missing and deleting it otherwise; keep deleting stale
  `--staging-` trees; additionally call `toolkit.vacuum_tree(live_name)` for every live tree a
  reserved entry points at that exists after processing (best effort, logged like the rest).
- `read_section` (`library.py:367`, body read `:374`) keeps `self._content_store(scope).load(...)`:
  **deviation from the spec M8 note**, recorded here — `read_section` is synchronous and keys by
  the catalog card's `node_id`, not by a node of a held tree, so `load_node` has no node to use;
  `load` resolves the id through the live tree JSON (spec revision 0.2) and returns the blob.
  Note this deviation in the Completion Note.
- Tests in `test_library.py`: the toolkit receives the grace; `read_section` returns the body of a
  book whose nodes only have `body_ref`; a reindex leaves no `--replaced-` tree; the sweep vacuums.

**NOT in scope**: Bookstore's MCP server, catalog or carding changes; the integration test with a
concurrent reader (TASK-5288).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | Grace kwarg, vacuum in sweep |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | Bookstore tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, REPLACED_MARKER   # verified: bookstore/library.py:30
```

### Existing Signatures to Use
```python
# knowledge/bookstore/library.py
_STAGING_MARKER = "--staging-"                                  # line 68
_STAGING_MAX_AGE_S = 3600                                       # line 69
def _is_reserved_tree_name(name) -> bool                        # line 72
class _NullAdapter                                              # line 149 (model/client stand-in)
    def _toolkit(self, scope) -> PageIndexToolkit               # line 233 (constructor call :237-241)
    def _content_store(self, scope) -> NodeContentStore         # line 244
    def _staging_tree_name(self, slug) -> str                   # line 269
    @staticmethod
    def _scan_reserved_trees(trees_dir) -> list[tuple[str, bool, float]]   # line 274
    async def _sweep_reserved_trees(self, scope) -> None        # line 291 (restore :301-304, delete :306, stale staging :307-309)
    def read_section(self, book_id, node_id) -> dict[str, Any]  # line 367 (body read :374)
    async def add_book(...)                                     # line 977 (staging :1042, create :1045, rename :1146, cleanup :1147-1153)

# knowledge/pageindex/toolkit.py (after TASK-5283 / TASK-5286)
    PageIndexToolkit(..., generation_grace_s: int = 3600, lock_timeout_s: float = 30.0)
    async def vacuum_tree(self, tree_name, max_age_s=None) -> dict[str, Any]
    async def rename_tree(self, src, dst, *, overwrite=False) -> dict[str, Any]   # no backup tree, no window
```

### Does NOT Exist
- ~~`NodeContentStore.load_node` use in `read_section`~~ — not applicable (no held node); see Scope
- ~~a Bookstore-level lock~~ — exclusion comes from the toolkit's `tree_lock`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_library.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._toolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._sweep_reserved_trees"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- All 52 existing `test_library.py` tests keep passing, in particular
  `test_reindex_success_swaps_tree_same_book_id` (:691),
  `test_reindex_card_draft_and_swap_failures_keep_old_book` (:726),
  `test_sweep_restores_orphaned_replaced_tree` (:751),
  `test_sweep_deletes_stale_staging_keeps_fresh` (:767),
  `test_cancelled_ingest_cleans_up_staging_tree` (:814).
- Verify the class name owning `_toolkit` before writing the symbol ids above into code comments
  (`grep -n '^class ' library.py`); fix the Complexity Contract symbols if it is not `Bookstore`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the kwarg in `_toolkit` — *why*: one grace period for staging trees and generations.
2. Add the vacuum pass in `_sweep_reserved_trees` — *why*: the sweep already runs at the right moments (startup, before ingest).
3. Tests.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '                lightweight_model=self.lightweight_model,' library.py)
# AFTER — insert below that line inside the PageIndexToolkit(...) call (verified: library.py:240)
                generation_grace_s=_STAGING_MAX_AGE_S,
```
```python
# occurrences: 1 (verified: grep -cF '    async def _sweep_reserved_trees(self, scope: str) -> None:' library.py)
# In _sweep_reserved_trees (library.py:291-313), after the existing loop:
        # FILL IN: for each distinct live name derived from the reserved entries (split on the
        # marker), if toolkit's store has it, await toolkit.vacuum_tree(live_name) inside
        # try/except Exception → logger.warning(..., exc_info=True) — bounded by AC-3
```

### FILL IN checklist
- [ ] vacuum pass; AC-3
- [ ] tests; AC-1..AC-4

---

## Acceptance Criteria

- [ ] AC-1: the toolkit built by `_toolkit()` has `generation_grace_s == _STAGING_MAX_AGE_S`.
- [ ] AC-2: `read_section` returns the stored body for a book whose nodes carry `body_ref` and no `<node_id>.md`.
- [ ] AC-3: `_sweep_reserved_trees` calls `vacuum_tree` for the live trees it visits and never fails the sweep when vacuum raises.
- [ ] AC-4: after an "updated" reindex no tree name contains `--replaced-`.
- [ ] All existing `test_library.py` tests pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`

---

## Test Specification

```python
# add to packages/ai-parrot/tests/knowledge/bookstore/test_library.py
def test_toolkit_receives_grace(bookstore):
    # FILL IN: bookstore._toolkit(scope)._generation_grace_s == _STAGING_MAX_AGE_S
    ...

@pytest.mark.asyncio
async def test_read_section_reads_body_ref(bookstore, tmp_path):
    # FILL IN: add a markdown book, assert nodes have body_ref and read_section returns the text
    ...

@pytest.mark.asyncio
async def test_reindex_leaves_no_replaced_tree(bookstore, tmp_path):
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
9. **Close the task** with `parrot sdd task close TASK-5287 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
