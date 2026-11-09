# TASK-5391: Normalization identity and key-item anchor integrity

**Feature**: FEAT-853 — PageIndex Optimizer Fixes
**Spec**: `sdd/specs/pageindex-optimizer-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:33ad15e686e9`, `issue:66f376157327`

---

## Context

Spec §2 A and B, Module 1. Two defects make the optimizer reject its whole candidate.

- **Empty leaf (`issue:33ad15e686e9`).** `normalize` pops an empty leaf without recording its
  `concept_id` (`optimizer.py:323`). `validate_candidate` then reports `protected node <id> was
  removed` (`optimizer.py:678`). A published tree with a blank "Preface" can never be
  re-optimized.
- **Stale anchors (`issue:66f376157327` items 1–2).** Ownership changes after key items are
  attached:
  - `split_at` turns a leaf into a parent whose `owned` shrinks to the residual before its first
    heading, but the leaf's key items stay on it.
  - `_absorb` merges `owned` but never widens `span`, so `assign_ownership` rebuilds the leaf's
    `owned` from its `span` and hands the absorbed range (and its title key item) to the parent.

  One stale anchor fails `validate_candidate` and discards the whole run.

This task fixes the root causes and adds a fail-soft safety net, `reconcile_key_items`, wired
into `plan_deterministic`. TASK-5393 wires the same safety net into `run_llm_passes`.

---

## Scope

- Add `OptimizeReport.key_items_rehomed: int = 0` right after `rejected_proposals`.
- `_absorb`: when `absorbed` owns ranges, widen `absorber["span"]` to cover their extent
  (min start, max end of the absorbed `owned`). An absorbed node without owned ranges leaves the
  span unchanged.
- `normalize`: add keyword `parent: Optional[dict] = None`. Empty-leaf rule:
  - published (`node_id` set) without a `concept_id` → keep it;
  - else, with `parent` → `_absorb(parent, node, "empty", report, revision)`, then pop;
  - else (no `parent`) → pop, unrecorded (legacy).
  
  The recursion passes `parent=child`.
- `split_at`: after `assign_ownership(node)`, move each of `node`'s key items whose `seq` now
  lies inside a piece's `owned` onto that piece (`report.key_items_rehomed += 1` per item).
- New `reconcile_key_items(root, revision, mutable, report)` per the spec skeleton.
- `plan_deterministic`: pass `parent=root` to `normalize`. After
  `plan.optimizable_roots = roots`, call `reconcile_key_items(root, revisions[key], plan.mutable,
  report)` for every root.
- Tests: unit tests in `test_optimizer.py`; the toolkit-level empty-leaf apply test in
  `test_optimizer_toolkit.py`.

**NOT in scope**:
- `is_heading_text` and pseudo-headings (TASK-5392).
- Anything in `optimizer_llm.py`, including the `run_llm_passes` reconcile call (TASK-5393).
- `toolkit.py` (not modified by this feature) and `segments.py`.
- `validate_candidate` stays unchanged.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | report counter, `_absorb` span, `normalize(parent=…)`, `split_at` re-homing, `reconcile_key_items`, `plan_deterministic` wiring |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` | MODIFY | unit tests for AC-1…AC-5 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py` | MODIFY | `test_optimize_apply_with_empty_leaf` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported at the top of optimizer.py (verified: optimizer.py:5-23) — add nothing new
from typing import Any, Literal, Optional
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment, validate_ownership
from parrot.knowledge.pageindex.utils import structure_to_list

