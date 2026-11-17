# TASK-5329: `vacuum_tree` grace floor + revision sweep; `rename_tree` fails fast on a missing revision

**Feature**: FEAT-844 — PageIndex Toolkit Fixes
**Spec**: `sdd/specs/pageindex-toolkit-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:4780eadd5fa5`

---

## Context

Implements spec §3 **Module 2** (decisions D1 and D2 in spec §7). `pageindex_vacuum_tree` is an
LLM-callable tool; today it accepts `max_age_s=0`, which deletes body blobs a reader of the previous
generation still needs (ledger `issue:4780eadd5fa5` item S6 — the other items of that issue are
already fixed on `dev`). It also sweeps only body blobs, never the segment-store revision files
(`issue:b42f99778d5f` item 3). `rename_tree` logs "not carried" for a missing live revision of the
source and then fails later inside `publish` with a misleading "missing revision" error
(`issue:b42f99778d5f` item 2).

---

## Scope

- `vacuum_tree`: `effective = self._generation_grace_s if max_age_s is None else max(int(max_age_s), self._generation_grace_s)`;
  run `NodeContentStore.sweep_unreferenced` **and** `SegmentStore.sweep_unreferenced` with
  `effective`, both via `asyncio.to_thread`, still under `tree_lock`; return
  `{"tree_name", "removed", "revisions_removed", "max_age_s": effective}`; update the docstring
  (it is the LLM-facing tool description).
- `rename_tree`: replace the `logger.warning(... "not carried")` + `continue` with
  `raise ValueError(f"rename_tree: revision {doc_id}@{rev_id} of {src!r} is missing")`.
- Tests: `test_toolkit.py` (floor; revision sweep), update
  `test_generation_integration.py::test_crash_between_bodies_and_json` (reopen with
  `generation_grace_s=0`), `test_segment_migration.py` (rename fail-fast).

**NOT in scope**: any other method of `toolkit.py` (TASK-5330/5331 edit the same file after this
task); `SegmentStore`/`NodeContentStore` internals; the tool's MCP schema beyond its docstring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `vacuum_tree`, `rename_tree` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` | MODIFY | floor + revision-sweep tests |
| `packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py` | MODIFY | `max_age_s=0` → `generation_grace_s=0` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_segment_migration.py` | MODIFY | rename fail-fast test |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `origin/dev` @ `a3dec1c902` (2026-11-08). Re-locate anchors with `grep -nF`.

### Verified Imports
```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit                 # toolkit.py:89
from parrot.knowledge.pageindex.segment_store import SegmentStore               # imported in toolkit.py (used :636/:705)
from parrot.knowledge.pageindex.generation import generation_of                 # used toolkit.py:1085
# toolkit.py already imports asyncio, random, Optional, Any; tree_lock / lock_path from .locks
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):
    def __init__(..., generation_grace_s: int = 3600, ...)                               # :160; self._generation_grace_s :179
    self._content_store: NodeContentStore ; self._segment_store: SegmentStore ; self._embedding_store
    async def rename_tree(self, src, dst, *, overwrite=False) -> dict[str, Any]:            # :642
        for doc_id, rev_id in sorted(SegmentStore.live_revisions(src_tree)):                 # :705
            revision = self._segment_store.load_revision(src, doc_id, rev_id)                # :706
            if revision is None:                                                             # :707
                logger.warning("rename_tree: revision %s@%s of %r is missing; not carried", doc_id, rev_id, src)  # :708
                continue                                                                     # :709
            txn.set_revision(revision)                                                       # :710
    async def vacuum_tree(self, tree_name: str, max_age_s: Optional[int] = None) -> dict[str, Any]:   # :1071
        async with tree_lock(self._storage_dir, tree_name, timeout=self._lock_timeout_s):    # :1077
            tree = self._store.load(tree_name)                                               # :1078
            removed = self._content_store.sweep_unreferenced(tree_name, tree, max_age_s=...) # :1079-1083
            if self._embedding_store is not None: ... prune_tree_matrices(...)               # :1084-1086
        return {"tree_name": tree_name, "removed": removed}                                  # :1087

# packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py
class SegmentStore:
    def revision_path(self, tree_name: str, doc_id: str, revision: str) -> Path            # :39
    def live_revisions(tree: dict[str, Any]) -> set[tuple[str, str]]  (staticmethod)        # :98
    def sweep_unreferenced(self, tree_name: str, tree: dict[str, Any], *, max_age_s: int) -> int   # :120 — non-live revision files older than max_age_s

# packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py
class NodeContentStore:
    def sweep_unreferenced(self, tree_name: str, tree: dict[str, Any], *, max_age_s: int) -> int   # :322

