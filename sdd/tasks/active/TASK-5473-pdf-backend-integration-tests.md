# TASK-5473: Native PDF backend integration tests

**Feature**: FEAT-875 — Optional PyMuPDF Layout for Bookstore PDF Ingestion
**Spec**: `sdd/specs/bookstore-pymupdf-layout.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5470, TASK-5471, TASK-5472
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 and §4 Integration Tests. This proves the complete ingestion path, from
`Bookstore.add_book(pdf_backend="pymupdf-layout")` through `build_page_index` and the isolated
worker to publication, against **real** native Layout on generated PDFs. These are the
feature's quality gate (spec §2: if native headings fail it, stop for a design revision; do not weaken assertions).

## Scope

Create `tests/knowledge/pageindex/test_pdf_backend_integration.py` with fixtures generated in `tmp_path`
via PyMuPDF (two columns with unique sentinels, a ruled table with labeled cells, bookmarks,
bold and enumerated headings, a blank middle page, and an image-only page), plus:

- `test_layout_import_preserves_physical_pages`: physical-page identity, blank page, segment ownership, citation alignment.
- `test_layout_failure_preserves_published_book`: a forced Layout re-index failure leaves the previously
  published card, tree, and retrieval readable, and an initial failure publishes no book.
- Column sentinel order, table cell order, and every expected heading and page.
- Bookmark and hybrid trees still cite valid pages. `--no-llm` (no adapter) invokes no remote model.
- Isolation: concurrent legacy and Layout imports via `asyncio.gather` do not affect each other's heading mode or import state.
- An arxiv fixture comparison against the legacy baseline: page alignment and text retention are
  **asserted**, while heading and table differences are only recorded.
- Collect cold and warm extraction time and peak child memory for both backends into
  `artifacts/logs/FEAT-875-backend-comparison.md`, with no performance threshold asserted.

Native tests skip only when Layout is absent (`pytest.importorskip` on the module verified in TASK-5469).
The Layout-enabled job must show **zero** native skips.

**Deviation from spec §3 M5 path list:** `tests/knowledge/bookstore/test_pdf_backend.py`
(including `test_cli_pdf_backend_forwarding`) is created by TASK-5472, which owns Bookstore forwarding.
That avoids two tasks owning one file. This task owns the single integration file.

**NOT in scope**: production code changes. If a gate fails, record it and mark `done-with-issues`. Do not patch `pdf_layout_backend.py` from here.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_backend_integration.py` | CREATE | Native end-to-end + quality gate |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.pageindex.builder import build_page_index      # verified: builder.py:1571
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit       # verified: library.py:35
from parrot.knowledge.pageindex.layout import PDFStructureError       # verified: layout.py:51
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.pageindex.pdf_layout_backend import extract_layout_pages   # created by TASK-5470
```

### Existing Signatures to Use

```python
async def build_page_index(doc: str | BytesIO, adapter=None, options: dict | config | None = None, ...) -> dict
#   result keys: "structure", "structure_source", "structure_report", "_pages", "_segments", "_node_markdown"
async def PageIndexToolkit.import_pdf(..., structure_mode: str = "auto", *, pdf_backend: str = "legacy")  # TASK-5471
async def Bookstore.add_book(file_path, scope="project", ..., force=False, *, relate=False, pdf_backend="legacy")  # TASK-5472
```

Reusable read-only fixture: `packages/ai-parrot/tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf`.
For Bookstore setup, reuse the patterns in `tests/knowledge/bookstore/test_library.py` and `test_reindex_hardening.py`
(atomic re-index is already covered there for legacy).

### Does NOT Exist

- No existing generated-PDF helper for columns or tables. Build fixtures with `pymupdf` page drawing in this file.
- No performance target exists. Do not assert timings.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_pdf_backend_integration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#build_page_index",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_book"
  ]
}
```

## Implementation Notes

### Key Constraints

- No network or LLM calls. Pass no adapter (`--no-llm` equivalent).
- Never commit PDFs. Fixtures are generated into `tmp_path`, and the arxiv fixture is read-only.
- To force a failure in the atomicity test, monkeypatch `extract_layout_pages` to raise `PDFStructureError` after a successful legacy publish.

## Implementation Blueprint

### Steps (in order)