# tests (verified: test_optimizer.py:5-24, test_optimizer_toolkit.py:3-12)
from parrot.knowledge.pageindex.optimizer import (
    OptimizeReport, OptimizerSettings, OptimizePlan, assign_ownership, expand_at_headings,
    normalize, plan_deterministic, validate_candidate,
)
from parrot.knowledge.pageindex.segments import DocumentRevision, revision_id, segment_text
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.utils import structure_to_list
```
`reconcile_key_items` and `split_at` are imported by the tests from
`parrot.knowledge.pageindex.optimizer` once this task creates/changes them.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py
class KeyItem(BaseModel): label: str; kind: Literal["literal", "abstractive"]; seq: int; page; ordinal  # line 47
class MergeAction(BaseModel): reason: Literal["duplicate_span", "empty", "under_minimum"]  # line 74/81
class OptimizeReport(BaseModel):                     # line 93
    merged: list[MergeAction]                        # line 106
    key_items_added: int = 0                         # line 108
    rejected_proposals: int = 0                      # line 113
class OptimizePlan:                                  # line 121 — .candidate, .report, .mutable: set[int], .optimizable_roots
def _merge_ranges(ranges: list[list[int]]) -> list[list[int]]:  # line 144
def _absorb(absorber, absorbed, reason, report, revision) -> None:  # line 277; last line `_record_merge(...)` line 306
def normalize(parent_children, revision, settings, report) -> None:  # line 309; recursion line 315; empty rule line 323-325
def assign_ownership(node: dict) -> None:            # line 369 — a leaf's owned becomes [span]
def split_at(node, revision, seqs, *, source, settings, report) -> list[dict]:  # line 432
    # line 474: node["nodes"] = pieces ; line 475: assign_ownership(node)
def _document_nodes(root: dict, doc_id: str, revision: str) -> list[dict]:  # line 593
def plan_deterministic(tree, revisions, settings, *, tree_name, node_id=None) -> OptimizePlan:  # line 600
    # line 618: normalize(root.get("nodes") or [], revision, settings, report)
    # line 635: plan.optimizable_roots = roots
def validate_candidate(plan, revisions, *, base_tree) -> list[str]:  # line 653 — alias rule line 676, "was removed" line 678

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py (read-only for this task)
#   PageIndexToolkit._store.load(tree_name) -> dict / ._store.save(tree_name, tree)  (store.py:57, :63)
#   test helper _tree_with_document(tmp_path, name="guide")  (test_optimizer_toolkit.py:117)
#   PageIndexToolkit.optimize(tree_name, apply=..., llm_passes=...) -> dict report
```

### Does NOT Exist
- ~~`parrot.knowledge.pageindex.optimizer.reconcile_key_items`~~ — created here.
- ~~`OptimizeReport.key_items_rehomed`~~ — created here.
- ~~`normalize(..., parent=...)`~~ — the keyword is new; today `normalize` never sees the parent node.
- ~~`OptimizePlan.rehome`~~ / ~~`KeyItem.node_id`~~ — not real.
- `toolkit._restore_merged_ownership` must not be edited (spec Non-Goals).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#OptimizeReport",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#_absorb",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#normalize",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#split_at",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#assign_ownership",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#plan_deterministic",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#validate_candidate"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pure, synchronous code; no logging needed (module has none).
- Key items can be `dict` or `KeyItem`. Read `seq`/`label` with the existing idiom
  `item.get("seq") if isinstance(item, dict) else item.seq`.
- A node is mutable iff `id(node) in mutable`. `reconcile_key_items` must never append to or
  remove from a non-mutable node, because `restore_protected` and the protected-node check in
  the toolkit compare those nodes with the base tree.
- Ranges are half-open `[start, end)`.
- The absorber for an empty leaf is the **parent**, never a sibling. The toolkit's alias-span
  restore (`toolkit.py:112`) is a no-op for a parent, but could widen a sibling across a
  neighbour.

---

## Implementation Blueprint

### Steps (in order)
1. Add the report counter — *why*: AC-5 counts moved anchors separately from drops.
2. Widen the span in `_absorb` — *why*: `assign_ownership` rebuilds a leaf's `owned` from its
   `span`, which today silently returns absorbed ranges to the parent (AC-4).
3. Add `parent` to `normalize` and absorb empty leaves into it — *why*: the alias is what
   `validate_candidate` accepts for a removed protected node (AC-1, AC-2).
4. Move key items to pieces in `split_at` — *why*: the root cause of the NIST failure (AC-3).
5. Add `reconcile_key_items` and call it from `plan_deterministic` — *why*: a fail-soft net for
   any remaining drift (AC-5).
6. Write the tests, then run the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` (MODIFY — report)
```python
# occurrences: 1 (verified: grep -c '    rejected_proposals: int = 0' optimizer.py)
# AFTER — insert below `    rejected_proposals: int = 0` (verified: optimizer.py:113)
    key_items_rehomed: int = 0
```

### `optimizer.py` (MODIFY — `_absorb`)
```python
# occurrences: 1 (verified: grep -c '    _record_merge(absorbed, absorber, reason, report)' optimizer.py)
# BEFORE — insert above `    _record_merge(absorbed, absorber, reason, report)` (verified: optimizer.py:306)
    if ranges and absorber.get("span"):
        # Keep the absorbed ranges with the absorber: assign_ownership rebuilds a leaf's owned from its span.
        absorber["span"] = [
            min(int(absorber["span"][0]), min(int(start) for start, _ in ranges)),
            max(int(absorber["span"][1]), max(int(end) for _, end in ranges)),
        ]
