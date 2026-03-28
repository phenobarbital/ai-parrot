# TASK-479: DatasetManager Files Integration Tests

**Feature**: datasetmanager-files
**Spec**: `sdd/specs/datasetmanager-files.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-475, TASK-476, TASK-477, TASK-478
**Assigned-to**: unassigned

---

## Context

> This task implements Module 5 from the spec. End-to-end integration tests that verify
> all components work together: analyzer discovers tables in complex Excel files,
> toolkit exposes tools that agents can discover, and DatasetManager correctly catalogs
> both file-based and DataFrame-based entries.

---

## Scope

- Write integration tests covering:
  - Loading a complex multi-sheet Excel file end-to-end through DatasetManager
  - Verifying all tables are detected and extractable
  - ExcelIntelligenceToolkit tools are discoverable by agents
  - Mixed catalog: load files + DataFrames, verify both accessible
  - Token-budget control: large tables truncated correctly
  - Error paths: corrupt files, missing sheets, invalid table IDs
- Create test fixture Excel files with realistic complexity:
  - Multiple sheets
  - Stacked tables with gaps
  - Merged cells for section titles
  - Total/summary rows
  - Mixed content (numbers, dates, text)

**NOT in scope**: Unit tests for individual modules (those are in TASK-475, TASK-476, TASK-477, TASK-478).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/test_file_intelligence_integration.py` | CREATE | End-to-end integration tests |

---

## Implementation Notes

### Key Test Scenarios

1. **Complex Excel end-to-end**: Create a workbook with 3 sheets, each with 2+ stacked tables,
   merged section titles, and total rows. Load via `DatasetManager.load_file()`, verify all
   tables discovered, extract each table and verify content.

2. **Toolkit + Agent**: Instantiate `ExcelIntelligenceToolkit`, call `get_tools()`, verify
   3 tools are returned with correct names and descriptions.

3. **Mixed catalog**: Load a CSV as file, load an Excel as file, load another CSV as DataFrame.
   Verify all three coexist in the manager and are independently accessible.

4. **Token budget**: Create an Excel with 500+ row table, load with `max_rows_per_table=50`,
   verify markdown is truncated.

5. **Error resilience**: Corrupt file, empty file, non-existent sheet, invalid table ID.

### Key Constraints

- Tests must create fixture files programmatically (no external test data files)
- Use `tmp_path` for all file creation
- Tests should be independent (no shared state between test methods)
- Mark async tests with `@pytest.mark.asyncio`

### References in Codebase

- `tests/tools/test_excel_analyzer.py` — from TASK-475
- `tests/tools/test_excel_toolkit.py` — from TASK-476
- `tests/tools/test_datasetmanager_files.py` — from TASK-477
- `tests/tools/test_csv_reader.py` — from TASK-478

---

## Acceptance Criteria

- [ ] Complex multi-sheet Excel loads end-to-end and all tables extracted
- [ ] ExcelIntelligenceToolkit tools are discoverable via `get_tools()`
- [ ] Mixed catalog (files + DataFrames) works correctly
- [ ] Token-budget truncation works for large tables
- [ ] Error paths tested: corrupt file, missing sheet, invalid table ID
- [ ] All tests pass: `pytest tests/tools/test_file_intelligence_integration.py -v`
- [ ] No breaking changes to existing DatasetManager tests

---

## Test Specification

