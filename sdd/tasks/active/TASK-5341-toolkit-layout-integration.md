# TASK-5341: Toolkit integration — structure_mode, segment reuse, structure_source (M7)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5340, TASK-5338
**Assigned-to**: unassigned

---

## Context

Spec §2 "Toolkit" and Module 7. After TASK-5340 the builder returns one dict with
`structure_source`, `structure_report` and `_segments` (the layout-aware segments it already
produced) and every structure node carries a transient `anchor`. `PageIndexToolkit.import_pdf`
must pass the new `structure_mode` option through, reuse `_segments` instead of segmenting the
pages a second time, strip anchors on the path where no revision is attached (TASK-5338 strips
them on the revision path inside `attach_pdf_document`), return the structure keys, and report
`structure_source` per document in `list_documents`. FEAT-840's builder fakes return only
`_pages` / `_node_markdown`; they must keep working (AC-11).

---

## Scope

- Add `structure_mode: str = "auto"` as the LAST parameter of `PageIndexToolkit.import_pdf` and
  forward it as `options["structure_mode"]`.
- Replace the LLM-facing docstring with the spec M7 skeleton text (rev 0.2 wording, below).
- Pop `_segments`, `structure_source` and `structure_report` from the builder result with
  defaults; reuse `_segments` when present, otherwise keep today's `segment_pages(pages)` fallback.
- Strip `anchor` from every node on the no-revision path before splicing
  (`_strip_anchors` staticmethod).
- Add `structure_source`, `structure_confidence`, `structure_report` to the `import_pdf` result.
- `_documents_of` collects the root node's `structure_source`; each `list_documents` row reports it.
- Write `test_layout_import.py`.

**NOT in scope**: removing `pageindex_import_pdf` from `llm_dependent_tools` (TASK-5343); any
builder change (TASK-5340); `attach_pdf_document` anchor handling (TASK-5338); Bookstore
(TASK-5342); end-to-end fixture tests (TASK-5345).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `import_pdf(structure_mode)`, `_strip_anchors`, `_documents_of`, `list_documents` row |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_import.py` | CREATE | Result keys, `_segments` reuse, `list_documents` column, anchor strip |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# Already imported in toolkit.py — add nothing:
from .builder import build_page_index                                    # toolkit.py:36
from .segments import (..., attach_pdf_document, ..., segment_pages, ...)  # toolkit.py:49-67 (attach :57, segment_pages :65)
from .utils import find_node_by_id, get_pdf_name, structure_to_list      # toolkit.py:75
import asyncio, copy, hashlib                                            # toolkit.py:21-24

# Tests:
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit          # toolkit.py:90
from parrot.knowledge.pageindex.segments import segment_pages, validate_ownership  # segments.py:231, :473
from parrot.knowledge.pageindex.segment_store import SegmentStore       # segment_store.py:25 (load_revision :64)
from parrot.knowledge.pageindex.utils import structure_to_list          # utils.py:294
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):
    def __init__(self, adapter: Optional[PageIndexLLMAdapter] = None, storage_dir=None, ..., *,
                 llm_client=None, max_result_chars=None, **kwargs)              # :145
    self._store = JSONTreeStore(storage_dir)                                    # :189
    self._segment_store = SegmentStore(storage_dir)                             # :191
    self._light_adapter: Optional[PageIndexLLMAdapter]                          # :184
    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]  # :592
    def _documents_of(self, tree: dict[str, Any]) -> dict[str, dict[str, Any]]  # :755; dict literal :761
    async def list_documents(self, tree_name: str) -> list[dict[str, Any]]      # :853; row dict :864-861 ("scored_by" :871, "available" :872)
    async def insert_markdown(self, tree_name, markdown, parent_node_id=None, doc_name=None, doc_id=None, ...)  # :1375
    async def import_pdf(self, tree_name, pdf_path, parent_node_id=None, with_summaries=True,
                         with_doc_description=False, doc_id=None) -> dict[str, Any]  # :1546
        # :1555 docstring; :1568 is_file guard; :1569-1567 build_page_index(...) call ("if_add_node_id" :1576)
        # :1584 node_markdown = dict(subtree.pop("_node_markdown", {}) or {})
        # :1585 pages = list(subtree.pop("_pages", []) or [])
        # :1586 segments = await asyncio.to_thread(segment_pages, pages) if pages else []
        # :1610 attach_pdf_document(fresh["structure"], revision)   (inside `if segments and source is not None:`)
        # :1611 new_ids = splice_subtree(txn.tree, fresh, parent_node_id=parent_node_id)
        # :1621-1615 return {tree_name, new_node_ids, doc_name, doc_description (:1625), **imported (:1626)}
    async def _scan(self, segments: list) -> Optional[ScanReport]               # :1629

# packages/ai-parrot/src/parrot/knowledge/pageindex/tree_ops.py
def _coerce_subtree(subtree) -> list[dict]   # :40 — splice uses only subtree["structure"]; extra keys are ignored

# Existing fakes this task must keep green (they return only _pages/_node_markdown):
#   test_segment_import.py:57-72 (_pdf_fake), test_read_tools.py:61, test_segment_integration.py:69,
#   test_toolkit.py:322 (fake_build_page_index(doc, adapter, options=None, **kwargs))
```

