# TASK-476: ExcelIntelligenceToolkit

**Feature**: datasetmanager-files
**Spec**: `sdd/specs/datasetmanager-files.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-475
**Assigned-to**: unassigned

---

## Context

> This task implements Module 2 from the spec. The ExcelIntelligenceToolkit wraps the
> ExcelStructureAnalyzer (TASK-475) as an AbstractToolkit subclass, exposing three
> async LLM-callable tools: `inspect_workbook`, `extract_table`, `query_cells`.
> Per the resolved open question, this toolkit will be auto-registered as a dependency
> of DatasetManager.

---

## Scope

- Create `ExcelIntelligenceToolkit(AbstractToolkit)` with:
  - `async def inspect_workbook(file_path: str, sheet_name: Optional[str] = None) -> str` — Returns human-readable structural map of workbook
  - `async def extract_table(file_path: str, sheet_name: str, table_id: str, include_totals: bool = False, max_rows: int = 200, output_format: str = "markdown") -> str` — Returns clean tabular data
  - `async def query_cells(file_path: str, sheet_name: str, cell_range: str) -> str` — Returns raw cell values
- Manage analyzer and analysis caches (`_analyzer_cache`, `_analysis_cache`)
- Implement `async def cleanup()` to close all cached workbooks
- Handle error cases: file not found, sheet not found, table_id not found
- Respect `max_rows` parameter for token-budget control
- Support output formats: markdown, csv, json
- Write unit tests

**NOT in scope**: DatasetManager integration (TASK-477), CSV handling (TASK-478).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/excel_intelligence.py` | CREATE | ExcelIntelligenceToolkit implementation |
| `tests/tools/test_excel_toolkit.py` | CREATE | Unit tests for toolkit tools |

---

## Implementation Notes

### Pattern to Follow

Follow the `AbstractToolkit` pattern — all public async methods become LLM tools automatically:

```python
from typing import Optional
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.dataset_manager.excel_analyzer import (
    ExcelStructureAnalyzer, SheetAnalysis
)


class ExcelIntelligenceToolkit(AbstractToolkit):
    """Toolkit for intelligent Excel file analysis.

    Provides LLM agents with tools to analyze complex Excel workbooks:
    1. inspect_workbook — structural map of sheets and tables
    2. extract_table — clean tabular data for a specific table
    3. query_cells — raw cell values for arbitrary ranges
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._analyzer_cache: dict[str, ExcelStructureAnalyzer] = {}
        self._analysis_cache: dict[str, dict[str, SheetAnalysis]] = {}

    async def inspect_workbook(
        self, file_path: str, sheet_name: Optional[str] = None
    ) -> str:
        """Analyze the structure of an Excel workbook.

        Returns a map showing all sheets, detected tables with IDs,
        column names, and ranges. Use table IDs with extract_table.

        Args:
            file_path: Path to the Excel file (.xlsx, .xls)
            sheet_name: Specific sheet to analyze. If None, analyzes all.
        """
        ...

    async def extract_table(
        self,
        file_path: str,
        sheet_name: str,
        table_id: str,
        include_totals: bool = False,
        max_rows: int = 200,
        output_format: str = "markdown",
    ) -> str:
        """Extract a specific table as clean tabular data.

        Use table_id from inspect_workbook results.

        Args:
            file_path: Path to the Excel file
            sheet_name: Name of the sheet containing the table
            table_id: Table ID (e.g., 'T1', 'T2')
            include_totals: Include total/summary rows
            max_rows: Maximum rows to return
            output_format: 'markdown', 'csv', or 'json'
        """
        ...

    async def query_cells(
        self, file_path: str, sheet_name: str, cell_range: str
    ) -> str:
        """Read raw cell values from a specific range.

        Args:
            file_path: Path to the Excel file
            sheet_name: Sheet name
            cell_range: Excel-style range (e.g., 'B10:I16')
        """
        ...

    async def cleanup(self) -> None:
        """Close all cached workbooks."""
        ...
```

### Key Constraints

