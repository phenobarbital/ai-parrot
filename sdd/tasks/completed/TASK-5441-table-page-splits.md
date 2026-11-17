# TASK-5441: Page splits for long table leaves

**Feature**: FEAT-861 — PageIndex Optimizer Fixes 4 — Page Splits for Long Table Leaves
**Spec**: `sdd/specs/pageindex-optimizer-fixes-4.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:f31b01d845b0`

---

## Context

Spec §3 Module 1. `expand_at_headings` (`optimizer.py:752`) splits an oversized leaf at heading segments, else at
pseudo-heading paragraphs. A leaf that is one long table has neither, so NIST 800-53's seven `TABLE C-*` leaves
(1,545–3,864 tokens) and AICPA's 27,651-token table leaf stay whole (`issue:f31b01d845b0`, spec §1 evidence table).
This task adds a third fallback: split a table-dominated, multi-page leaf at page boundaries, packed from the last page
backward, with page-range titles (spec §2 Overview A–C).

---

## Scope

- Add `TABLE_SPLIT_MIN_SHARE = 0.5` and `table_page_splits(node, revision, settings) -> dict[int, str]`.
- `split_at(..., titles: Optional[dict[int, str]] = None)`: a piece whose start sequence is in `titles` takes that
  title; otherwise the title comes from the segment text, as today.
- `expand_at_headings`: when the pseudo-heading fallback gives no split point, use `table_page_splits` (points and
  titles).
- Five unit tests (names fixed by spec §4).

**NOT in scope**: `optimizer_llm.py` (its `split_at(..., source="llm")` call stays as is), `layout.py`,
`layout_structure.py`, `segments.py`, `OptimizerSettings`, `ExpandAction` (the table split records `source="layout"`),
`_coalesce_split_points`, `OPTIMIZER_VERSION`, row-level splits, prose leaves, the wiki pages and the host evaluation
(TASK-5442).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | constant, `table_page_splits`, `split_at(titles=)`, third fallback |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` | MODIFY | five new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Any, Literal, Optional  # verified: optimizer.py:9 (Optional already imported)
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title  # verified: optimizer.py:15
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment  # verified: optimizer.py:16-24
# tests
from parrot.knowledge.pageindex.segments import segment_pages  # verified: segments.py:231 (imported inside _paged_tree, test_optimizer.py:501)
from parrot.knowledge.pageindex.optimizer import plan_deterministic, OptimizerSettings, OptimizeReport, validate_candidate  # verified: test_optimizer.py:5-22
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py
RUNNING_LINE_MIN_DENSITY = 0.8  # :31
class ExpandAction(BaseModel): parent_title: str; parent_concept_id; pieces: list[str]; source: Literal["layout", "llm"]  # :92-98
def owned_tokens(node: dict, revision: DocumentRevision) -> int  # :164
def pseudo_heading_segments(node, revision, *, running_keys=None) -> list[Segment]  # :515
def _coalesce_split_points(node: dict, revision, seqs: list[int], settings) -> list[int]  # :565 — drops points that leave a piece < min_leaf_tokens
def _owned_in_span(owned: list[list[int]], start: int, end: int) -> list[list[int]]  # :621
def _piece_pages(piece: dict, revision: DocumentRevision) -> Optional[tuple[int, int]]  # :681-689 — (min, max) page of owned segments or None
def split_at(node, revision, seqs, *, source: str, settings, report) -> list[dict]  # :692-749
    #   :725 "title": heading_title(revision.segments[seq].text),  — the only title assignment
def expand_at_headings(node, revision, settings, report, *, depth, running_keys=None) -> None  # :752-796
    #   :761-768 docstring ; :779 if owned_tokens(node, revision) <= settings.target_leaf_tokens: return ; :781 headings = [
    #   :789-793 else: candidates = pseudo_heading_segments(...); seqs = _coalesce_split_points(...); if not seqs: return
    #   :794 pieces = split_at(node, revision, seqs, source="layout", settings=settings, report=report)
def plan_deterministic(tree, revisions, settings, *, tree_name, node_id=None) -> OptimizePlan  # :920
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel): seq: int; kind: SegmentKind; page: Optional[int] = None; text: str; tokens: int  # :33-43
def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]  # :231 — a run of lines starting with "|" is ONE table segment (:195-201)
# packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py
_stub_tokens (autouse, :28: count_tokens = len(text) // 4) ; _PROSE (:400, ~712 tokens)
def _markdown_tree(text: str, title: str = "Libro") -> tuple[dict, dict]  # :403 (unpaged, one leaf)
def _paged_tree(pages: list[tuple[int, str]], title: str = "Libro") -> tuple[dict, dict]  # :499 (one leaf, doc_id "libro")
def test_expand_computes_running_keys_once(monkeypatch) -> None  # :671 (last function; file ends at :694)
```

