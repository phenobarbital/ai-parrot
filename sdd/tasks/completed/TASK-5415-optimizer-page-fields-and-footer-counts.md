# TASK-5415: Optimizer piece page fields and footer-safe pseudo-heading repeat counts

**Feature**: FEAT-857 — PageIndex Optimizer Fixes 2 — Page Fields and Footer-Safe Pseudo-Headings
**Spec**: `sdd/specs/pageindex-optimizer-fixes-2.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:5396799daf67`
**Discovered-from**: `issue:38e4627b2284`

---

## Context

Spec §3 Module 1. `split_at` creates optimizer children without `start_index` / `end_index`, which breaks
`test_fixture_import_is_hybrid_and_anchored` on `dev` (`issue:5396799daf67`). `pseudo_heading_segments` counts
repeats by exact casefolded title, so numbered running footers (`CHAPTER THREE PAGE 19`) pass as headings
(`issue:38e4627b2284`). Both edits are in `optimizer.py`.

---

## Scope

- Add `_piece_pages(piece, revision)` and call it in `split_at` after `assign_ownership(node)`, setting
  `start_index` / `end_index` on every piece whose owned segments carry a `page`; unpaged pieces get neither key.
- Key `pseudo_heading_segments`' repeat counts (build and lookup) with `running_key(heading_title(...))`.
- Add three unit tests.

**NOT in scope**: `layout.py`, `layout_structure.py`, `OptimizerSettings`, `OPTIMIZER_VERSION`, the docs page
(TASK-5416), changing the piece titles or the cost model.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `_piece_pages`, `split_at` page fields, `running_key` counts |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` | MODIFY | three new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.layout import running_key  # verified: layout.py:97 (layout imports only utils + segments: no cycle)
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment, segment_pages  # verified: segments.py:231; optimizer.py:15-17 already import the first two
from typing import Optional  # verified: optimizer.py:9
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py
def _owned_in_span(owned: list[list[int]], start: int, end: int) -> list[list[int]]   # :585
def split_at(node, revision, seqs, *, source, settings, report) -> list[dict]           # :645
    #   :688 assign_ownership(node) ; :689 _move_key_items_to_pieces(node, pieces, report)
def pseudo_heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]    # :485
    #   :509 key = heading_title(segment.text).casefold() ; :519 if counts.get(title.casefold(), 0) > PSEUDO_HEADING_MAX_REPEATS:
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment: page: Optional[int]   # :77 ; segment_pages(pages: list[tuple[int, str]]) -> list[Segment]  # :231
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
def running_key(text: str) -> str    # :97 casefold, collapse whitespace, digit runs -> '#'
# tests: test_optimizer.py
_PROSE (:400), _markdown_tree(text, title="Libro") -> (tree, revisions) (:403), autouse _stub_tokens (:28)
```

