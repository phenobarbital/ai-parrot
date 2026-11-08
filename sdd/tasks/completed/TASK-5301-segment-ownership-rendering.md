# TASK-5301: Spans, owned ranges and body rendering

**Feature**: FEAT-840 — PageIndex Segment Store
**Spec**: `sdd/specs/pageindex-segment-store.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5300
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 2**. A node of an imported subtree gets `doc_id`, `revision`,
`span` (its subtree's half-open range over `seq`) and `owned` (the span minus its children's
spans). Owned ranges partition the document, and a node's body is rendered from them
(`render_body`). This is what removes duplicated shared-page text and what the optimizer slice
will re-check with `validate_ownership` before it re-partitions.

---

## Scope

- Add to `segments.py`: `normalize_title`, `attach_pdf_document`, `attach_section_document`,
  `render_body`, `validate_ownership` and the private range helpers.
- Extend `test_segments.py` with the ownership tests.

**NOT in scope**: calling these from the toolkit (TASK-5308), optimizer passes, `key_items`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py` | MODIFY | Ownership + rendering (append) |
| `packages/ai-parrot/tests/knowledge/pageindex/test_segments.py` | MODIFY | Ownership tests (append) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.utils import structure_to_list   # verified: knowledge/pageindex/utils.py:294
# plus everything TASK-5300 created in segments.py (Segment, DocumentRevision)
```

### Existing Signatures to Use
```python
# knowledge/pageindex/schemas.py — node fields produced by build_page_index
start_index: Optional[int]; end_index: Optional[int]      # lines 123-124 — 1-based, INCLUSIVE physical pages
nodes: Optional[list[PageIndexNode]]                       # line 129

# knowledge/pageindex/utils.py
def structure_to_list(structure) -> list[dict]             # line 294 — pre-order flattening
def post_processing(structure, end_physical_index)         # line 426 — a parent's end_index stops at its first child

# knowledge/pageindex/pdf_to_markdown.py
def build_node_markdown_map(structure, pages)              # line 211 — today's inclusive page slicing (the behaviour this replaces)

# knowledge/pageindex/builder.py
async def check_title_appearance_in_start_concurrent(...)  # line 683 — LLM check that a title starts its page; mirrored here deterministically
```

### Does NOT Exist
- ~~`span`, `owned`, `doc_id`, `revision` node fields~~ — introduced here (toolkit wiring in TASK-5308)
- ~~an ownership validator or partition check~~ anywhere under `knowledge/pageindex/`
- ~~`key_items`, `locked`~~ — optimizer slice

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_segments.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#DocumentRevision",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#structure_to_list"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Ranges are half-open `[start, end)` over `seq`, stored as JSON lists (`span: [a, b]`,
  `owned: [[a, b], ...]`), sorted, maximal (adjacent ranges merged), never empty.
- **PDF spans** (`attach_pdf_document`): walk siblings in order. Span start = the first segment
  whose `page == start_index`, or — when a segment on that page has `kind == "heading"` and its text
  matches `normalize_title(node["title"])` — that segment. Span end = min(first segment with
  `page > end_index`, next sibling's start); then widen a parent's span to cover its children.
  A node whose page range has no segment gets no span and owns nothing — *because* an empty page
  range must not steal text from a sibling.
- The first top-level node's span starts at 0 and the last one's ends at `len(segments)`, so
  front/back matter belongs to a node — *because* the partition must cover `[0, n)` exactly (AC-3).
- **owned** = span minus the union of the children's spans.
- **Section documents** (`attach_section_document`): `by_node[id(node)]` is the node's own
  `[start, end)`; owned = that range (or nothing when empty); span = union of own range and the
  descendants' spans.
- `normalize_title`: casefold, collapse whitespace, strip leading numbering `^\d+(\.\d+)*\.?\s*`
  and trailing punctuation; match = equality, or containment of the shorter in the longer when the
  shorter has ≥ 3 characters (spec §7).
- `render_body`: owned segments in document order joined by `"\n\n"`; at every point where a
  child's span interrupts the owned ranges, emit `<!-- continues in: <child title> -->` once per
  child, in document order. Deterministic — *because* an unchanged node must re-render to the same
  `body_sha16` (spec §2 *Bodies as views*).
- `validate_ownership` returns human-readable problems: `gap [a, b)`, `overlap seq N owned by X and Y`,
  `out of range`. Empty list ⇔ exact partition.

---

## Implementation Blueprint

### Steps (in order)
1. Append the block below to `segments.py` — *why*: the names are fixed by spec §3 M2.
2. Fill the range helpers first, then `attach_*`, then `render_body` and `validate_ownership`.
3. Append the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py` (MODIFY)
```python
# AFTER — append at the end of the module (after `def parse_cursor`, created by TASK-5300)
# occurrences: 1 (verify: grep -c '^def parse_cursor' segments.py)

from parrot.knowledge.pageindex.utils import structure_to_list  # move to the import block at the top

_NUM_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s*")

Range = tuple[int, int]


def normalize_title(title: str) -> str:
    """Casefold, collapse whitespace, strip leading numbering and trailing punctuation."""
    # FILL IN — bounded by Key Constraints (normalize_title)
    raise NotImplementedError


def _titles_match(a: str, b: str) -> bool:
    # FILL IN: equality or containment with the >= 3 chars rule — bounded by spec §7
    raise NotImplementedError


def _subtract(span: Range, holes: Sequence[Range]) -> list[Range]:
    """``span`` minus ``holes`` as sorted, maximal, non-empty half-open ranges."""
    # FILL IN
    raise NotImplementedError


def attach_pdf_document(structure: list[dict], revision: DocumentRevision) -> None:
    """Set ``doc_id``, ``revision``, ``span`` and ``owned`` on every node of ``structure`` (PDF source)."""
    # FILL IN: recursive sibling walk per Key Constraints (PDF spans) — bounded by AC-1..AC-3
    raise NotImplementedError


def attach_section_document(structure: list[dict], revision: DocumentRevision,
                            by_node: dict[int, tuple[int, int]]) -> None:
    """Same fields for an unpaged source; ``by_node`` maps ``id(node)`` to its own ``[start, end)``."""
    # FILL IN — bounded by Key Constraints (section documents), AC-4
    raise NotImplementedError


def render_body(revision: DocumentRevision, node: dict, children: Sequence[dict]) -> str:
    """Owned segments in document order with one gap marker per interrupting child."""
    # FILL IN — bounded by AC-5
    raise NotImplementedError


def validate_ownership(nodes: Sequence[dict], revision: DocumentRevision) -> list[str]:
    """Problems with the owned ranges of ``nodes``; empty when they partition ``[0, n)`` exactly once."""
    # FILL IN — bounded by AC-6
    raise NotImplementedError
```
**Why this shape**: `attach_*` mutate the subtree in place because the toolkit already holds object
references to the spliced nodes (`_capture_node_id_object_map`, `toolkit.py:1424`). `render_body`
takes `children` explicitly so callers decide which nodes are children (a subtree root's parent is
outside the document).