- All tool methods must be `async def` (AbstractToolkit requirement)
- The underlying openpyxl work is synchronous but fast — no need for `asyncio.to_thread()` unless profiling shows it's needed
- Cache analyzers by file path to avoid re-parsing the same file
- Docstrings are critical — they become the LLM's tool descriptions
- Type hints on all parameters — they become the tool's JSON schema
- Use `self.logger` for warnings and errors

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/toolkit.py` — `AbstractToolkit` base class
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — DatasetManager as toolkit example
- `packages/ai-parrot/src/parrot/tools/dataset_manager/excel_analyzer.py` — From TASK-475

---

## Acceptance Criteria

- [ ] `ExcelIntelligenceToolkit` inherits from `AbstractToolkit`
- [ ] `inspect_workbook` returns human-readable structural map with table IDs
- [ ] `extract_table` returns clean markdown/csv/json for a given table_id
- [ ] `extract_table` respects `max_rows` parameter and adds truncation note
- [ ] `query_cells` returns raw cell values for arbitrary ranges
- [ ] Error cases handled: file not found, sheet not found, table_id not found
- [ ] Analyzer caching works (same file not re-parsed)
- [ ] `cleanup()` closes all cached workbooks
- [ ] Tools are auto-generated by `AbstractToolkit.get_tools()`
- [ ] All tests pass: `pytest tests/tools/test_excel_toolkit.py -v`

---

## Test Specification

```python
# tests/tools/test_excel_toolkit.py
import pytest
import openpyxl
from parrot.tools.excel_intelligence import ExcelIntelligenceToolkit


@pytest.fixture
def complex_excel_path(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Revenue"
    ws["A1"] = "Roadshow Net Revenue"
    ws["A2"], ws["B2"], ws["C2"] = "Client", "Jan 2024", "Feb 2024"
    ws["A3"], ws["B3"], ws["C3"] = "Client A", 10000, 12000
    ws["A4"], ws["B4"], ws["C4"] = "Client B", 8000, 9500
    ws["A5"], ws["B5"], ws["C5"] = "Total", 18000, 21500
    ws["A9"], ws["B9"], ws["C9"] = "Division", "Q1", "Q2"
    ws["A10"], ws["B10"], ws["C10"] = "North", 5000, 6200
    path = tmp_path / "test.xlsx"
    wb.save(path)
    return path


@pytest.fixture
def toolkit():
    return ExcelIntelligenceToolkit()


class TestInspectWorkbook:
    @pytest.mark.asyncio
    async def test_returns_structural_map(self, toolkit, complex_excel_path):
        result = await toolkit.inspect_workbook(str(complex_excel_path))
        assert "Revenue" in result
        assert "T1" in result

    @pytest.mark.asyncio
    async def test_specific_sheet(self, toolkit, complex_excel_path):
        result = await toolkit.inspect_workbook(
            str(complex_excel_path), sheet_name="Revenue"
        )
        assert "Revenue" in result

    @pytest.mark.asyncio
    async def test_invalid_sheet(self, toolkit, complex_excel_path):
        result = await toolkit.inspect_workbook(
            str(complex_excel_path), sheet_name="NonExistent"
        )
        assert "not found" in result


class TestExtractTable:
    @pytest.mark.asyncio
    async def test_extract_markdown(self, toolkit, complex_excel_path):
        # First inspect to get table IDs
        await toolkit.inspect_workbook(str(complex_excel_path))
        result = await toolkit.extract_table(
            str(complex_excel_path), "Revenue", "T1"
        )
        assert "Client" in result

    @pytest.mark.asyncio
    async def test_extract_csv(self, toolkit, complex_excel_path):
        await toolkit.inspect_workbook(str(complex_excel_path))
        result = await toolkit.extract_table(
            str(complex_excel_path), "Revenue", "T1", output_format="csv"
        )
        assert "Client" in result

    @pytest.mark.asyncio
    async def test_invalid_table_id(self, toolkit, complex_excel_path):
        await toolkit.inspect_workbook(str(complex_excel_path))
        result = await toolkit.extract_table(
            str(complex_excel_path), "Revenue", "T99"
        )
        assert "not found" in result


class TestQueryCells:
    @pytest.mark.asyncio
    async def test_query_range(self, toolkit, complex_excel_path):
        result = await toolkit.query_cells(
            str(complex_excel_path), "Revenue", "A1:C3"
        )
        assert "Roadshow" in result or "Client" in result


class TestToolGeneration:
    def test_tools_auto_generated(self, toolkit):
        tools = toolkit.get_tools_sync()
        tool_names = [t.name for t in tools]
        assert "inspect_workbook" in tool_names
        assert "extract_table" in tool_names
        assert "query_cells" in tool_names


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup(self, toolkit, complex_excel_path):
        await toolkit.inspect_workbook(str(complex_excel_path))
        assert len(toolkit._analyzer_cache) > 0
        await toolkit.cleanup()
        assert len(toolkit._analyzer_cache) == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-files.spec.md`
2. **Check dependencies** — verify TASK-475 is completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** `packages/ai-parrot/src/parrot/tools/toolkit.py` to understand AbstractToolkit
5. **Implement** ExcelIntelligenceToolkit with all 3 tools + cleanup
6. **Run tests**: `pytest tests/tools/test_excel_toolkit.py -v`
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