# tests
# test_generation_integration.py:148-153 — `reopened = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path)`;
#     `report = await reopened.vacuum_tree("t", max_age_s=0)`; `assert report["removed"] == 1`
# test_segment_migration.py — fixture `toolkit(tmp_path)` (:38), `_adapter()` (:13), autouse `_stub_tiktoken` (:26);
#     test_rename_tree_copies_revisions(toolkit, tmp_path, monkeypatch) (:96) shows how a tree with revisions is built
# test_toolkit.py — fixture `toolkit` + `_adapter()` (:19); uses `tmp_path`
```

### Does NOT Exist
- ~~`vacuum_tree(..., force=True)`~~ / ~~`min_age_s`~~ — no bypass parameter; the floor is unconditional (D1).
- ~~`SegmentStore.vacuum` / `SegmentStore.sweep`~~ — the method is `sweep_unreferenced`.
- ~~`PageIndexToolkit._segments`~~ — the attribute is `self._segment_store` (`WriteTransaction` uses `_segments`, the toolkit does not).
- ~~`RevisionUnavailableError` raised by `rename_tree`~~ — D2 fixes a plain `ValueError` with the message above.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_segment_migration.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.vacuum_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.rename_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py#SegmentStore.sweep_unreferenced",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore.sweep_unreferenced"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- D1: a caller can never go **below** the grace; `max_age_s` larger than the grace is honoured.
  `None` means the grace. Report the effective value so an agent sees why nothing was removed.
- Both sweeps are blocking file I/O → `asyncio.to_thread`, still inside the `tree_lock` block
  (the lock is what makes the sweep safe against a concurrent publish).
- D2: raise **before** the `WriteTransaction` for `dst` publishes — the check sits inside the
  `for attempt in range(3)` loop body, so raising there leaves `dst` untouched.
- The `vacuum_tree` docstring is the LLM-facing tool description: say that ages below the grace
  are raised to it, in one sentence.

### References in Codebase
- `generation.py:286-295` — the publish path already runs both sweeps via `asyncio.to_thread`; mirror it.

---

## Implementation Blueprint

### Steps (in order)
1. Rewrite `vacuum_tree` — *why*: D1 + item 3; keep the lock and the embedding prune exactly as they are.
2. Replace the rename warning with a `ValueError` — *why*: D2, fail before touching `dst`.
3. Update `test_crash_between_bodies_and_json` — *why*: it relied on `max_age_s=0` bypassing the grace, which D1 forbids.
4. Add the new tests — *why*: AC-4, AC-5.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    async def vacuum_tree(self, tree_name: str, max_age_s: Optional[int] = None) -> dict[str, Any]:' packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py)
# REPLACE the whole method (verified: toolkit.py:1071-1087) with:
    async def vacuum_tree(self, tree_name: str, max_age_s: Optional[int] = None) -> dict[str, Any]:
        """Remove files unreferenced by the live generation of a tree.

        Sweeps body blobs and document revision files older than ``max_age_s`` seconds. The age is
        never lower than the configured generation grace: a smaller ``max_age_s`` is raised to it,
        so readers of the previous generation keep their bodies. Returns the effective ``max_age_s``.
        """
        effective = self._generation_grace_s if max_age_s is None else max(int(max_age_s), self._generation_grace_s)
        async with tree_lock(self._storage_dir, tree_name, timeout=self._lock_timeout_s):
            tree = self._store.load(tree_name)
            removed = await asyncio.to_thread(
                self._content_store.sweep_unreferenced, tree_name, tree, max_age_s=effective
            )
            revisions_removed = await asyncio.to_thread(
                self._segment_store.sweep_unreferenced, tree_name, tree, max_age_s=effective
            )
            if self._embedding_store is not None:
                generation = generation_of(tree)
                self._embedding_store.prune_tree_matrices(tree_name, keep={generation.id} if generation else set())
        return {
            "tree_name": tree_name,
            "removed": removed,
            "revisions_removed": revisions_removed,
            "max_age_s": effective,
        }

# occurrences: 1 (verified: grep -cF 'logger.warning("rename_tree: revision %s@%s of %r is missing; not carried", doc_id, rev_id, src)' packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py)
# REPLACE the two lines `logger.warning("rename_tree: revision %s@%s of %r is missing; not carried", doc_id, rev_id, src)` / `continue` (verified: toolkit.py:708-709) with:
                        raise ValueError(f"rename_tree: revision {doc_id}@{rev_id} of {src!r} is missing")
```
**Why**: the embedding prune and the lock are unchanged (spec: touch only what the decisions
need). The `int(...)` guards a float/str coming from an LLM tool call.

### `packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    report = await reopened.vacuum_tree("t", max_age_s=0)' packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py)
# REPLACE `    reopened = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path)` (verified: :148) with:
    reopened = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path, generation_grace_s=0)