### Created by TASK-5340 (dependency)
```python
# build_page_index(...) now returns one dict:
#   {doc_name, structure, structure_source, structure_report (dict = StructureReport.model_dump()),
#    _node_markdown, _pages, _segments, doc_description?}
# structure_report keys include "confidence" (Optional[float]) and "source".
# Every structure node carries "structure_source"; bookmark/layout/hybrid nodes carry
# "anchor": {"page": int, "ordinal": int}.
```

### Created by TASK-5338 (dependency)
```python
# attach_pdf_document(structure, revision) resolves and REMOVES "anchor" from every node it visits.
```

### Does NOT Exist
- ~~`PageIndexToolkit._strip_anchors`~~ — this task creates it
- ~~`structure_mode` parameter / `structure_source` key anywhere in toolkit.py~~ — added here
- ~~`subtree["_segments"]` from FEAT-840 fakes~~ — fakes return only `_pages`; always `pop(..., None)`
- ~~`toolkit.import_pdf(..., structure_min_confidence=...)`~~ — not a parameter; the threshold is a builder option only
- ~~a `structure_source` field on `DocumentRevision` / `SourceInfo`~~ — it lives on tree nodes only

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout_import.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.import_pdf",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._documents_of",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.list_documents",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#segment_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#attach_pdf_document"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Read every new builder key with a default — FEAT-840 fakes return only `_pages` (AC-11).
- `_segments` reuse means `segment_pages` is NOT called when the builder returned segments; the
  fallback stays for fakes and for `BytesIO`-style results with `_pages` only.
- Anchors must never reach a stored tree (AC-10): the revision path relies on TASK-5338; the
  no-revision path calls `_strip_anchors` before `splice_subtree`.
- The LLM-facing docstring is part of the tool description — copy the spec text verbatim.
- `toolkit.py` is also edited by FEAT-843 and FEAT-844 (other methods, `llm_dependent_tools`):
  rebase before `/sdd-done`.

### References in Codebase
- `test_segment_import.py:28-72` — tiktoken + injection-engine stubs and the `_pdf_fake` pattern to copy.
- `test_toolkit.py:322-342` — fake builder signature `(doc, adapter, options=None, **kwargs)`.

---

## Implementation Blueprint

### Steps (in order)
1. Re-run `grep -c` on every anchor below — *why*: TASK-5340 does not touch toolkit.py, but FEAT-843/844 may have landed first.
2. Apply block A to `import_pdf` (signature, docstring, options, pops, anchor strip, result) and add `_strip_anchors` — *why*: one method carries the whole M7 contract.
3. Apply blocks B and C (`_documents_of`, `list_documents`) — *why*: AC-9's per-document column.
4. Write `test_layout_import.py`, run the Validation Commands — *why*: AC-9/10/11 are proven here; the FEAT-840 suites prove the fakes still pass.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)

