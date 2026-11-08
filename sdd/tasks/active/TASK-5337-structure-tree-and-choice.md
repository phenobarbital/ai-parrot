# TASK-5337: Hybrid insertion, tree builder and choice (M3b)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5336
**Assigned-to**: unassigned

---

## Context

Spec §2 ("Choice", "Hybrid rule", "Tree and pages", "Anchors") and §3 Module 3, revision 0.2.
TASK-5336 created `layout_structure.py` with the report models and the two candidate scores. This task
appends the three functions that turn scored items into a PageIndex tree and pick the winner:
`insert_layout_headings` (hybrid rule), `items_to_tree` (stack-built tree with the LLM path's page
conventions and `Preface`) and `build_structure` (the choice). The builder (TASK-5340) calls only
`build_structure` and `page_structure`.

Revision 0.2 changed the choice: hybrid insertion runs **only when both candidates reach
`min_confidence`**; hybrid confidence is the **minimum** of the two; a bookmark-only result keeps the
bookmark confidence; with no anchored bookmarks there is no level mapping, so nothing is inserted
(AC-21).

---

## Scope

- Append to `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py`, below `page_structure`:
  - `insert_layout_headings(bookmark_items, profile, segments) -> tuple[list[dict], int]` (spec §2 "Hybrid rule");
  - `items_to_tree(items, segments, profile) -> list[dict]` (spec §2 "Tree and pages");
  - `build_structure(profile, segments, *, mode="auto", min_confidence=0.6) -> Optional[StructureResult]` (spec §2 "Choice");
  - private helpers `_level_to_depth`, `_placed_depth`, `_position_key`, `_first_content_ordinals`.
- Append to `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py`: `test_hybrid_insertion`,
  `test_hybrid_rejects_noisy_layout`, `test_hybrid_confidence_and_empty_mapping`,
  `test_items_to_tree_pages_and_preface`, `test_choice_order_and_modes`.

**NOT in scope**:
- Changing `score_bookmarks` / `score_layout` / `heading_title` / `page_structure` or the models (TASK-5336) —
  if a bug is found there, fix it minimally and record it in the Completion Note.