# REPLACE `    report = await reopened.vacuum_tree("t", max_age_s=0)` (verified: :150) with:
    report = await reopened.vacuum_tree("t")
```
**Why**: the test's intent (an orphan blob is vacuumed) survives; the bypass it used does not (D1).

### `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` (MODIFY)
```python
# APPEND at end of file
async def test_vacuum_tree_floors_max_age_to_grace(tmp_path: Path) -> None:
    """AC-4: max_age_s below the grace is raised to it; nothing young is removed."""
    tk = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path)  # grace 3600
    await tk.create_tree("t")
    # FILL IN: add a node with a body, delete it (blob stays for the sweep), then
    #   report = await tk.vacuum_tree("t", max_age_s=0)
    #   assert report["removed"] == 0 and report["revisions_removed"] == 0 and report["max_age_s"] == 3600
    #   — bounded by AC-4


async def test_vacuum_tree_sweeps_revisions(tmp_path: Path) -> None:
    """AC-4: with grace 0 an orphan body and a superseded revision file are both removed."""
    tk = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path, generation_grace_s=0)
    await tk.create_tree("t")
    # FILL IN: insert_markdown twice with different text so the first revision is superseded
    #   (see test_generation.py::test_reimport_keeps_old_revision_for_grace for the shape), delete the
    #   subtree, then vacuum_tree("t") -> report["revisions_removed"] >= 1 — bounded by AC-4
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_segment_migration.py` (MODIFY)
```python
# APPEND at end of file
async def test_rename_tree_missing_revision_fails_fast(toolkit, tmp_path: Path) -> None:
    """AC-5: a missing live revision of src raises before dst exists."""
    # FILL IN: build a tree with one imported document (as test_rename_tree_copies_revisions does),
    #   unlink toolkit._segment_store.revision_path("src", doc_id, revision), then
    #   with pytest.raises(ValueError, match="is missing"): await toolkit.rename_tree("src", "dst")
    #   assert not toolkit._store.exists("dst") — bounded by AC-5
```

### FILL IN checklist
- [ ] `test_vacuum_tree_floors_max_age_to_grace` body — bounded by AC-4
- [ ] `test_vacuum_tree_sweeps_revisions` body — bounded by AC-4
- [ ] `test_rename_tree_missing_revision_fails_fast` body — bounded by AC-5

---

## Acceptance Criteria

- [ ] AC-4 `vacuum_tree(max_age_s=0)` with the default grace removes nothing and reports `max_age_s == 3600`; with `generation_grace_s=0` it removes orphan blobs and superseded revision files and reports both counts.
- [ ] AC-5 `rename_tree` over a tree whose live revision file is missing raises `ValueError` containing `is missing` and leaves no destination tree JSON.
- [ ] `test_generation_integration.py` passes with the updated test.
- [ ] AC-13 `ruff check` clean on the four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_migration.py -q`

---

## Test Specification

See the MODIFY blocks above.

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug pageindex-toolkit-fixes --feature-id FEAT-844`); never on `dev`.
2. Re-locate every anchor with `grep -nF`; mark `in-progress` in `sdd/tasks/index/pageindex-toolkit-fixes.json`, commit only the index.
3. Implement from the blueprint; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit the four files; `parrot sdd task close TASK-5329 pageindex-toolkit-fixes verified`; fill the Completion Note; commit the SDD state.

---

## Completion Note

**Completed by**: Claude Opus 5.5 (/sdd-fix session agent:sdd-fix:507d6e6a)
**Date**: 2026-11-08
**Notes**: `vacuum_tree` clamps `max_age_s` to `max(int(max_age_s), generation_grace_s)` (None = grace), runs both `NodeContentStore.sweep_unreferenced` and `SegmentStore.sweep_unreferenced` via `asyncio.to_thread` under the tree lock, and returns `{tree_name, removed, revisions_removed, max_age_s}`; docstring rewritten (LLM-facing). `rename_tree` raises `ValueError("rename_tree: revision ...@... of '...' is missing")` instead of warn+continue. Tests: `test_vacuum_tree_floors_max_age_to_grace`, `test_vacuum_tree_sweeps_revisions` (files aged with os.utime — a grace of 0 would already sweep at publish time, so the test keeps the default grace), `test_rename_tree_missing_revision_fails_fast` (fresh toolkit instance so no cached revision masks the missing file; placed in test_segment_migration.py, not test_tree_ops.py which holds pure tree-op tests); `test_crash_between_bodies_and_json` reopens with `generation_grace_s=0`. Validation: 78 passed; ruff clean except a pre-existing E402 at test_toolkit.py:369. Code commit: 51556a97cb.

**Deviations from spec**: the rename fail-fast test lives in `test_segment_migration.py` (spec §3 M2 named `test_tree_ops.py`, which has no toolkit fixture).