Block A — `import_pdf` and `_strip_anchors`:
```python
# A1  occurrences: 1 (verified: grep -c '    async def import_pdf(' toolkit.py) — REPLACE toolkit.py:1546-1555
#     (signature + docstring, down to and including the closing `"""` after
#     ``{tree_name, new_node_ids, doc_name, doc_description?, pages}``  (:1566, count 1))
    async def import_pdf(
        self,
        tree_name: str,
        pdf_path: str,
        parent_node_id: Optional[str] = None,
        with_summaries: bool = True,
        with_doc_description: bool = False,
        doc_id: Optional[str] = None,
        structure_mode: str = "auto",
    ) -> dict[str, Any]:
        """Build a PageIndex subtree from a PDF and splice it into ``tree_name``.

        Structure comes from the PDF's bookmarks or printed headings when they are reliable, from the
        LLM otherwise (structure_mode='auto'); 'layout' never calls a model for structure, 'llm'
        forces the LLM structure pipeline. Summaries and descriptions remain controlled by their
        own options when a model is configured. Works without a model (no summaries or description).

        Args:
            tree_name: Existing tree to insert into.
            pdf_path: Path to the source PDF on disk.
            parent_node_id: Insert under this node id, or at root if ``None``.
            with_summaries: When ``True`` and a model is configured, generate per-node summaries.
            with_doc_description: When ``True`` (and summaries run), also generate a document description.
            doc_id: Explicit document id; derived from the file name when ``None``.
            structure_mode: ``"auto"`` | ``"layout"`` | ``"llm"``.

        Returns: {tree_name, new_node_ids, doc_name, doc_description, doc_id, revision,
                  structure_source, structure_confidence, structure_report}
        """

# A2  occurrences: 1 (verified: grep -c '                "if_add_node_id": "yes",' toolkit.py) — AFTER toolkit.py:1576
                "structure_mode": structure_mode,

# A3  occurrences: 1 each (verified: grep -c on each line) — REPLACE toolkit.py:1584-1574
        node_markdown = dict(subtree.pop("_node_markdown", {}) or {})
        pages = list(subtree.pop("_pages", []) or [])
        built_segments = subtree.pop("_segments", None)
        structure_source = subtree.pop("structure_source", None)
        structure_report = subtree.pop("structure_report", None)
        # FILL IN: reuse built_segments when it is not None (list(built_segments)), else keep
        #   `await asyncio.to_thread(segment_pages, pages) if pages else []` — bounded by AC-11
        #   (no second segmentation when the builder returned _segments; fakes keep working)
        segments = ...

# A4  occurrences: 1 (verified: grep -c '                attach_pdf_document(fresh["structure"], revision)' toolkit.py)
#     AFTER toolkit.py:1610 — closes the `if segments and source is not None:` block
            else:
                self._strip_anchors(fresh["structure"])

# A5  occurrences: 1 (verified: grep -c '            "doc_description": subtree.get("doc_description"),' toolkit.py)
#     AFTER toolkit.py:1625 (before `**imported,` at :1626)
            "structure_source": structure_source,
            "structure_confidence": (structure_report or {}).get("confidence"),
            "structure_report": structure_report,

# A6  occurrences: 1 (verified: grep -c '    async def _scan(self, segments: list) -> Optional[ScanReport]:' toolkit.py)
#     BEFORE toolkit.py:1629
    @staticmethod
    def _strip_anchors(nodes: list[dict[str, Any]]) -> None:
        """Remove the transient ``anchor`` key from every node (no-revision path)."""
        for node in structure_to_list(nodes):
            node.pop("anchor", None)

```
**Why this shape**: A1–A5 are the spec M7 skeleton applied in place; the defaults in A3 are what
keep FEAT-840's fakes green, and `structure_confidence` is derived from the report rather than a
separate builder key so there is one source of truth. A4 is the only place anchors could otherwise
survive (TASK-5338 handles the revision branch). `structure_to_list` walks nested `nodes`
(utils.py:294), so `_strip_anchors` needs no recursion of its own. Do not reorder the parameters:
`structure_mode` is last so positional callers are unaffected.

Block B — `_documents_of`:
```python
# occurrences: 1 (verified: grep -c '                docs[doc_id] = {"revision": revision, "root_node_id": node.get("node_id"), "name": node.get("title")}' toolkit.py)
# REPLACE toolkit.py:761
                docs[doc_id] = {
                    "revision": revision,
                    "root_node_id": node.get("node_id"),
                    "name": node.get("title"),
                    "structure_source": node.get("structure_source"),
                }
```
**Why**: the first node per `doc_id` in pre-order is the document's root; every node of a PDF import
carries `structure_source`, markdown/ebook/legacy nodes carry none → `None`.

Block C — `list_documents` row:
```python
# occurrences: 1 (verified: grep -c '                    "scored_by": rev.scored_by if rev else None,' toolkit.py)
# AFTER toolkit.py:871
                    "structure_source": info.get("structure_source"),
```
**Why**: AC-9 — one more column; `info` is the `_documents_of` entry, so legacy trees read `None`.
Update the `list_documents` docstring's field list (:854) to name `structure_source`.

### `packages/ai-parrot/tests/knowledge/pageindex/test_layout_import.py` (CREATE)
```python
"""Toolkit integration of the layout structure builder (FEAT-845 M7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.pageindex.segments import segment_pages, validate_ownership
from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.utils import structure_to_list

PAGES = [(1, "# Ch 1\n\nIntro.\n\n## 1.1 Scope\n\nScope."), (2, "More.")]


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    approx = lambda text, model="gpt-4o": max(1, len(text or ""))  # noqa: E731
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", approx)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )


@pytest.fixture
def toolkit(tmp_path: Path) -> PageIndexToolkit:
    return PageIndexToolkit(storage_dir=tmp_path)


def _structure() -> list[dict[str, Any]]:
    """Ch 1 (anchored at page 1 ordinal 0) with child 1.1 Scope (page 1 ordinal 2), all stamped 'layout'."""
    # FILL IN: return the two-node tree with node_id, start_index/end_index, "structure_source": "layout"
    #   on both nodes and "anchor" dicts matching PAGES' heading segments — bounded by brief item 5 node shape
    raise NotImplementedError


def _fake(*, with_segments: bool, with_pages: bool = True, calls: list | None = None):
    async def fake_build(doc, adapter, options=None, **kwargs):
        # FILL IN: record options in `calls`; return {"doc_name": "doc.pdf", "structure": _structure(),
        #   "_node_markdown": {}, "structure_source": "layout", "structure_report": {"source": "layout",
        #   "confidence": 0.9, ...}} plus "_pages": PAGES when with_pages and "_segments":
        #   segment_pages(PAGES) (the segments-module function, not the toolkit's patched name) when
        #   with_segments — bounded by brief item 8 return keys
        raise NotImplementedError

    return fake_build


async def test_import_pdf_result_and_segments_reuse(toolkit, tmp_path, monkeypatch):
    """_segments reused (toolkit.segment_pages never called); result keys; fake with only _pages still works."""
    # FILL IN: patch "parrot.knowledge.pageindex.toolkit.segment_pages" with a spy that raises/records;
    #   import with _fake(with_segments=True) → spy not called, result has structure_source == "layout",
    #   structure_confidence == 0.9, structure_report dict, options["structure_mode"] forwarded;
    #   revision stored (SegmentStore(tmp_path).load_revision) and validate_ownership(...) == [];
    #   no node of the stored tree has "anchor". Then a second tree with _fake(with_segments=False):
    #   spy restored to the real function, import succeeds, structure_source still returned (AC-11)
    raise NotImplementedError


async def test_list_documents_structure_source(toolkit, tmp_path, monkeypatch):
    """PDF row reports its structure_source; a markdown row reports None (AC-9)."""
    # FILL IN: insert_markdown + import_pdf (fake) into one tree; rows keyed by doc_id
    raise NotImplementedError


async def test_anchor_stripped_without_revision(toolkit, tmp_path, monkeypatch):
    """No pages and no segments → no revision, and no 'anchor' key anywhere in the stored tree (AC-10)."""
    # FILL IN: _fake(with_segments=False, with_pages=False); walk structure_to_list(toolkit._store.load(...))
    raise NotImplementedError
```
**Why this shape**: the fake calls `segments.segment_pages` directly, so patching the toolkit's
imported name proves the toolkit itself never segments when `_segments` is present. The toolkit is
built without an adapter (FEAT-842) so no model is reachable; the injection engine is stubbed as in
`test_segment_import.py:35-37` so scoring stays on the regex path. Each test writes its own fake PDF
bytes (`b"%PDF-1.4 fake"`) because `import_pdf` only checks `is_file` before calling the (faked) builder.

### FILL IN checklist
- [ ] `toolkit.py::import_pdf` A3 — `segments` from `built_segments` or the `segment_pages` fallback; bounded by AC-11
- [ ] `test_layout_import.py::_structure` — two-node anchored tree; bounded by brief item 5
- [ ] `test_layout_import.py::_fake` — return keys and option capture; bounded by brief item 8
- [ ] `test_layout_import.py` three test bodies — assertions listed in each docstring/comment; bounded by AC-9, AC-10, AC-11

---

## Acceptance Criteria

- [ ] AC-9 (toolkit part): `import_pdf` returns `structure_source`, `structure_confidence` and `structure_report`; `list_documents` reports `structure_source` per document (`None` for markdown).
- [ ] AC-10: no stored tree contains an `anchor` key, with or without segments.
- [ ] AC-11: `import_pdf` does not segment twice when the builder returns `_segments`; FEAT-840 fakes returning only `_pages` keep passing.
- [ ] `structure_mode` is forwarded to `build_page_index` as `options["structure_mode"]`.
- [ ] All Validation Commands pass.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py packages/ai-parrot/tests/knowledge/pageindex/test_layout_import.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_import.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_read_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_import_pdf_result_and_segments_reuse` | toolkit-level `segment_pages` not called with `_segments`; result keys; `structure_mode` forwarded; revision partitions; no `anchor`; a `_pages`-only fake still imports |
| `test_list_documents_structure_source` | PDF row `structure_source == "layout"`; markdown row `None` |
| `test_anchor_stripped_without_revision` | no revision (`doc_id is None`), no `anchor` in any stored node |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure --feature-id FEAT-845`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5340 and TASK-5338 must be `"done"` in
   `sdd/tasks/index/pageindex-layout-structure.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/pageindex-layout-structure.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands as
   `PYTHONPATH=packages/ai-parrot/src pytest <file> -q` (never `uv sync` in the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5341 pageindex-layout-structure verified`
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
