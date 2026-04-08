# TASK-640: Unit tests for ExcelLoader sheet mode and row mode

**Feature**: excelloader-migration
**Spec**: `sdd/specs/excelloader-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-638
**Assigned-to**: unassigned

---

## Context

After TASK-638 adds per-sheet document generation to ExcelLoader, this task writes
comprehensive unit tests covering both the new `output_mode="sheet"` path and the
legacy `output_mode="row"` backward compatibility.

Implements spec Section 4 (Test Specification).

---

## Scope

- Create test file `packages/ai-parrot-loaders/tests/test_excel_loader.py`
- Write fixtures: `simple_excel` (single sheet), `multi_sheet_excel` (3 sheets including empty)
- Test `output_mode="sheet"`:
  - Single-sheet workbook produces exactly 1 Document
  - Multi-sheet workbook produces 1 Document per non-empty sheet (empty sheets skipped)
  - Each Document contains structural header (sheet name, dimensions, table info)
  - Each Document contains detected tables as markdown
  - Metadata has `content_type: "sheet"`, `table_count`, `sheet` name
  - `max_rows_per_table` truncates large tables
  - Sheets with no detected tables produce Document with raw cell content
- Test `output_mode="row"`:
  - Produces per-row Documents (existing behavior)
  - Row metadata has `content_type: "row"`, `row_index`
- Test defaults:
  - Default `output_mode` is `"sheet"`
- Test DataFrame input:
  - Falls back to row mode regardless of `output_mode`

**NOT in scope**: Modifying ExcelLoader code (TASK-638), integration tests

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/tests/test_excel_loader.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# ExcelLoader - after TASK-638 modifications
from parrot_loaders.excel import ExcelLoader  # verified: packages/ai-parrot-loaders/src/parrot_loaders/excel.py:11

# Document model for assertions
from parrot.stores.models import Document  # verified: packages/ai-parrot/src/parrot/stores/models.py:21

# Test dependencies
import pytest
import openpyxl
import pandas as pd
```

### Existing Signatures to Use

```python
# After TASK-638, ExcelLoader will have these NEW params:
class ExcelLoader(AbstractLoader):
    def __init__(self, source=None, *,
                 # ... existing params ...
                 output_mode: Literal["sheet", "row"] = "sheet",  # NEW
                 max_rows_per_table: int = 200,                    # NEW
                 **kwargs)

    # AbstractLoader provides the public load() method that calls _load() internally.
    # To test, call: await loader.load() which returns List[Document]

# packages/ai-parrot/src/parrot/loaders/abstract.py
class AbstractLoader(ABC):
    async def load(self, source=None, **kwargs) -> List[Document]  # public entry point
    # load() resolves sources and calls _load() for each

# packages/ai-parrot/src/parrot/stores/models.py:21
class Document(BaseModel):
    page_content: str  # the document text content
    metadata: Dict[str, Any]  # metadata dictionary
```

### Does NOT Exist

- ~~`ExcelLoader.load_sheet()`~~ — no such method; use `load()` which calls `_load()` internally
- ~~`ExcelLoader.from_file()`~~ — no such method; pass source to constructor or `load(source=path)`
- ~~`Document.content`~~ — the field is `page_content`, NOT `content`
- ~~`Document.text`~~ — does not exist; use `page_content`

---

## Implementation Notes

### Test structure

Use `pytest` with `pytest-asyncio` for async tests. Group tests in a class.

### Fixtures