1. Write fixture builders (pymupdf), one per scenario, so each test reads clearly.
2. Write the two named tests from spec §3 M5 first, because they are the acceptance anchors.
3. Add the remaining scenario tests.
4. Add the comparison and measurement test that writes the artifacts log.

### `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_backend_integration.py` (CREATE)

```python
"""Native PyMuPDF Layout backend integration tests (FEAT-875)."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.pageindex.builder import build_page_index

pymupdf = pytest.importorskip("pymupdf")
# FILL IN: layout = pytest.importorskip("<verified Layout module from sdd/state/FEAT-875/layout-compatibility.md>")

ARXIV = Path(__file__).parent / "fixtures" / "arxiv_2408_09869.pdf"


def _two_column_pdf(path: Path) -> Path:
    # FILL IN: left/right column text with unique ordered sentinels (L1..Ln, R1..Rn)
    ...


def _blank_middle_pdf(path: Path) -> Path:
    # FILL IN: 3 pages; page 2 has no text; pages 1/3 carry sentinels
    ...


# FILL IN: _table_pdf, _headings_pdf (chapter/subsection/bold-body/enumerated), _bookmarked_pdf


async def test_layout_import_preserves_physical_pages(tmp_path: Path) -> None:
    """Native Layout preserves page citations, blank pages and segment ownership."""
    pdf = _blank_middle_pdf(tmp_path / "blank.pdf")
    result = await build_page_index(str(pdf), options={"pdf_backend": "pymupdf-layout", "structure_mode": "layout"})
    pages = result["_pages"]
    assert [p for p, _ in pages] == [1, 2, 3]
    assert pages[1][1].strip() == ""
    # FILL IN: sentinel on correct page; every segment's page within 1..3; node page ranges valid
    ...


async def test_layout_failure_preserves_published_book(tmp_path: Path) -> None:
    """An explicit backend failure leaves the prior publication readable."""
    # FILL IN: legacy add_book -> published; monkeypatch extract_layout_pages to raise PDFStructureError;
    #          add_book(force=True, pdf_backend="pymupdf-layout") raises BookstoreError;
    #          card/tree/retrieval still return the legacy content; fresh failing add publishes nothing
    ...


# FILL IN: test_two_column_sentinel_order, test_table_cells_in_row_order, test_headings_retained,
#          test_bookmark_and_hybrid_trees_cite_valid_pages, test_concurrent_legacy_and_layout_isolated,
#          test_arxiv_page_alignment_and_text_retention (+ write artifacts/logs/FEAT-875-backend-comparison.md)
```

**Why:** `structure_mode="layout"` with no adapter exercises the no-LLM path deterministically.
`_pages` and `_segments` are the builder's existing return keys, so the assertions need no new API.

### FILL IN checklist

- [ ] Verified Layout module in `importorskip`
- [ ] Five fixture builders
- [ ] Both named tests completed
- [ ] Six scenario tests
- [ ] Comparison log written under `artifacts/logs/`

## Acceptance Criteria

- [ ] With Layout installed, every native test runs, none skip, and all pass.
- [ ] Without Layout, the file skips cleanly (base-install optionality).
- [ ] Physical pages, the blank page, citations, and segment ownership are correct. Failure atomicity holds.
- [ ] The comparison report records versions, text, heading, and table outcomes, time, and memory.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_backend_integration.py -q`

## Test Specification

See the blueprint. Run it twice: once in an environment with `ai-parrot[bookstore-layout]` (expect zero
skips, `-rs` to prove it) and once in the base environment (expect module-level skip).

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**: `parrot sdd worktree ensure --slug bookstore-pymupdf-layout --feature-id FEAT-875`
2. **Read the spec** and `sdd/state/FEAT-875/layout-compatibility.md`.
3. **Check dependencies**: TASK-5470, TASK-5471, and TASK-5472 must be `"done"`.
4. **Verify the Codebase Contract** before writing code.
5. **Update status** to `"in-progress"` and commit only the index file.
6. **Implement** from the blueprint, completing every `FILL IN`.
7. **Verify**: run the Validation Commands in both environments.
8. **Commit** only the files this task lists.
9. **Close** with `parrot sdd task close TASK-5473 bookstore-pymupdf-layout verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