### Does NOT Exist
- ~~`split_at(..., titles=...)`~~, ~~`table_page_splits`~~, ~~`TABLE_SPLIT_MIN_SHARE`~~ — created by this task.
- ~~any page-based split in `optimizer.py`~~ — every split today is at a heading or pseudo-heading segment.
- ~~`ExpandAction.source == "table"`~~ — not added; the table split records `"layout"`.
- ~~other callers of `split_at`~~ — only `optimizer.py:794` and `optimizer_llm.py:565` (leave the latter untouched).

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
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#expand_at_headings",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#_coalesce_split_points",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#plan_deterministic"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Order of fallbacks: headings, then pseudo-headings, then page splits — only when the pseudo-heading path yields no
  split point.
- `split_at` without `titles` must behave exactly as before (heading splits, pseudo-heading splits, the LLM pass).
- The first split point is the leaf's first `table` segment, not its first segment, so the title paragraph and any
  lead-in prose stay with the parent.
- Pack **backward** (from the last page block): forward packing left 800-53's 43-token trailing stub to push
  `TABLE C-1`'s last piece to 1,509 tokens and to veto `TABLE C-5`'s split (spec §2).
- Page numbers are `Segment.page` (PDF page index), the same values as `start_index` / `end_index`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the constant below `RUNNING_LINE_MIN_DENSITY` — because the helper and the docs name it.
2. Add `table_page_splits` directly after `_piece_pages` — because it uses `_piece_pages`, `_owned_in_span` and
   `_coalesce_split_points`, all defined above that point.
3. Add `titles` to `split_at` — because the page pieces need titles their first segment cannot provide.
4. Add the third fallback in `expand_at_headings`.
5. Write the five tests; run the validation commands; `ruff check` and `black` the two files.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'RUNNING_LINE_MIN_DENSITY = 0.8' optimizer.py)
# AFTER — insert below `RUNNING_LINE_MIN_DENSITY = 0.8` (verified: optimizer.py:31)
TABLE_SPLIT_MIN_SHARE = 0.5
"""Share of a leaf's owned tokens that must be ``table`` segments before it may be split at page boundaries."""

# occurrences: 1 (verified: grep -cF 'def _piece_pages(piece: dict, revision: DocumentRevision) -> Optional[tuple[int, int]]:' optimizer.py)
# AFTER — insert below the whole `_piece_pages` function (:681-689), above `def split_at(` (:692)
def table_page_splits(node: dict, revision: DocumentRevision, settings: OptimizerSettings) -> dict[int, str]:
    """Return page-boundary split points for a long table leaf, mapped to their piece titles.

    Applies only when ``table`` segments hold at least ``TABLE_SPLIT_MIN_SHARE`` of the leaf's owned tokens and sit on
    at least two pages. The owned segments from the first ``table`` segment on are grouped into page blocks (a block
    starts where the page changes; an unpaged segment joins the current block) and packed from the last block
    backward: a boundary goes before a block when adding it would exceed ``settings.target_leaf_tokens``. The points
    (the first ``table`` segment plus those boundaries) then pass through ``_coalesce_split_points``. Each piece is
    titled after the leaf plus ``(page N)`` / ``(pages N-M)``.

    Args:
        node: The oversized leaf.
        revision: The document revision the node is anchored to.
        settings: Optimizer settings (``target_leaf_tokens``, ``min_leaf_tokens``).

    Returns:
        The split sequences mapped to piece titles, in order; ``{}`` when the rule does not apply or fewer than two
        points remain.
    """
    owned = list(node.get("owned") or [])
    segments = [
        segment
        for start, end in owned
        for segment in revision.segments[max(int(start), 0) : min(int(end), len(revision.segments))]
    ]
    # FILL IN: eligibility — return {} unless sum(table tokens) >= TABLE_SPLIT_MIN_SHARE * sum(all tokens) (and the
    #   total is non-zero) and the table segments' non-None pages are at least 2 distinct values — bounded by AC-1.
    # FILL IN: page blocks — starts = [seq of first table segment]; walk segments from that one: a segment whose page
    #   is not None and differs from the last seen non-None page opens a new block; accumulate segment.tokens per block.
    # FILL IN: backward packing — iterate blocks from last to first with a running total; when the total is non-zero
    #   and total + block > settings.target_leaf_tokens, record the start of the block AFTER it as a boundary and reset;
    #   points = [starts[0]] + sorted(boundaries) — bounded by AC-2.
    kept = _coalesce_split_points(node, revision, points, settings)
    if len(kept) < 2:
        return {}
    final_end = max(int(end) for _, end in owned)
    title = str(node.get("title") or "").strip()
    titles: dict[int, str] = {}
    for index, seq in enumerate(kept):
        end = kept[index + 1] if index + 1 < len(kept) else final_end
        pages = _piece_pages({"owned": _owned_in_span(owned, seq, end)}, revision)
        # FILL IN: suffix = f"(page {a})" when a == b, f"(pages {a}-{b})" otherwise, f"(part {index + 1})" when pages
        #   is None; titles[seq] = f"{title} {suffix}".strip() — bounded by AC-3 (ASCII hyphen, unique per piece).
    return titles