```
**Why**: `ranges` is already bound to `absorbed.get("owned") or []` a few lines above
(`optimizer.py:297`). Use the owned extent, not the absorbed `span`, because the test fixture has
leaves whose span differs from their owned ranges (`"Separate"`, span `[8, 9]`, owned `[[4, 5]]`).

### `optimizer.py` (MODIFY — `normalize`)
```python
# occurrences: 1 each (verified: grep -c for each anchor below)
# REPLACE the signature (verified: optimizer.py:309-311):
def normalize(
    parent_children: list[dict],
    revision: DocumentRevision,
    settings: OptimizerSettings,
    report: OptimizeReport,
    *,
    parent: Optional[dict] = None,
) -> None:
    """<docstring from the spec skeleton, Module 1>."""
# REPLACE `            normalize(child.get("nodes") or [], revision, settings, report)` (optimizer.py:315):
            normalize(child.get("nodes") or [], revision, settings, report, parent=child)
# REPLACE the body of `        if not node.get("nodes") and not (node.get("owned") or []):` (optimizer.py:323-325):
        if not node.get("nodes") and not (node.get("owned") or []):
            if node.get("node_id") is not None and not node.get("concept_id"):
                index += 1  # published without identity: removing it could never pass validate_candidate
                continue
            if parent is not None:
                _absorb(parent, node, "empty", report, revision)
            parent_children.pop(index)
            continue
```

### `optimizer.py` (MODIFY — `split_at`)
```python
# occurrences: 1 (verified: grep -c '    node\["nodes"\] = pieces' optimizer.py)
# AFTER — insert below the `    assign_ownership(node)` line that follows `    node["nodes"] = pieces` (optimizer.py:474-475)
    _move_key_items_to_pieces(node, pieces, report)


def _move_key_items_to_pieces(node: dict, pieces: list[dict], report: OptimizeReport) -> None:
    """Move key items of a just-split node onto the piece whose owned ranges now hold their anchor."""
    # FILL IN: for each item in node["key_items"] whose seq is outside node["owned"] and inside exactly one
    #   piece's owned ranges, append it to that piece's key_items (skip a duplicate (label, seq)) and count
    #   report.key_items_rehomed; keep every other item on node — bounded by AC-3
```
**Why**: define the helper at module level, just above `split_at`, not nested inside it.
`assign_ownership(node)` (line 475) has already shrunk `node["owned"]` to the residual, so
anchor membership is checked against the final ranges.

### `optimizer.py` (MODIFY — new `reconcile_key_items` + `plan_deterministic` wiring)
```python
# Place reconcile_key_items just above `def plan_deterministic(` (verified: optimizer.py:600)
def reconcile_key_items(root: dict, revision: DocumentRevision, mutable: set[int], report: OptimizeReport) -> None:
    """<docstring from the spec skeleton, Module 1>."""
    nodes = _document_nodes(root, revision.doc_id, revision.revision)
    # FILL IN: build owner lookup seq -> node over `nodes` (owned ranges are disjoint after validation;
    #   take the first owner); for each node in nodes with id(node) in mutable, split its key_items into
    #   kept / misplaced; move a misplaced item to a mutable owner (dedupe (label, seq), count
    #   key_items_rehomed) or drop it (count rejected_proposals); write back node["key_items"] — bounded by AC-5

# REPLACE `        normalize(root.get("nodes") or [], revision, settings, report)` (optimizer.py:618):
        normalize(root.get("nodes") or [], revision, settings, report, parent=root)
# AFTER — insert below `    plan.optimizable_roots = roots` (optimizer.py:635)
    for root in roots:
        reconcile_key_items(root, revisions[(root["doc_id"], root["revision"])], plan.mutable, report)
