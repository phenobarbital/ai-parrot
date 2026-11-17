# TASK-5310: index_segments for legacy trees; revisions follow rename and delete

**Feature**: FEAT-840 — PageIndex Segment Store
**Spec**: `sdd/specs/pageindex-segment-store.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5309
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 9**. Trees imported before FEAT-840 have bodies but no segments.
`index_segments` (an explicit tool; brainstorm decision: segments are derived from the stored node
markdown, a re-import is suggested for more) gives them section-path addressed revisions. Also makes
`rename_tree(overwrite=True)` carry revisions to the destination and `delete_tree` remove them.

---

## Scope

- New tool `PageIndexToolkit.index_segments(tree_name, node_id=None)`.
- `rename_tree`: stage `src`'s live revisions in the `dst` transaction before publishing; evict `src`
  from the segment cache after cleanup.
- `delete_tree`: `self._segment_store.delete_tree(tree_name)` (cache eviction + files).
- `NodeContentStore.delete_tree`: the sub-directory tuple gains `"segments"`.
- Write `tests/knowledge/pageindex/test_segment_migration.py`.

**NOT in scope**: running `index_segments` implicitly anywhere; Bookstore (TASK-5311).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `index_segments`, rename, delete |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` | MODIFY | Remove `segments/` on delete |
| `packages/ai-parrot/tests/knowledge/pageindex/test_segment_migration.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All needed names are already imported in toolkit.py after TASK-5308/5309:
# SegmentStore, SourceInfo, attach_section_document, derive_doc_id, structure_to_list, WriteTransaction
```

### Existing Signatures to Use
```python
# knowledge/pageindex/toolkit.py
async def delete_tree(self, tree_name) -> dict                                       # :519
            sidecars_removed = self._content_store.delete_tree(tree_name)           # :523 (inside tree_lock)
async def rename_tree(self, src, dst, *, overwrite=False) -> dict                    # :538
                for node in structure_to_list(txn.tree.get("structure", [])):        # :593 body-copy loop
                        body = self._content_store.load_body(src, body_ref)          # :596
                    report = await txn.publish()                                     # :602 (occurrences: 1)
            self._content_store.delete_tree(src)                                     # :611
            self._content_store._cache_evict_tree(src)                               # :617 (occurrences: 1)
def _legacy_body(self, tree_name, node) -> Optional[str]                             # :283
async def _mutate(self, tree_name, apply, *, attempts=3) -> T                        # :244
# from TASK-5308: self._segment_store, self._scan(segments), self._stage_document(txn, revision, roots),
#   self._new_revision(doc_id, segments, source, report), self._doc_ids_in(tree_name, tree), _section_segments(roots, texts)

# knowledge/pageindex/content_store.py
def load_node(self, tree_name, node) -> Optional[str]                                # :211
def delete_tree(self, tree_name) -> int                                              # :406
        for sub in ("bodies", "embeddings"):                                         # :424 (occurrences: 1)

# knowledge/pageindex/segment_store.py (TASK-5302)
@staticmethod
def live_revisions(tree) -> set[tuple[str, str]]
def load_revision(self, tree_name, doc_id, revision) -> Optional[DocumentRevision]
def delete_tree(self, tree_name) -> int
```

### Does NOT Exist
- ~~`index_segments`, `pageindex_index_segments`~~ — created here
- ~~a source file path on legacy subtrees~~ — legacy revisions use `SourceInfo(kind="legacy", name=<root title>)`

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
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_segment_migration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `index_segments` targets **root-level** nodes of `tree["structure"]` that have no `doc_id` (or the one
  root named by `node_id`; a non-root or already-segmented `node_id` raises `ValueError`).
- Texts come from the bodies the tree holds: `{node["node_id"]: self._content_store.load_node(tree_name, node) or ""}`
  over the subtree. Build segments with `_section_segments([root], texts)`, scan with `self._scan`,
  then inside one `_mutate` apply: derive `doc_id` from the root title, build the revision with
  `SourceInfo(kind="legacy", name=root title)`, `attach_section_document`, `self._stage_document`.
- Read bodies and scan **outside** `apply` from a snapshot (`_load_tree`), then inside `apply` re-find
  the root by `node_id` in `txn.tree` and skip it if it gained a `doc_id` meanwhile — *because* `apply`
  can re-run after a stale generation.
- Nothing to do → return `documents: []` and publish nothing (`txn.noop = True`).
- Known limitation (write it in the docstring): a legacy PDF parent body contains its children's text,
  so its revision duplicates that text; the partition is still exact over the revision. A re-import fixes it.
- Rename: before `report = await txn.publish()` stage every `(doc_id, rev)` of `SegmentStore.live_revisions(src_tree)`
  with `self._segment_store.load_revision(src, doc_id, rev)` (skip `None` with a warning).

---

## Implementation Blueprint