- Unknown-mode validation and the LLM / page fallbacks (the builder, TASK-5340).
- Resolving `anchor` to a segment `seq` (TASK-5338, `attach_pdf_document`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` | MODIFY | Append `insert_layout_headings`, `items_to_tree`, `build_structure` + helpers |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` | MODIFY | Append the five M3b tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from collections import Counter                                    # stdlib (new import in layout_structure.py)
from parrot.knowledge.pageindex.segments import segment_pages      # tests only; verified: segments.py:231
```

#### Created by TASK-5336 (dependency — already in `layout_structure.py`)
```python
# module-level in layout_structure.py
logger; MAX_HEADING_WORDS; MAX_HEADINGS_PER_PAGE; MIN_CONTAINED_CHARS
class CandidateScore(BaseModel): source; confidence; entries; anchored; rejected
class StructureReport(BaseModel): source; mode; min_confidence; confidence=None; candidates=[]; inserted_headings=0;
                                  body_size=None; running_lines=0; llm_used=False; llm_error=None
class StructureResult(BaseModel): source; structure: list[dict]; report: StructureReport
def heading_title(text: str) -> str
def _segments_by_page(segments) -> dict[int, list[Segment]]
def score_bookmarks(profile, segments) -> tuple[CandidateScore, list[dict]]
def score_layout(profile, segments) -> tuple[CandidateScore, list[dict]]
def page_structure(page_count: int, doc_name: str) -> list[dict]
# already imported there: LayoutProfile, StructureMode, StructureSource, running_key (layout.py),
#                         Segment, _heading_text, _titles_match, normalize_title (segments.py), Optional, Sequence
```

#### Created by TASK-5333 (transitive)
```python
from parrot.knowledge.pageindex.layout import Bookmark, LayoutProfile, RunningLine   # tests build profiles with these
```
Re-verify: `grep -n "^def \|^class " packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py`.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel):  seq (:36); kind (:37); page (:38); ordinal (:39, restarts per page); level (:41); text (:42)
def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]   # :231

# packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py — the LLM-path conventions this task mirrors
def add_preface_if_needed(data) -> list[dict]                      # :410 — inserts {"title": "Preface", physical_index 1} as the FIRST flat item
def post_processing(structure, end_physical_index) -> list[dict]   # :426 — end_index = NEXT FLAT ITEM's page, minus 1 when
                                                                   #   that item appears at start; last item → end_physical_index
def list_to_tree(data) -> list[dict]                               # :371 — "nodes" deleted when empty (:398-404)
```

### Does NOT Exist
- ~~`utils.post_processing` / `utils.list_to_tree` keeping `anchor`~~ — they rebuild nodes from title/start/end/nodes
  only; do NOT route items through them (spec §6 "Does NOT Exist").
- ~~`LayoutProfile.headings`~~, ~~`Segment.title`~~, ~~`Segment.bbox`~~ — not attributes.
- ~~`StructureResult.confidence`~~ — confidence lives on `StructureResult.report`.
- ~~`build_structure` raising for an unknown mode~~ — the builder validates the mode (TASK-5340).
- ~~a `"structure"` key on items~~ — items use `depth`, not the LLM path's dotted `structure` index.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#segment_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#Segment",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#post_processing",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#add_preface_if_needed"
  ]
}
```

---

## Implementation Notes

### Rules (spec §2, rev 0.2 — implement exactly)
- **Choice**, with `mode` in `auto` | `layout`:
  1. bookmarks confidence `>= min_confidence` → the bookmark items; apply `insert_layout_headings` only when
     the layout confidence is **also** `>= min_confidence`. `source = "hybrid"` when at least one heading was
     inserted, else `"bookmarks"`. Hybrid confidence = `min(bookmarks, layout)`; bookmark-only keeps the
     bookmark confidence.
  2. else layout confidence `>= min_confidence` → `"layout"` with the layout confidence.
  3. else `None`. `mode="llm"` → `None` always.
  The report always lists **both** candidates (`[bookmarks, layout]`), plus `inserted_headings`,
  `body_size = profile.body_size`, `running_lines = len(profile.running)`.
- **Hybrid rule**: no anchored bookmark (anchor and level both set) → return the bookmark items unchanged and
  `0`. Otherwise map each anchored heading **level** to the most common bookmark **depth** among the bookmarks
  anchored at that level (ties → the smaller depth, for determinism). For every layout item (from
  `score_layout`) whose anchor is not a bookmark anchor, with level `L`:
  - `L` lower (shallower, smaller number) than every mapped level → skip (not structure);
  - `L` mapped → that depth;
  - else `depth(M) + (L − M)` where `M` is the deepest mapped level below `L` (largest mapped level `< L`).
  Order the merged list by segment position: `(page, ordinal)`; an unanchored bookmark uses ordinal `-1`
  (it sits at the first segment of its page, ahead of the headings on that page). Use a stable sort with the
  bookmark items first so ties keep bookmark order.
- **Tree and pages**: one flat document-ordered item list → nodes with a stack, depth clamped to
  `previous + 1` (first item clamped to 1). `start_index` = item page; `end_index` = next flat item's page,
  minus 1 when that item **appears at the start** of its page; `page_count` for the last item; never below
  `start_index`. An item appears at the start when it has an anchor and the anchor's ordinal is the first
  segment ordinal of its page once running-line segments are skipped (a segment is running when
  `running_key(heading_title(seg.text))` is a key of `profile.running`). When the first item starts after
  page 1, insert a flat `{"depth": 1, "title": "Preface", "page": 1, "anchor": None, "level": None}` item
  first (same as `add_preface_if_needed`, utils.py:410, on the LLM path) — its end follows the same rule.
- **Node shape**: `{"title", "start_index", "end_index", "nodes"?, "anchor"?}` — `nodes` only when non-empty,
  `anchor` (a copy) only when the item had one.

### Key Constraints
- Pure functions; `logger.debug` only. No pymupdf, no I/O.
- Do not mutate the caller's item dicts (build new node dicts).
- `build_structure` never raises for content: odd bookmarks were already rejected by the profile.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:410-440` — Preface and end_index convention to mirror.
- `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:371-408` — node shape to mirror.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `from collections import Counter` to the stdlib imports of `layout_structure.py` — *why*: `_level_to_depth` counts depths.
2. Append Block 1 (hybrid helpers + `insert_layout_headings`) and Block 2 (`items_to_tree` + `build_structure`) below `page_structure` — *why*: TASK-5336 owns everything above it.
3. Complete the FILL IN markers — *why*: they carry the rev 0.2 gating and the page convention; the tests pin them.
4. Append Block 3 to the test module and fill the bodies — *why*: spec §4 lists these five M3b tests.
5. Run the Validation Commands and `ruff check` — *why*: AC-18.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` (MODIFY) — Block 1 of 2
```python
# occurrences: 1 (verified after TASK-5336: grep -c '^def page_structure(' packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py)
# AFTER — append at the END of the file, below the body of `def page_structure(page_count: int, doc_name: str) -> list[dict]:`
# (also add `from collections import Counter` to the stdlib import group at the top)