### Does NOT Exist
- ~~`start_index`/`end_index` handling anywhere in `optimizer.py`~~ — none today.
- ~~a `page` attribute on markdown segments~~ — unpaged revisions have `page is None`.
- ~~`running_key` in `segments.py` or `layout_structure.py`~~ — only `layout.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#split_at",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#pseudo_heading_segments"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Set the page fields **after** `assign_ownership(node)` — because ownership can change a piece's `owned`.
- `end_index` is the page of the last owned segment (never below `start_index`) — an optimizer piece owns exactly
  those pages; do not apply FEAT-856's "next item minus 1" rule.
- Do not change any other behaviour; `PSEUDO_HEADING_MAX_REPEATS` stays 2.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `running_key` import — because the repeat counts need it.
2. Add `_piece_pages` above `split_at` — because `split_at` is its only caller.
3. Set the page fields in `split_at` — because stored trees expect them on paged documents.
4. Re-key the counts in `pseudo_heading_segments` — because footers differ only by digits.
5. Write the tests, run the validation commands.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title' optimizer.py)
# AFTER — insert below `from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title` (verified: optimizer.py:14)
from parrot.knowledge.pageindex.layout import running_key

# occurrences: 1 (verified: grep -c '^def split_at(' optimizer.py)
# BEFORE — insert above `def split_at(` (verified: optimizer.py:645)
def _piece_pages(piece: dict, revision: DocumentRevision) -> Optional[tuple[int, int]]:
    """Return the first and last page of a piece's owned segments, or ``None`` when none is paged."""
    pages = [
        segment.page
        for start, end in piece.get("owned") or []
        for segment in revision.segments[max(int(start), 0) : min(int(end), len(revision.segments))]
        if segment.page is not None
    ]
    return (min(pages), max(pages)) if pages else None

# occurrences: 1 (verified: grep -c -F '    _move_key_items_to_pieces(node, pieces, report)' optimizer.py; the preceding line `    assign_ownership(node)` occurs 2x in the file, so quote both lines)
# AFTER — insert between `    assign_ownership(node)` and `    _move_key_items_to_pieces(node, pieces, report)` (verified: optimizer.py:688-689)
    for piece in pieces:
        pages = _piece_pages(piece, revision)
        if pages is not None:
            piece["start_index"], piece["end_index"] = pages

# occurrences: 1 (verified: grep -c -F 'key = heading_title(segment.text).casefold()' optimizer.py)
# REPLACE `key = heading_title(segment.text).casefold()` (verified: optimizer.py:509) WITH
        key = running_key(heading_title(segment.text))

# occurrences: 1 (verified: grep -c -F 'counts.get(title.casefold(), 0) > PSEUDO_HEADING_MAX_REPEATS' optimizer.py)
# REPLACE `if counts.get(title.casefold(), 0) > PSEUDO_HEADING_MAX_REPEATS:` (verified: optimizer.py:519) WITH
        if counts.get(running_key(title), 0) > PSEUDO_HEADING_MAX_REPEATS:
```
**Why**: the helper reads pages from owned segments, so it reflects the final ownership; `running_key` collapses the
digit runs that make each page's footer unique, so `CHAPTER THREE PAGE 19/21/22` count as one title.

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` (MODIFY)
```python
# AFTER — append at the end of the file (after test_coalesce... tests; anchor: the last function in the file)
def test_split_at_sets_page_fields() -> None:
    """Pieces of a paged revision carry start_index/end_index from their owned segments' pages."""
    # FILL IN: build segments with segment_pages([(1, f"# Alpha\n\n{_PROSE}"), (2, f"{_PROSE}\n\n# Beta\n\n{_PROSE}"),
    #   (3, _PROSE)]), wrap in a DocumentRevision exactly as _markdown_tree does, make a one-leaf tree, run
    #   plan_deterministic with OptimizerSettings(target_leaf_tokens=100, min_leaf_tokens=20), and assert
    #   (start_index, end_index) of the two pieces — bounded by AC-1.

def test_split_at_unpaged_has_no_page_fields() -> None:
    """Pieces of a markdown (unpaged) revision carry neither key."""
    # FILL IN: reuse _markdown_tree with two `#` headings; assert "start_index" / "end_index" not in each piece.

def test_pseudo_headings_drop_numbered_footers() -> None:
    """One footer per page differing only by its number is not a pseudo-heading; a real bold title is."""
    # FILL IN: _markdown_tree text = for n in (19, 21, 22, 23): f"CHAPTER THREE PAGE {n}\n\n{_PROSE}\n\n" then
    #   "**Real Title**\n\n{_PROSE}"; assert titles of pseudo_heading_segments == ["Real Title"] — bounded by AC-4.
```

### FILL IN checklist
- [ ] the three test bodies (concrete page numbers asserted from the fixture you build)

---

## Acceptance Criteria

- [ ] Pieces of a paged revision carry `start_index <= end_index` from their owned segments' pages.
- [ ] Pieces of an unpaged revision carry no page keys.
- [ ] `test_fixture_import_is_hybrid_and_anchored` passes.
- [ ] Numbered footers are not pseudo-headings once repeated more than `PSEUDO_HEADING_MAX_REPEATS` times.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` is clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py::test_fixture_import_is_hybrid_and_anchored -q`

---

## Test Specification

See the blueprint stubs; names are fixed by the spec §4.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch` (`parrot sdd worktree ensure --slug pageindex-optimizer-fixes-2 --feature-id FEAT-857`)
2. **Read the spec** at the path listed above
3. **Verify the Codebase Contract** before writing anything
4. **Update status** in `sdd/tasks/index/pageindex-optimizer-fixes-2.json` → `"in-progress"`; commit only that file
5. **Implement**, completing every `FILL IN`
6. **Verify** acceptance criteria with `PYTHONPATH=packages/ai-parrot/src`
7. **Commit** only the files this task lists
8. **Close** with `parrot sdd task close TASK-5415 pageindex-optimizer-fixes-2 verified`
9. Fill in the Completion Note, commit the SDD state

---

## Completion Note

**Completed by**: sdd-fix session (Claude)
**Date**: 2026-11-09
**Notes**: `_piece_pages` + page fields in `split_at`; `running_key` repeat counts in `pseudo_heading_segments`; three tests added. `test_optimizer.py` + `test_layout_integration.py` (31) and the other optimizer test files (41) pass; ruff clean.

**Deviations from spec**: none