### Steps (in order)
1. `content_store.py`: extend the tuple.
2. `toolkit.py`: rename and delete hooks.
3. `toolkit.py`: `index_segments` tool (insert after `read_segments`, added by TASK-5309).
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` (MODIFY)
```python
# MODIFY — `        for sub in ("bodies", "embeddings"):` (verified: content_store.py:424, occurrences: 1)
        for sub in ("bodies", "embeddings", "segments"):
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY) — rename / delete
```python
# BEFORE — insert above `                    report = await txn.publish()` (verified: toolkit.py:602, occurrences: 1)
                for doc_id, rev_id in SegmentStore.live_revisions(src_tree):
                    revision = self._segment_store.load_revision(src, doc_id, rev_id)
                    if revision is None:
                        logger.warning("rename_tree: revision %s@%s of %r is missing; not carried", doc_id, rev_id, src)
                        continue
                    txn.set_revision(revision)

# AFTER — insert below `            self._content_store._cache_evict_tree(src)` (verified: toolkit.py:617, occurrences: 1)
            self._segment_store.delete_tree(src)

# BEFORE — insert above `            sidecars_removed = self._content_store.delete_tree(tree_name)` (verified: :523, occurrences: 1)
            self._segment_store.delete_tree(tree_name)
```
**Why**: `rename_tree` builds `dst` from `src`'s nodes, which still name `src`'s revisions; without staging them
the FEAT-831/TASK-5303 validation rejects the publish. `delete_tree` order: segment store first (cache eviction),
then the content store removes the directory.

### `toolkit.py` (MODIFY) — `index_segments`, inserted after `async def read_segments` (TASK-5309)
```python
    async def index_segments(self, tree_name: str, node_id: Optional[str] = None) -> dict[str, Any]:
        """Create segments for documents imported before segment support, from their stored bodies.

        Run it once per legacy tree to enable ``pageindex_read_segments`` and citations on it.
        Addresses are section paths (no page numbers). A legacy PDF parent's body includes its
        children's text, so that text appears twice in the revision; re-import the PDF to avoid it.

        Returns ``{tree_name, documents: [{doc_id, revision, segments, nodes}], generation}``.
        """
        # FILL IN: snapshot → pick roots (Key Constraints) → texts → _section_segments → _scan per root;
        #   then self._mutate(tree_name, apply) building and staging one revision per root; noop when nothing to do;
        #   return the summary with the live generation id — bounded by AC-1, AC-2
        raise NotImplementedError
```

### FILL IN checklist
- [ ] `index_segments` body; bounded by AC-1, AC-2

---

## Acceptance Criteria

- [ ] AC-1: on a FEAT-831 tree created with `add_node`/`update_node_content` (no `doc_id`), `index_segments` creates one `legacy` revision per root-level subtree with section addresses, sets `doc_id`/`revision`/`span`/`owned` on its nodes and publishes exactly one new generation; `read_segments(node_id=...)` then works.
- [ ] AC-2: a second `index_segments` returns `documents: []` and does not bump the generation; a `node_id` that is not a root raises `ValueError`.
- [ ] AC-3: after `rename_tree(src, dst, overwrite=True)`, `read_pages(dst, doc, "1")` returns the same segments as before on `src`.
- [ ] AC-4: `delete_tree` removes `<tree>/segments/`.
- [ ] `ruff check` on both source files passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_migration.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_segment_migration.py
# Setup: adapter/toolkit/tiktoken-stub pattern of test_toolkit.py:19-71 (define the fixtures in this file).
import pytest


@pytest.mark.asyncio
async def test_index_segments_legacy_tree(toolkit):
    # FILL IN: create_tree + add_node x3 (one nested) + update_node_content bodies; index_segments; assertions — AC-1
    ...


@pytest.mark.asyncio
async def test_index_segments_idempotent_and_root_only(toolkit):
    # FILL IN — AC-2
    ...


@pytest.mark.asyncio
async def test_rename_tree_copies_revisions(toolkit, tmp_path, monkeypatch):
    # FILL IN: import_pdf with the fake build_page_index of test_segment_import.py; rename overwrite; read_pages — AC-3
    ...


@pytest.mark.asyncio
async def test_delete_tree_removes_segments(toolkit, tmp_path):
    # FILL IN — AC-4
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-segment-store --feature-id FEAT-840`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design,
   §7 holds the splitter rules and the known risks).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-segment-store.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   within the constraint it names; touch only the files in *Files to Create / Modify*.
7. **Validate** — `ruff check --fix` on your files, then every command under *Validation Commands*.
8. **Commit code** (`feat(pageindex-segment-store): TASK-5310 — index_segments for legacy trees; revisions follow rename and delete`), then close with
   `parrot sdd task close TASK-5310 pageindex-segment-store verified` and fill the Completion Note.

---

## Completion Note

Added index_segments tool (root-level legacy subtrees, kind=legacy, noop when nothing to do), rename_tree carries live revisions and evicts src, delete_tree removes segments, NodeContentStore.delete_tree also removes segments/. This also resolves the interim Bookstore reindex failure noted in TASK-5308. 4 new tests; 108 tests pass across content_store/toolkit/generation_integration/migration.

**Completed by**: sdd-worker (sequential fallback; parrot-sdd-coder MCP unavailable)
**Date**: 2026-11-07
**Notes**: tests run with a scratchpad-only shim for navconfig's read-only log dir (environment, not committed)
**Deviations from spec**: none