# occurrences: 1 (verified: grep -cF 'def split_at(' optimizer.py) — signature :692-700
# ADD after `    report: OptimizeReport,` inside the split_at signature:
    titles: Optional[dict[int, str]] = None,
# FILL IN: docstring (:701) — add one sentence: a piece whose start sequence is in ``titles`` takes that title.

# occurrences: 1 (verified: grep -cF '                "title": heading_title(revision.segments[seq].text),' optimizer.py)
# REPLACE (:725) WITH
                "title": titles[seq] if titles and seq in titles else heading_title(revision.segments[seq].text),

# occurrences: 1 (verified: grep -cF '        seqs = _coalesce_split_points(node, revision, [segment.seq for segment in candidates], settings)' optimizer.py)
# REPLACE the fallback block (:789-794) so it reads:
    titles: Optional[dict[int, str]] = None
    if headings:
        ...  # unchanged: shallowest level, seqs
    else:
        candidates = pseudo_heading_segments(node, revision, running_keys=running_keys)
        seqs = _coalesce_split_points(node, revision, [segment.seq for segment in candidates], settings)
        if not seqs:
            titles = table_page_splits(node, revision, settings)
            seqs = list(titles)
        if not seqs:
            return
    pieces = split_at(node, revision, seqs, source="layout", settings=settings, report=report, titles=titles)
# FILL IN: docstring (:761-768) — one sentence: a leaf with no heading and no pseudo-heading split point falls back to
#   ``table_page_splits`` (page-range pieces of a long table).
```
**Why**: table pages are the only boundaries a long table offers; packing backward keeps the trailing stub (the next
page's running header) from creating an undersized last piece, and the first table segment as the first point leaves
the leaf's title and lead-in on the parent, as a heading split does (spec §2).

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` (MODIFY)
```python
# AFTER — append at the end of the file (after test_expand_computes_running_keys_once, :671-694)
# --- FEAT-861: page splits for long table leaves -------------------------------------------------------------------


def _table_rows(rows: int, label: str) -> str:
    """Return a markdown table of ``rows`` body rows (one table segment) for page fixtures."""
    # FILL IN: header "| CONTROL | NAME |", separator "|---|---|", then rows lines f"| {label}-{n} | {long text} |";
    #   size each row so a 12-row table is ~200-250 stub tokens (count_tokens = len // 4).


def _table_leaf_pages() -> list[tuple[int, str]]:
    """Pages 1-4: a bold table title then a table on page 1, one table on pages 2-4, and a header-only page 5."""
    # FILL IN: page 1 = "**TABLE C-9: TEST FAMILY**\n\n" + table; pages 2-4 = "RUNNING HEADER LINE\n\n" + table;
    #   page 5 = "RUNNING HEADER LINE" only (the trailing stub).


def test_table_page_splits_packs_pages_backward() -> None:
    # FILL IN: _paged_tree(_table_leaf_pages(), title="TABLE C-9: TEST FAMILY"); settings with a target that fits two
    #   table pages but not three, min below one page; assert keys == [first table seq, ...page starts...], the page-5
    #   stub is inside the last piece (last title ends "(pages 4-5)"), titles are unique — AC-2/AC-3.


def test_table_page_splits_requires_table_share_and_two_pages() -> None:
    # FILL IN: (a) prose pages with one small table → {}; (b) one page holding two tables (arxiv shape) → {};
    #   (c) _markdown_tree with the same tables (unpaged) → {} — AC-1.


def test_split_at_uses_given_titles() -> None:
    # FILL IN: _paged_tree with two "# Heading" pages; split_at(..., titles={seq_of_second: "Named"}) → titles are
    #   [heading text, "Named"]; without titles → both heading texts — AC-4.


def test_expand_splits_long_table_leaf_at_pages() -> None:
    # FILL IN: plan_deterministic over _paged_tree(_table_leaf_pages(), title="TABLE C-9: TEST FAMILY"); the leaf has
    #   children whose titles end with "(page N)"/"(pages N-M)", each owned_tokens <= target, the parent still owns
    #   the bold title paragraph, validate_candidate(...) == [] (fails on dev: the leaf stays whole) — AC-5.


def test_expand_prefers_pseudo_headings_over_table_pages() -> None:
    # FILL IN: same pages with "**Real Section**\n\n" + prose added to page 3; the leaf splits at "Real Section"
    #   and no piece title ends with a page range — AC-5.
```