def _level_to_depth(anchored: Sequence[dict]) -> dict[int, int]:
    """Heading level -> most common bookmark depth among the bookmarks anchored at that level (ties: smaller depth)."""
    counts: dict[int, Counter] = {}
    for item in anchored:
        counts.setdefault(int(item["level"]), Counter())[int(item["depth"])] += 1
    return {level: min(c, key=lambda depth: (-c[depth], depth)) for level, c in counts.items()}


def _placed_depth(level: Optional[int], mapping: dict[int, int]) -> Optional[int]:
    """Depth for an unbookmarked heading of ``level``; None when it is shallower than every mapped level."""
    if level is None or not mapping:
        return None
    # FILL IN: mapped level → mapping[level]; otherwise M = the largest mapped level < level → mapping[M] + (level - M);
    #   no mapped level below `level` → None (not structure) — bounded by spec §2 "Hybrid rule" (rev 0.2).
    raise NotImplementedError


def _position_key(item: dict) -> tuple[int, int]:
    """Document position: (page, anchor ordinal); an unanchored item sits ahead of its page's segments."""
    anchor = item.get("anchor")
    return (int(item["page"]), int(anchor["ordinal"]) if anchor else -1)


def insert_layout_headings(bookmark_items: list[dict], profile: LayoutProfile,
                           segments: Sequence[Segment]) -> tuple[list[dict], int]:
    """Hybrid rule of spec §2; caller must gate on both candidate scores meeting min_confidence.

    Returns the merged item list and insertion count; no anchored bookmarks means no insertions.
    """
    anchored = [it for it in bookmark_items if it.get("anchor") is not None and it.get("level") is not None]
    if not anchored:
        return list(bookmark_items), 0
    mapping = _level_to_depth(anchored)
    taken = {(it["anchor"]["page"], it["anchor"]["ordinal"]) for it in anchored}
    _, layout_items = score_layout(profile, segments)
    inserted: list[dict] = []
    for item in layout_items:
        if (item["anchor"]["page"], item["anchor"]["ordinal"]) in taken:
            continue
        depth = _placed_depth(item["level"], mapping)
        if depth is not None:
            inserted.append({**item, "depth": depth})
    merged = sorted([*bookmark_items, *inserted], key=_position_key)   # stable: bookmarks first on ties
    logger.debug("hybrid: mapping=%s, %d headings inserted", mapping, len(inserted))
    return merged, len(inserted)