### FILL IN checklist
- [ ] `normalize_title`, `_titles_match`, `_subtract`
- [ ] `attach_pdf_document`; bounded by AC-1..AC-3
- [ ] `attach_section_document`; bounded by AC-4
- [ ] `render_body`; bounded by AC-5
- [ ] `validate_ownership`; bounded by AC-6

---

## Acceptance Criteria

- [ ] AC-1: parent and child starting on one page where a heading segment matches the child's title → the parent owns the segments before that heading; the child's span starts at it.
- [ ] AC-2: a child on a shared page with no matching heading starts at the page's first segment and its earlier sibling ends there.
- [ ] AC-3: for any attached PDF document, `validate_ownership(all nodes, revision) == []` (front and back matter included).
- [ ] AC-4: section documents: span == owned for leaves; a parent owns only its own paragraphs.
- [ ] AC-5: text between two children belongs to the parent and `render_body` emits two gap markers in document order; two renders are byte-identical.
- [ ] AC-6: removing one owner reports `gap`; duplicating a range reports `overlap`.
- [ ] `ruff check` on `segments.py` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segments.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_segments.py  (append)
from parrot.knowledge.pageindex.segments import (
    DocumentRevision, SourceInfo, attach_pdf_document, render_body, revision_id, validate_ownership,
)
from parrot.knowledge.pageindex.utils import structure_to_list


def _rev(pages):
    segs = segment_pages(pages)
    return DocumentRevision(doc_id="d", revision=revision_id(segs), source=SourceInfo(name="d.pdf", kind="pdf"),
                            created_at="2026-11-07T00:00:00Z", segments=segs)


def test_attach_pdf_shared_page_partition():
    rev = _rev([(1, "# Ch 1\n\nIntro.\n\n## 1.1 Scope\n\nScope text."), (2, "More scope.")])
    tree = [{"title": "Ch 1", "start_index": 1, "end_index": 2,
             "nodes": [{"title": "1.1 Scope", "start_index": 1, "end_index": 2}]}]
    attach_pdf_document(tree, rev)
    parent, child = tree[0], tree[0]["nodes"][0]
    assert parent["owned"] == [[0, 2]] and child["span"] == [2, 5]
    assert validate_ownership(structure_to_list(tree), rev) == []


def test_attach_pdf_no_title_match():
    # FILL IN — AC-2
    ...


def test_attach_pdf_parent_interstitial_text():
    # FILL IN — AC-5 (two children with parent text between them; two markers)
    ...


def test_render_body_deterministic():
    # FILL IN — AC-5
    ...


def test_validate_ownership_reports_gap_and_overlap():
    # FILL IN — AC-6
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
8. **Commit code** (`feat(pageindex-segment-store): TASK-5301 — Spans, owned ranges and body rendering`), then close with
   `parrot sdd task close TASK-5301 pageindex-segment-store verified` and fill the Completion Note.

---

## Completion Note

Added normalize_title, attach_pdf_document, attach_section_document, render_body, validate_ownership. Top-level gaps go to the preceding sibling so the partition is exact; nested gaps stay with the parent. structure_to_list import not added to segments.py (unused there).

**Completed by**: sdd-worker (sequential fallback; parrot-sdd-coder MCP unavailable)
**Date**: 2026-11-07
**Notes**: tests run with a scratchpad-only shim for navconfig's read-only log dir (environment, not committed)
**Deviations from spec**: none