### FILL IN checklist
- [ ] eligibility, page blocks, backward packing and the title suffix in `table_page_splits`
- [ ] the two docstring sentences (`split_at`, `expand_at_headings`)
- [ ] the two fixture helpers and five test bodies (import `table_page_splits`, `split_at`, `owned_tokens` inside the
      tests as the FEAT-857/859 tests do)

---

## Acceptance Criteria

- [ ] AC-1: `table_page_splits` returns `{}` unless `table` tokens are ≥ `TABLE_SPLIT_MIN_SHARE` of the leaf's owned
      tokens and its `table` segments sit on ≥ 2 pages; an unpaged leaf returns `{}`.
- [ ] AC-2: its points are the first `table` segment plus page starts, packed from the last page backward within
      `target_leaf_tokens`, then coalesced; fewer than two points return `{}`.
- [ ] AC-3: piece titles are the leaf title plus `(page N)` / `(pages N-M)`; no two pieces of one leaf share a title.
- [ ] AC-4: `split_at` without `titles` behaves exactly as before (existing tests pass unchanged).
- [ ] AC-5: `expand_at_headings` uses page splits only when headings and pseudo-headings give no split point;
      `test_expand_splits_long_table_leaf_at_pages` fails on `dev` and passes here.
- [ ] `ruff check` is clean on both files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_integration.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py -q`

---

## Test Specification

Names and intent fixed by spec §4 (Unit Tests table); bodies per the blueprint stubs.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-optimizer-fixes-4 --feature-id FEAT-861`)
2. **Read the spec** at the path listed above
3. **Verify the Codebase Contract** before writing anything
4. **Update status** in `sdd/tasks/index/pageindex-optimizer-fixes-4.json` → `"in-progress"`; commit only that file
5. **Implement**, completing every `FILL IN`
6. **Verify** acceptance criteria with `PYTHONPATH=packages/ai-parrot/src`; prove AC-5 by running the regression test
   against the base commit
7. **Commit** only the files this task lists
8. **Close** with `parrot sdd task close TASK-5441 pageindex-optimizer-fixes-4 verified`
9. Fill in the Completion Note, commit the SDD state

---

## Completion Note

**Completed by**: sdd-fix session (Claude)
**Date**: 2026-11-09
**Notes**: `TABLE_SPLIT_MIN_SHARE`, `table_page_splits` (eligibility: table share + table on >= 2 pages; page blocks
from the first `table` segment; backward packing; `_coalesce_split_points`; page-range titles), `split_at(...,
titles=None)`, and the third fallback in `expand_at_headings`. Five tests added. Validation commands:
`test_optimizer.py` + `test_optimizer_integration.py` + `test_layout_integration.py` 48 passed; ruff + black clean.
AC-5 proven by running a copy of the test file outside the repo against `origin/dev` @ `f245375ced` (pageindex source
identical to the base `ae583b386c`): `test_expand_splits_long_table_leaf_at_pages` fails there with `assert 0 == 3`
(the leaf stays whole); the three tests of the new API fail with ImportError/TypeError; the pseudo-heading guard
passes on both. Code commit `90442976dc`.

**Deviations from spec**: none. The test fixture targets "pages 2+3" so backward packing gives `(page 1)`,
`(pages 2-3)`, `(pages 4-5)` while forward packing would leave a last piece over the target.
