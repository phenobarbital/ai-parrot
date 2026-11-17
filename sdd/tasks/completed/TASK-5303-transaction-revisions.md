# TASK-5303: Stage and publish revisions in WriteTransaction

**Feature**: FEAT-840 — PageIndex Segment Store
**Spec**: `sdd/specs/pageindex-segment-store.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5302
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 4**. Revisions must be published *with* the generation that first
references them (spec decision `revisions-published-with-generations`): staged in the FEAT-831
transaction, validated in publication step 3, written durably in step 4 before the JSON switch,
and marked superseded / swept with the same grace rule as body blobs.

---

## Scope

- `WriteTransaction.__init__` gains `segment_store: Optional[SegmentStore] = None` (default
  `SegmentStore(storage_dir)`) and records the base generation's live revisions.
- New `set_revision(rev)` and `live_revisions()`.
- `_publish_locked`: validate live revisions, write staged revisions (then fsync `segments/`)
  before the body blobs, and after the JSON save `mark_superseded` + `sweep_unreferenced` for revisions.
- Append tests to `tests/knowledge/pageindex/test_generation.py`.

**NOT in scope**: any toolkit change (the toolkit keeps constructing `WriteTransaction` without the
new kwarg; the default store is correct because revision files are immutable). `PublishReport` is unchanged.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py` | MODIFY | Revision staging + publication |
| `packages/ai-parrot/tests/knowledge/pageindex/test_generation.py` | MODIFY | Append revision tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.store import JSONTreeStore            # generation.py:20 (existing)
from parrot.knowledge.pageindex.segment_store import SegmentStore     # created by TASK-5302
from parrot.knowledge.pageindex.segments import DocumentRevision      # created by TASK-5300
```

### Existing Signatures to Use
```python
# knowledge/pageindex/generation.py
class WriteTransaction:                                                          # :114
    def __init__(self, *, tree_name, base_tree, base_signature, store, content_store, storage_dir,
                 lock_timeout_s, grace_s, projector: Callable[[dict[str, Any], str], bool]) -> None  # :117-129
    self._staged: dict[str, str] = {}                                            # :141
    base_nodes = structure_to_list(base_tree.get("structure", []))               # :145
    self._base_legacy_ids: set[str] = {                                          # :149-153 (last statement of __init__)
    def drop_body(self, node) -> None                                            # :170
    @staticmethod
    def _fsync_bodies_dir(path: Path) -> None                                    # :178-187 — reuse for segments/
    async def _publish_locked(self) -> PublishReport:                            # :207
        # stale check :209-218; ensure_concept_ids(self.tree) :220; body_ref validation loop :221-233
        staged_keys = [key for key in self._staged if ...]                       # :235 — step 4 starts here
        await asyncio.to_thread(self._fsync_bodies_dir, self._content.bodies_dir(self.tree_name))  # :242
        okf_projected = await asyncio.to_thread(self._projector, self.tree, self.tree_name)         # :244
        self.published_signature = self._store.save(self.tree_name, self.tree)  # :247 — the switch
        await asyncio.to_thread(self._content.mark_superseded, ...)             # :251-256
        bodies_swept = await asyncio.to_thread(                                  # :257-259
        return PublishReport(                                                    # :261

# tests/knowledge/pageindex/test_generation.py — existing; read its helpers before appending
```

### Does NOT Exist
- ~~`WriteTransaction.set_revision`, `segment_store` kwarg, `_staged_revisions`~~ — created here
- ~~`PublishReport.revisions_written`~~ — do NOT add fields to `PublishReport` (spec keeps it unchanged)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_generation.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py#WriteTransaction"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Write revisions **before** body blobs and both **before** the JSON switch — *because* a crash after
  the switch must find every referenced file (FEAT-831 invariant).
- Validation (step 3) raises `ValueError(f"missing revision {doc_id}@{rev} for node {node_id!r}")` when
  a node names a pair that is neither staged nor on disk; nothing is written in that case.
- Superseded = base live revisions − candidate live revisions; mark them, then sweep with
  `max_age_s=self._grace_s` — *because* the grace runs from supersession (same reason as bodies, :249-250).
- File I/O in `asyncio.to_thread`, like the existing blob writes.

---

## Implementation Blueprint

### Steps (in order)
1. Add the import and the `segment_store` kwarg — *why*: the store is needed in every later step.
2. Add `set_revision` / `live_revisions`.
3. Extend `_publish_locked` at the three anchors below.
4. Append the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py` (MODIFY)
```python
# AFTER — insert below `from parrot.knowledge.pageindex.store import JSONTreeStore` (verified: generation.py:20)
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.store import JSONTreeStore' generation.py)
from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.segments import DocumentRevision

# MODIFY — signature: after `        projector: Callable[[dict[str, Any], str], bool],` (verified: generation.py:128)
# occurrences: 1 (verified: grep -c 'projector: Callable\[\[dict\[str, Any\], str\], bool\],' generation.py)
        segment_store: Optional[SegmentStore] = None,

# AFTER — append after the `self._base_legacy_ids: set[str] = {...}` statement (verified: generation.py:149-153)
# occurrences: 1 (verified: grep -c 'self._base_legacy_ids: set\[str\] = {' generation.py)
        self._segments = segment_store if segment_store is not None else SegmentStore(self._storage_dir)
        self._staged_revisions: dict[tuple[str, str], DocumentRevision] = {}
        self._base_revisions: set[tuple[str, str]] = SegmentStore.live_revisions(base_tree)

# BEFORE — insert above `    def drop_body(self, node: dict[str, Any]) -> None:` (verified: generation.py:170)
# occurrences: 1 (verified: grep -c 'def drop_body(self, node: dict\[str, Any\]) -> None:' generation.py)
    def set_revision(self, rev: DocumentRevision) -> None:
        """Stage ``rev`` under ``(doc_id, revision)``; idempotent."""
        self._staged_revisions[(rev.doc_id, rev.revision)] = rev

    def live_revisions(self) -> set[tuple[str, str]]:
        """Every ``(doc_id, revision)`` named by a node of ``self.tree``."""
        return SegmentStore.live_revisions(self.tree)

# BEFORE — insert above `        staged_keys = [key for key in self._staged if ...` (verified: generation.py:235)
# occurrences: 1 (verified: grep -c 'staged_keys = \[key for key in self._staged' generation.py)
        # FILL IN: step 3b — for each pair in self.live_revisions(): raise ValueError when it is neither in
        #   self._staged_revisions nor self._segments.has_revision(...) — bounded by AC-1
        # FILL IN: step 4a — asyncio.to_thread(self._segments.save_revision, self.tree_name, rev) for every staged
        #   revision, then asyncio.to_thread(self._fsync_bodies_dir, self._segments.segments_dir(self.tree_name))
        #   — bounded by AC-2

# BEFORE — insert above `        return PublishReport(` (verified: generation.py:261)
# occurrences: 1 (verified: grep -c '        return PublishReport(' generation.py)
        # FILL IN: mark_superseded(self.tree_name, self._base_revisions - self.live_revisions()) then
        #   sweep_unreferenced(self.tree_name, self.tree, max_age_s=self._grace_s), both via asyncio.to_thread
        #   — bounded by AC-3
```
**Why this shape**: the three insertion points are exactly publication steps 3, 4 and 8 of FEAT-831
(spec §2 Overview). Keeping the default store inside the transaction means no toolkit call site changes.

### FILL IN checklist
- [ ] step 3b validation; bounded by AC-1
- [ ] step 4a write + fsync; bounded by AC-2
- [ ] supersede + sweep; bounded by AC-3

---

## Acceptance Criteria

- [ ] AC-1: a node naming a revision that is neither staged nor on disk makes `publish()` raise `ValueError`; the tree JSON is unchanged.
- [ ] AC-2: with `os.replace` patched to fail on the tree JSON path, the revision file exists (orphan) and the on-disk tree is the old generation.
- [ ] AC-3: replacing revision R by R' in a publish keeps R's file until it is older than `grace_s`; a later publish (or an aged mtime) removes it; R' is never removed.
- [ ] AC-4: every existing test in `test_generation.py` and `test_generation_integration.py` still passes.
- [ ] `ruff check` on `generation.py` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_generation.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_generation.py  (append; reuse the module's existing
# WriteTransaction construction helper — read the top of the file first)

@pytest.mark.asyncio
async def test_publish_requires_live_revisions(tmp_path):
    # FILL IN: node with doc_id/revision but nothing staged → ValueError; JSON unchanged — AC-1
    ...


@pytest.mark.asyncio
async def test_publish_writes_revisions_before_json(tmp_path, monkeypatch):
    # FILL IN: patch os.replace to raise for "<tree>.json" only; revision file exists afterwards — AC-2
    ...


@pytest.mark.asyncio
async def test_reimport_keeps_old_revision_for_grace(tmp_path):
    # FILL IN: publish R, publish R'; R kept; os.utime R into the past; publish again; R gone — AC-3
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
8. **Commit code** (`feat(pageindex-segment-store): TASK-5303 — Stage and publish revisions in WriteTransaction`), then close with
   `parrot sdd task close TASK-5303 pageindex-segment-store verified` and fill the Completion Note.

---

## Completion Note

WriteTransaction gains segment_store kwarg, set_revision, live_revisions; publish validates live revisions, writes staged revisions + fsync before blobs, marks superseded and sweeps after the JSON switch. 3 new tests; 24 generation tests pass.

**Completed by**: sdd-worker (sequential fallback; parrot-sdd-coder MCP unavailable)
**Date**: 2026-11-07
**Notes**: tests run with a scratchpad-only shim for navconfig's read-only log dir (environment, not committed)
**Deviations from spec**: none
