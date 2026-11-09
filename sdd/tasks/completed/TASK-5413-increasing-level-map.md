# TASK-5413: Strictly increasing hybrid level-to-depth map

**Feature**: FEAT-856 — PageIndex Layout Fixes — Enumerated Enhancement Headings
**Spec**: `sdd/specs/pageindex-layout-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:92245af971f3`

---

## Context

Spec §1 fact 4 and §3 Module 2. The hybrid rule maps each markdown heading level to the most common depth of the
bookmarks anchored at that level (`_level_to_depth`) and places every unanchored heading by that map
(`_placed_depth`). In NIST 800-53 one control typeset at 10 pt (`PL-10 BASELINE SELECTION`, level 6, depth 3) maps
level 6 to the controls' depth, so every inserted level-6 heading — the 867 enhancements TASK-5412 adds — lands beside
its control instead of under it. The raw map is `{1: 1, 2: 1, 3: 2, 5: 3, 6: 3}`. Keeping the map strictly increasing
(`{1: 1, 3: 2, 5: 3}`) nests them at depth 4; arxiv (`{3: 1}`) and CSF 2.0 (`{3: 1, 4: 2}`) are already increasing and
their trees were measured identical with the prototype.

---

## Scope

- Make `_level_to_depth` drop every level whose majority depth is not greater than the depth kept for the nearest
  shallower level.
- Tests in `test_layout_structure.py`.

**NOT in scope**: `_placed_depth` and `insert_layout_headings` (unchanged — a dropped level already falls back to
`depth(M) + (L − M)`); anchored bookmark items (they keep their bookmark depth); `layout.py` (TASK-5412);
`score_layout`, `items_to_tree`, the choice order.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` | MODIFY | `_level_to_depth` keeps an increasing map |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` | MODIFY | new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# layout_structure.py — nothing new to import
from collections import Counter                                    # verified: layout_structure.py:11
from typing import Literal, Optional, Sequence                     # verified: layout_structure.py:13
# test_layout_structure.py — extend the second import block (verified: test_layout_structure.py:147-151) with
#   _level_to_depth
from parrot.knowledge.pageindex.layout_structure import build_structure, insert_layout_headings, items_to_tree
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py
def _level_to_depth(anchored: Sequence[dict]) -> dict[int, int]:          # line 212
    """Map heading levels to their most common anchored bookmark depths."""
    counts: dict[int, Counter] = {}
    for item in anchored:
        counts.setdefault(int(item["level"]), Counter())[int(item["depth"])] += 1
    return {level: min(count, key=lambda depth: (-count[depth], depth)) for level, count in counts.items()}   # 218
def _placed_depth(level: Optional[int], mapping: dict[int, int]) -> Optional[int]   # line 220 — unchanged
def insert_layout_headings(bookmark_items, profile, segments) -> tuple[list[dict], int]   # line 239;
    # `mapping = _level_to_depth(anchored)` at line 246
def score_bookmarks(profile, segments) -> tuple[CandidateScore, list[dict]]   # line 97