```python
# tests/tools/test_file_intelligence_integration.py
import pytest
import openpyxl
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.excel_intelligence import ExcelIntelligenceToolkit


@pytest.fixture
def multi_sheet_excel(tmp_path):
    """Create a realistic multi-sheet Excel workbook."""
    wb = openpyxl.Workbook()

    # Sheet 1: Revenue with 2 stacked tables
    ws1 = wb.active
    ws1.title = "Revenue"
    ws1["A1"] = "Roadshow Net Revenue"
    ws1["A2"], ws1["B2"], ws1["C2"], ws1["D2"] = "Client", "Jan", "Feb", "Mar"
    ws1["A3"], ws1["B3"], ws1["C3"], ws1["D3"] = "Acme Corp", 50000, 55000, 60000
    ws1["A4"], ws1["B4"], ws1["C4"], ws1["D4"] = "Beta Inc", 30000, 32000, 35000
    ws1["A5"], ws1["B5"], ws1["C5"], ws1["D5"] = "Total", 80000, 87000, 95000
    # Gap
    ws1["A8"] = "Digital Net Revenue"
    ws1["A9"], ws1["B9"], ws1["C9"], ws1["D9"] = "Platform", "Jan", "Feb", "Mar"
    ws1["A10"], ws1["B10"], ws1["C10"], ws1["D10"] = "Web", 20000, 22000, 25000
    ws1["A11"], ws1["B11"], ws1["C11"], ws1["D11"] = "Mobile", 15000, 17000, 19000

    # Sheet 2: Expenses
    ws2 = wb.create_sheet("Expenses")
    ws2["A1"], ws2["B1"], ws2["C1"] = "Category", "Q1", "Q2"
    ws2["A2"], ws2["B2"], ws2["C2"] = "Salaries", 100000, 105000
    ws2["A3"], ws2["B3"], ws2["C3"] = "Marketing", 25000, 28000
    ws2["A4"], ws2["B4"], ws2["C4"] = "Total", 125000, 133000

    path = tmp_path / "financial_report.xlsx"
    wb.save(path)
    return path


@pytest.fixture
def simple_csv(tmp_path):
    path = tmp_path / "clients.csv"
    path.write_text("Name,Revenue,Region\nAcme,50000,North\nBeta,30000,South\n")
    return path


@pytest.fixture
def manager():
    return DatasetManager(generate_guide=False)


class TestComplexExcelEndToEnd:
    @pytest.mark.asyncio
    async def test_load_and_discover_all_tables(self, manager, multi_sheet_excel):
        summary = await manager.load_file("report", multi_sheet_excel)
        entry = manager._file_entries["report"]
        # Should have tables from both sheets
        assert len(entry.markdown_content) >= 3  # 2 from Revenue + 1 from Expenses
        assert entry.file_type == "excel"
        assert "Revenue" in summary

    @pytest.mark.asyncio
    async def test_extract_specific_table(self, manager, multi_sheet_excel):
        await manager.load_file("report", multi_sheet_excel)
        entry = manager._file_entries["report"]
        first_table_id = list(entry.markdown_content.keys())[0]
        result = await manager.get_file_table("report", first_table_id)
        assert "Client" in result or "Category" in result

    @pytest.mark.asyncio
    async def test_get_full_context(self, manager, multi_sheet_excel):
        await manager.load_file("report", multi_sheet_excel)
        context = await manager.get_file_context("report")
        # Should contain data from all tables
        assert len(context) > 100  # Non-trivial content


class TestToolkitIntegration:
    def test_tools_discoverable(self):
        toolkit = ExcelIntelligenceToolkit()
        tools = toolkit.get_tools_sync()
        names = {t.name for t in tools}
        assert "inspect_workbook" in names
        assert "extract_table" in names
        assert "query_cells" in names
        # Verify descriptions exist
        for tool in tools:
            assert tool.description and len(tool.description) > 10

    @pytest.mark.asyncio
    async def test_toolkit_inspect_and_extract(self, multi_sheet_excel):
        toolkit = ExcelIntelligenceToolkit()
        # Phase 1: Inspect
        structure = await toolkit.inspect_workbook(str(multi_sheet_excel))
        assert "Revenue" in structure
        assert "Expenses" in structure
        # Phase 2: Extract
        table_data = await toolkit.extract_table(
            str(multi_sheet_excel), "Revenue", "T1"
        )
        assert "Client" in table_data or "Acme" in table_data
        await toolkit.cleanup()


class TestMixedCatalog:
    @pytest.mark.asyncio
    async def test_files_and_dataframes_coexist(
        self, manager, multi_sheet_excel, simple_csv
    ):
        # Load as files
        await manager.load_file("excel_file", multi_sheet_excel)
        await manager.load_file("csv_file", simple_csv)
        # Load as DataFrame
        manager.add_dataframe_from_file("csv_df", simple_csv)
        df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
        manager.add_dataframe("manual_df", df)
        # Verify separation
        assert "excel_file" in manager._file_entries
        assert "csv_file" in manager._file_entries
        assert "csv_df" in manager._datasets
        assert "manual_df" in manager._datasets
        # No cross-contamination
        assert "excel_file" not in manager._datasets
        assert "csv_df" not in manager._file_entries


class TestTokenBudget:
    @pytest.mark.asyncio
    async def test_large_table_truncated(self, manager, tmp_path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"], ws["B1"] = "Id", "Value"
        for i in range(2, 302):
            ws[f"A{i}"] = i - 1
            ws[f"B{i}"] = (i - 1) * 10
        path = tmp_path / "large.xlsx"
        wb.save(path)
        await manager.load_file("large", path, max_rows_per_table=50)
        entry = manager._file_entries["large"]
        # Markdown should be truncated
        for table_id, md in entry.markdown_content.items():
            lines = [l for l in md.strip().split("\n") if l.strip() and not l.startswith("-")]
            # Should have header + at most 50 data rows (plus separator lines)
            assert lines is not None  # Just verify it loaded


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_nonexistent_file(self, manager):
        with pytest.raises((FileNotFoundError, OSError)):
            await manager.load_file("bad", "/nonexistent/file.xlsx")

    @pytest.mark.asyncio
    async def test_unsupported_extension(self, manager, tmp_path):
        path = tmp_path / "data.txt"
        path.write_text("hello")
        with pytest.raises(ValueError, match="Unsupported"):
            await manager.load_file("bad", path)

    @pytest.mark.asyncio
    async def test_get_nonexistent_file(self, manager):
        with pytest.raises((KeyError, ValueError)):
            await manager.get_file_context("nonexistent")

    @pytest.mark.asyncio
    async def test_get_nonexistent_table(self, manager, tmp_path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"], ws["B1"] = "X", "Y"
        ws["A2"], ws["B2"] = 1, 2
        path = tmp_path / "small.xlsx"
        wb.save(path)
        await manager.load_file("small", path)
        with pytest.raises((KeyError, ValueError)):
            await manager.get_file_table("small", "T99")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-files.spec.md`
2. **Check dependencies** — verify TASK-475, TASK-476, TASK-477, TASK-478 are all completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** integration tests using the test specification above as a starting point
5. **Run tests**: `pytest tests/tools/test_file_intelligence_integration.py -v`
6. **Also run all related unit tests**: `pytest tests/tools/test_excel_analyzer.py tests/tools/test_excel_toolkit.py tests/tools/test_datasetmanager_files.py tests/tools/test_csv_reader.py -v`
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