```
**Why this shape**: the layout items come from `score_layout` so the hybrid rule sees exactly the headings the
layout score counted (running lines and empty titles already excluded). The early return is rev 0.2's "no
anchored bookmarks → no mapping → no insertions". Sorting is stable with bookmarks concatenated first, so an
unanchored bookmark (ordinal `-1`) precedes the headings of its page and bookmark order is preserved on ties.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` (MODIFY) — Block 2 of 2 (append below Block 1)
```python
def _first_content_ordinals(segments: Sequence[Segment], profile: LayoutProfile) -> dict[int, int]:
    """Page -> ordinal of its first segment that is not a running line."""
    running = {line.key for line in profile.running}
    first: dict[int, int] = {}
    for page, page_segments in _segments_by_page(segments).items():
        for seg in page_segments:
            if running_key(heading_title(seg.text)) not in running:
                first[page] = seg.ordinal
                break
    return first


def items_to_tree(items: Sequence[dict], segments: Sequence[Segment], profile: LayoutProfile) -> list[dict]:
    """Stack-built tree; start/end pages per the LLM-path convention; Preface when needed."""
    if not items:
        return []
    flat = list(items)
    if int(flat[0]["page"]) > 1:
        flat.insert(0, {"depth": 1, "title": "Preface", "page": 1, "anchor": None, "level": None})
    first = _first_content_ordinals(segments, profile)
    nodes: list[dict] = []
    for i, item in enumerate(flat):
        start = int(item["page"])
        # FILL IN: end = next flat item's page - 1 when that item has an anchor whose ordinal == first.get(its page),
        #   else the next item's page; the last item ends at profile.page_count; end = max(end, start) — bounded by
        #   spec §2 "Tree and pages" (mirrors utils.post_processing, utils.py:426).
        end = start
        node: dict = {"title": item["title"], "start_index": start, "end_index": end}
        if item.get("anchor"):
            node["anchor"] = dict(item["anchor"])
        nodes.append(node)
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    previous = 0
    for item, node in zip(flat, nodes):
        depth = max(1, min(int(item["depth"]), previous + 1))
        while stack and stack[-1][0] >= depth:
            stack.pop()
        (stack[-1][1].setdefault("nodes", []) if stack else roots).append(node)
        stack.append((depth, node))
        previous = depth
    return roots


def build_structure(profile: LayoutProfile, segments: Sequence[Segment], *,
                    mode: StructureMode = "auto", min_confidence: float = 0.6) -> Optional[StructureResult]:
    """Chosen bookmarks/hybrid/layout structure, or None when no candidate reaches min_confidence
    (always None for mode='llm'). The report lists both candidates."""
    if mode == "llm":
        return None
    bookmarks, bookmark_items = score_bookmarks(profile, segments)
    layout, layout_items = score_layout(profile, segments)
    # FILL IN: the rev 0.2 choice — (1) bookmarks.confidence >= min_confidence → bookmark_items; only when
    #   layout.confidence >= min_confidence too, call insert_layout_headings(bookmark_items, profile, segments);
    #   source "hybrid" iff inserted > 0 (confidence = min(bookmarks, layout)), else "bookmarks" (bookmark
    #   confidence); (2) elif layout passes → "layout" with layout_items and layout.confidence; (3) else
    #   logger.debug(...) and return None — bounded by spec §2 "Choice" and AC-21.
    source: StructureSource = "bookmarks"
    items: list[dict] = bookmark_items
    inserted = 0
    confidence: Optional[float] = bookmarks.confidence
    report = StructureReport(source=source, mode=mode, min_confidence=min_confidence, confidence=confidence,
                             candidates=[bookmarks, layout], inserted_headings=inserted,
                             body_size=profile.body_size, running_lines=len(profile.running))
    return StructureResult(source=source, structure=items_to_tree(items, segments, profile), report=report)
```
**Why this shape**: `items_to_tree` works on the flat list first (pages) and builds the hierarchy second
(stack), exactly like the LLM path's `post_processing` + `list_to_tree`, so `outline`, Bookstore's TOC and
`build_node_markdown_map` read every tree the same way. `setdefault("nodes", ...)` only creates `nodes` when a
child exists. `build_structure` computes both scores up front so the report always lists both, even for
`bookmarks`-only results (AC-21 "both candidate scores in the report").

### `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-5336: grep -c '^def test_page_structure' packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py)
# AFTER — append at the END of the file. Reuse the module's _segs / _profile helpers and the autouse tiktoken stub.
from parrot.knowledge.pageindex.layout_structure import (  # noqa: E402
    build_structure, insert_layout_headings, items_to_tree,
)

HYBRID_PAGES = (
    "# Report Title\n\n## 1 Intro\n\nText.\n\n### 1.1 Scope\n\nText.",
    "## 2 Usage\n\nText.\n\n## Appendix\n\nText.",
)


def test_hybrid_insertion():
    """Same-level unbookmarked heading → sibling; deeper → child; shallower → not structure (spec §2 Hybrid rule)."""
    # FILL IN: profile bookmarks [(1,"1 Intro",1),(1,"2 Usage",2)] over HYBRID_PAGES; score_bookmarks → items;
    #   insert_layout_headings(...) inserts "1.1 Scope" at depth 2 and "Appendix" at depth 1 (inserted == 2),
    #   never "Report Title" (level 1 < mapped level 2); items_to_tree nests Scope under Intro, Appendix top-level.
    raise NotImplementedError


def test_hybrid_rejects_noisy_layout():
    """Valid bookmarks (1.0) + ~100 short bold labels per page: layout fails density → bookmarks, 0 insertions."""
    # FILL IN: 2 pages, each "## Chapter n\n\n" + 100 x "#### Note k\n\n"; bookmarks anchor both chapters (1.0);
    #   build_structure(..., min_confidence=0.6) → source "bookmarks", report.inserted_headings == 0,
    #   [c.source for c in report.candidates] == ["bookmarks", "layout"], layout confidence < 0.6 (AC-21).
    raise NotImplementedError