```
**Why**: the call runs after `mark_mutable` (lines 623–634) so `plan.mutable` is populated.
Keep `node["key_items"]` absent rather than `[]` when a node had none, so `pass_input` digests of
untouched nodes stay stable.

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_validate_candidate(revision: DocumentRevision) -> None:' test_optimizer.py)
# APPEND at the end of the file (after test_refresh_after_counts_tracks_candidate_changes, line 224)
def test_normalize_absorbs_empty_leaf_into_parent(revision: DocumentRevision) -> None: ...      # FILL IN
def test_normalize_keeps_published_empty_leaf_without_concept_id(revision: DocumentRevision) -> None: ...  # FILL IN
def test_validate_accepts_preface_shaped_tree(revision: DocumentRevision) -> None: ...         # FILL IN
def test_absorb_widens_span_and_keeps_title_anchor(revision: DocumentRevision) -> None: ...    # FILL IN
def test_split_moves_key_items_to_pieces(revision: DocumentRevision) -> None: ...              # FILL IN
def test_reconcile_rehomes_or_drops(revision: DocumentRevision) -> None: ...                   # FILL IN
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def _tree_with_document(tmp_path: Path, name: str = "guide") -> PageIndexToolkit:' test_optimizer_toolkit.py)
# APPEND at the end of the file
@pytest.mark.asyncio
async def test_optimize_apply_with_empty_leaf(tmp_path: Path) -> None:
    """A published tree with an empty first leaf re-optimizes; the leaf survives as a parent alias."""
    toolkit = await _tree_with_document(tmp_path)
    tree = toolkit._store.load("guide")
    root = tree["structure"][0]
    # FILL IN: insert {"title": "Preface", "concept_id": "guide/preface", "node_id": <unused id>,
    #   "doc_id": root["doc_id"], "revision": root["revision"], "span": [root["span"][0], root["span"][0]],
    #   "owned": [], "nodes": []} as root["nodes"][0]; toolkit._store.save("guide", tree);
    #   report = await toolkit.optimize("guide", apply=True, llm_passes=False);
    #   assert report["errors"] == [] and "guide/preface" in the published root's aliases — bounded by AC-1
```

### FILL IN checklist
- [ ] `_move_key_items_to_pieces` — move rule and duplicate skip; AC-3
- [ ] `reconcile_key_items` — owner lookup, move/drop, counters, never touch non-mutable nodes; AC-5
- [ ] six unit tests + one toolkit test — the assertions listed in spec §4 for M1; AC-1…AC-5
- [ ] If `_store.save` bypasses generation bookkeeping so that `optimize(apply=True)` cannot run,
  build the tree through the same path `test_locked_semantics` uses for edits, and record that in
  the Completion Note.

---

## Acceptance Criteria

- [ ] AC-1: the toolkit apply on a tree with an empty leaf (with `node_id` and `concept_id`)
  returns `errors == []`; the parent carries the alias; a `reason == "empty"` merge is reported.
- [ ] AC-2: the legacy `normalize` call without `parent` is unchanged
  (`test_normalize_duplicates_empty_and_tiny` passes as is); a published empty leaf without a
  `concept_id` is kept.
- [ ] AC-3: after `split_at` / `expand_at_headings` on a leaf with key items, every item lies in
  its node's `owned`; `validate_candidate` has no `key_item anchor` error.
- [ ] AC-4: after an `under_minimum` merge plus `assign_ownership`, the absorbed title key item
  lies inside the absorber's `owned`.
- [ ] AC-5: `reconcile_key_items` moves (`key_items_rehomed`) or drops (`rejected_proposals`) and
  never modifies a non-mutable node.
- [ ] `ruff check` and `black --check` are clean on the three files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_integration.py -q`

---

## Test Specification

```python
# test_optimizer.py — uses the module's `revision` fixture: segments of
# "# Parent\n\nlead\n\n# First\n\nsmall\n\n# Second\n\ntail" (5 segments, seq 0..4).
def test_validate_accepts_preface_shaped_tree(revision):
    root = {"node_id": "0000", "concept_id": "doc", "title": "Doc", "doc_id": "doc", "revision": revision.revision,
            "span": [0, 5], "owned": [[0, 5]], "nodes": [
                {"node_id": "0001", "concept_id": "doc/preface", "title": "Preface", "doc_id": "doc",
                 "revision": revision.revision, "span": [0, 0], "owned": [], "nodes": []}]}
    base = {"nodes": [root]}
    plan = plan_deterministic(base, {("doc", revision.revision): revision}, OptimizerSettings(), tree_name="t")
    errors = validate_candidate(plan, {("doc", revision.revision): revision}, base_tree=base)
    assert not any("was removed" in e for e in errors)
    assert "doc/preface" in plan.candidate["nodes"][0]["aliases"]
```

---

## Agent Instructions

1. Work in the feature worktree
   (`parrot sdd worktree ensure --slug pageindex-optimizer-fixes --feature-id FEAT-853`).
2. Read the spec; verify this Codebase Contract (`grep -c` every anchor) before writing code.
3. Mark `in-progress` in `sdd/tasks/index/pageindex-optimizer-fixes.json` and commit only that file.
4. Implement from the blueprint, complete every `FILL IN`, and run the Validation Commands with
   `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
5. Commit only the three files; close with
   `parrot sdd task close TASK-5391 pageindex-optimizer-fixes verified`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