```python
@pytest.fixture
def simple_excel(tmp_path):
    """Single-sheet workbook with 5 data rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Product", "Revenue", "Units"])
    for i in range(5):
        ws.append([f"Product {i}", (i + 1) * 100, (i + 1) * 10])
    path = tmp_path / "simple.xlsx"
    wb.save(path)
    return path

@pytest.fixture
def multi_sheet_excel(tmp_path):
    """3-sheet workbook: Sales (3 rows), Expenses (2 rows), Empty."""
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Sales"
    ws1.append(["Product", "Q1", "Q2"])
    for i in range(3):
        ws1.append([f"Item {i}", i * 10, i * 20])
    ws2 = wb.create_sheet("Expenses")
    ws2.append(["Category", "Amount"])
    ws2.append(["Rent", 5000])
    ws2.append(["Utilities", 800])
    wb.create_sheet("Empty")
    path = tmp_path / "multi.xlsx"
    wb.save(path)
    return path
```

### How to invoke the loader

```python
loader = ExcelLoader(source=str(path), output_mode="sheet")
docs = await loader.load()
# docs is List[Document]
```

### Key assertions

- `len(docs)` matches expected sheet count (excluding empty sheets)
- `doc.page_content` contains expected structural header keywords
- `doc.metadata["document_meta"]["content_type"]` equals `"sheet"` or `"row"`
- `doc.metadata["document_meta"]["sheet"]` matches sheet name

### Key Constraints

- All async tests need `@pytest.mark.asyncio`
- Use `tmp_path` fixture for temporary Excel files
- Do NOT mock `ExcelStructureAnalyzer` — test with real files
- Verify Document content contains markdown table formatting (`|`)

---

## Acceptance Criteria

- [ ] Test file created at `packages/ai-parrot-loaders/tests/test_excel_loader.py`
- [ ] All 10 test cases from spec Section 4 are covered
- [ ] All tests pass: `pytest packages/ai-parrot-loaders/tests/test_excel_loader.py -v`
- [ ] Tests use real Excel files via fixtures (no mocking of analyzer)
- [ ] Both `output_mode="sheet"` and `output_mode="row"` are tested

---

## Test Specification

```python
class TestExcelLoaderSheetMode:
    async def test_sheet_mode_one_doc_per_sheet(self, simple_excel):
        """Single-sheet workbook -> exactly 1 Document."""

    async def test_sheet_mode_multi_sheet(self, multi_sheet_excel):
        """3-sheet workbook (1 empty) -> exactly 2 Documents."""

    async def test_sheet_mode_structural_header(self, simple_excel):
        """Document contains sheet name, dimensions, table summary."""

    async def test_sheet_mode_tables_as_markdown(self, simple_excel):
        """Detected tables rendered as markdown with | separators."""

    async def test_sheet_mode_metadata(self, simple_excel):
        """Metadata has content_type: 'sheet', table_count, sheet name."""

    async def test_sheet_mode_max_rows_truncation(self, tmp_path):
        """Tables exceeding max_rows_per_table are truncated."""

    async def test_sheet_mode_empty_sheet_skipped(self, multi_sheet_excel):
        """Empty sheets produce no Documents."""

    async def test_sheet_mode_no_tables_raw_content(self, tmp_path):
        """Sheets with no detected tables produce Document with raw cell content."""


class TestExcelLoaderRowMode:
    async def test_row_mode_backward_compat(self, simple_excel):
        """output_mode='row' produces per-row Documents."""

    async def test_default_mode_is_sheet(self):
        """Default output_mode is 'sheet'."""


class TestExcelLoaderDataFrameInput:
    async def test_dataframe_input_falls_back_to_row(self):
        """DataFrame input uses row mode regardless of output_mode."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/excelloader-migration.spec.md` for full context
2. **Check dependencies** — TASK-638 must be complete
3. **Verify the Codebase Contract** — confirm ExcelLoader has the new params from TASK-638
4. **Update status** in `tasks/.index.json` -> `"in-progress"`
5. **Implement** all test cases per scope
6. **Run tests**: `source .venv/bin/activate && pytest packages/ai-parrot-loaders/tests/test_excel_loader.py -v`
7. **Verify** all acceptance criteria
8. **Move this file** to `tasks/completed/TASK-640-excelloader-unit-tests.md`
9. **Update index** -> `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