def test_hybrid_confidence_and_empty_mapping():
    """Passing candidates → hybrid confidence = min of both; found-but-unanchored bookmarks → no insertions."""
    # FILL IN: (a) HYBRID_PAGES with one extra heading ending in "." so layout clean < 1 while bookmarks score 1.0 →
    #   source "hybrid", report.confidence == min(bookmark, layout); (b) bookmarks whose titles appear only in
    #   paragraphs (found, not anchored) + a passing layout → insert_layout_headings returns (items, 0) and
    #   build_structure gives "bookmarks" with the bookmark confidence (AC-21).
    raise NotImplementedError


def test_items_to_tree_pages_and_preface():
    """end_index convention with and without appear-at-start; Preface when the first item starts after page 1."""
    # FILL IN: items starting on page 2 → first node {"title": "Preface", "start_index": 1, ...}; an item whose anchor is
    #   the first non-running segment of page 3 makes the previous item end at 2, otherwise at 3; the last item ends at
    #   profile.page_count; end never below start; a running header segment first on the page is skipped when deciding
    #   appear-at-start; leaves carry no "nodes" key; anchors are copied onto nodes.
    raise NotImplementedError


def test_choice_order_and_modes():
    """bookmarks > layout > None; mode='llm' → None; threshold respected."""
    # FILL IN: rejected bookmarks + passing layout → "layout"; neither passing (min_confidence=0.99 on imperfect inputs)
    #   → None; mode="llm" → None even with perfect bookmarks; mode="layout" behaves like "auto" here;
    #   report.body_size == profile.body_size and report.running_lines == len(profile.running).
    raise NotImplementedError
```
**Why this shape**: inputs are markdown pages run through the real `segment_pages`, so heading levels and ordinals
match production. `HYBRID_PAGES` mirrors the fixture's shape (a document title shallower than the chapters, a
same-level `Appendix`, a deeper subsection) that AC-1 relies on end to end.

### FILL IN checklist
- [ ] `layout_structure.py::_placed_depth` — mapped / deeper-unmapped / shallower rules; bounded by spec §2 "Hybrid rule"
- [ ] `layout_structure.py::items_to_tree` — end_index convention with appear-at-start; bounded by spec §2 "Tree and pages"
- [ ] `layout_structure.py::build_structure` — rev 0.2 choice and confidence; bounded by spec §2 "Choice", AC-21
- [ ] `test_layout_structure.py` — five test bodies per the stubs

---

## Acceptance Criteria

- [ ] AC-21: hybrid insertions require both bookmark and layout confidence `>= min_confidence`; reliable bookmarks
  plus failing layout give `bookmarks`, zero insertions and both candidate scores in the report; hybrid
  confidence is the minimum of both; no anchored bookmarks means no insertions.
- [ ] AC-4: rejected bookmarks lead to the layout candidate or `None` (fallback), with the rejection reason in the
  report's bookmarks candidate.
- [ ] AC-1 (structure part): on `HYBRID_PAGES`-shaped inputs the bookmark titles keep their depths, same-level
  unbookmarked headings become siblings and the shallower document title is not structure (the fixture itself is
  checked end to end by TASK-5340 / TASK-5345).
- [ ] Trees follow the LLM-path page convention (`end_index`, `Preface`) and never carry an empty `nodes` list.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py -q`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_hybrid_insertion` | same-level → sibling; deeper → child (depth M + (L−M)); shallower → not structure |
| `test_hybrid_rejects_noisy_layout` | bookmarks 1.0 + density-failing layout → `bookmarks`, 0 insertions, both candidates in the report |
| `test_hybrid_confidence_and_empty_mapping` | hybrid confidence = min of both; found-but-unanchored bookmarks → no insertions |
| `test_items_to_tree_pages_and_preface` | `end_index` with/without appear-at-start (running lines skipped); `Preface`; no empty `nodes`; anchors copied |
| `test_choice_order_and_modes` | bookmarks > layout > None; `llm` → None; threshold respected; report body/running fields |

(Block 3 above is the scaffold.)

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure --feature-id FEAT-845`)
2. **Read the spec** at the path listed above for full context (§2 "Choice", "Hybrid rule", "Tree and pages",
   "Anchors"; revision history 0.2)
3. **Check dependencies** — TASK-5336 must be `"done"` in `sdd/tasks/index/pageindex-layout-structure.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every name in "Created by TASK-5336" exists in `layout_structure.py`
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/pageindex-layout-structure.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands as
   `PYTHONPATH=packages/ai-parrot/src pytest <file> -q` (never `uv sync` inside the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5337 pageindex-layout-structure verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