# test_layout_structure.py helpers: _segs(*pages) (17), _profile(page_count, bookmarks=..., ...) (22),
#   HYBRID_PAGES (153), test_hybrid_insertion (159) — the pattern to mirror
```

### Does NOT Exist
- ~~a minimum anchor count per level~~, ~~a context-relative placement for inserted headings~~ — rejected in the spec's
  Decisions block; do not add either.
- ~~`StructureReport.level_map`~~ — the map is only logged at DEBUG (`hybrid: mapping=%s`), as today.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#_level_to_depth",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#_placed_depth",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#insert_layout_headings",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#score_bookmarks"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep today's majority vote (ties to the shallower depth) exactly; the new step only removes entries.
- Visit levels in ascending order; compare with the depth **kept** for the nearest shallower level (not the raw one).
- An empty `anchored` returns `{}` (today's behaviour; `test_hybrid_confidence_and_empty_mapping` relies on it).

---

## Implementation Blueprint

### Steps (in order)
1. Replace `_level_to_depth`'s body — *why*: one stray anchor must not flatten a whole level.
2. Write the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _level_to_depth(anchored: Sequence\[dict\]) -> dict\[int, int\]:' layout_structure.py)
# REPLACE the function (verified: layout_structure.py:212-217) with:
def _level_to_depth(anchored: Sequence[dict]) -> dict[int, int]:
    """Map heading levels to their most common anchored bookmark depths, strictly increasing with the level.

    The majority vote picks, per level, the most common depth (ties to the shallower one). Levels are then visited
    in ascending order and kept only when their depth is greater than the depth kept for the nearest shallower
    level; ``_placed_depth`` places the headings of a dropped level from the nearest shallower mapped level.

    Args:
        anchored: Bookmark items anchored to a heading segment, each with ``level`` and ``depth``.

    Returns:
        The level-to-depth map, strictly increasing in depth.
    """
    counts: dict[int, Counter] = {}
    for item in anchored:
        counts.setdefault(int(item["level"]), Counter())[int(item["depth"])] += 1
    majority = {level: min(count, key=lambda depth: (-count[depth], depth)) for level, count in counts.items()}
    mapping: dict[int, int] = {}
    # FILL IN: for level in sorted(majority): keep it (mapping[level] = majority[level]) unless mapping is non-empty
    #   and majority[level] <= mapping[max(mapping)] (the nearest shallower kept level, since levels ascend)
    #   — bounded by spec §3 M2 and the decision hybrid-level-map-strictly-increasing
    return mapping
```
**Why**: levels are visited in ascending order, so the last kept level is the nearest shallower one; comparing with
the kept depth makes the result increasing even when several levels in a row are dropped.

### FILL IN checklist
- [ ] the keep/drop walk
- [ ] tests below — bodies

---

## Acceptance Criteria

- [ ] `_level_to_depth` on items `{5: 3}` ×3 + `{6: 3}` → `{5: 3}`; `{3: 1}`, `{4: 2}` → `{3: 1, 4: 2}`; `{2: 2}`, `{3: 1}`
      → `{2: 2}`; `{1: 1}`, `{2: 1}`, `{3: 2}`, `{5: 3}`, `{6: 3}` → `{1: 1, 3: 2, 5: 3}`; `[]` → `{}`.
- [ ] Hybrid insertion with two `##` bookmarked controls and one bookmarked `###` outlier on the same depth: the
      unanchored `###` headings land at depth 2 (children of the controls); the anchored `###` item keeps depth 1.
- [ ] Existing `test_layout_structure.py` tests pass unchanged; `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py -q`

---

## Test Specification

```python
# test_layout_structure.py — reuse _segs, _profile
def test_level_to_depth_strictly_increasing():
    # FILL IN: the five cases of the first acceptance criterion, items as {"level": L, "depth": D}
    ...


def test_hybrid_nests_headings_below_stray_anchor():
    # FILL IN: pages ("## AC-1 Control\n\nText.\n\n### (1) AC ONE | FIRST\n\nText.",
    #   "## AC-2 Control\n\nText.\n\n### PL-10 Odd\n\nText.\n\n### (1) AC TWO | SECOND\n\nText.");
    #   bookmarks (1, "AC-1 Control", 1), (1, "AC-2 Control", 2), (1, "PL-10 Odd", 2);
    #   insert_layout_headings → AC-1 depth 1, (1) AC ONE | FIRST depth 2, AC-2 depth 1, PL-10 Odd depth 1,
    #   (1) AC TWO | SECOND depth 2
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-fixes --feature-id FEAT-856`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5413 pageindex-layout-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude (Opus 5.5) — /sdd-fix session agent:sdd-fix:087cd628
**Date**: 2026-11-09
**Notes**: `_level_to_depth` keeps today's majority vote, then walks levels in ascending order and keeps a level only
when its depth is greater than the last kept level's depth. Tests: `test_level_to_depth_strictly_increasing` (the five
cases of the acceptance criteria, including the 800-53 map `{1: 1, 2: 1, 3: 2, 5: 3, 6: 3}` → `{1: 1, 3: 2, 5: 3}`)
and `test_hybrid_nests_headings_below_stray_anchor` (unanchored `###` headings at depth 2, the anchored `PL-10 Odd`
keeps depth 1). Both new tests fail against the baseline tree of origin/dev (4ace6b6d11) and pass here.
Validation: test_layout_structure.py + test_builder_layout.py 25 passed; ruff clean.

**Deviations from spec**: none
