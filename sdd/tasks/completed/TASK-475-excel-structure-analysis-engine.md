# TASK-475: Excel Structure Analysis Engine

**Feature**: datasetmanager-files
**Spec**: `sdd/specs/datasetmanager-files.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 1 from the spec. The Excel Structure Analysis Engine is the
> foundation for all other tasks — it provides the core `openpyxl`-based analysis that
> discovers table structures in complex Excel workbooks using header-row heuristics.

---

## Scope

- Create `CellRegion`, `DetectedTable`, `SheetAnalysis` dataclasses with all properties
- Implement `ExcelStructureAnalyzer` class with:
  - `analyze_workbook()` — analyze all sheets, return `Dict[str, SheetAnalysis]`
  - `_analyze_sheet()` — scan a single sheet for tables and standalone labels
  - `_is_header_row()` — heuristic: 3+ non-empty cells, 40%+ strings, numeric data in row below
  - `_extract_table_from_header()` — expand table boundaries downward (2-empty-row gap stop), detect total rows, look above for section titles
  - `extract_table_as_dataframe()` — extract a detected table as a clean pandas DataFrame
  - `extract_cell_range()` — read raw values from an arbitrary cell range
  - `close()` — close the workbook
- Handle merged cells by reloading the sheet in non-read-only mode
- Use `data_only=True` for calculated values
- `TOTAL_KEYWORDS` set: `total`, `sum`, `subtotal`, `grand total`, `net total`, `totals`, `aggregate`, `overall`
- Write unit tests for the analyzer

**NOT in scope**: Toolkit wrapper (TASK-476), DatasetManager integration (TASK-477), CSV handling (TASK-478).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/excel_analyzer.py` | CREATE | Core analysis engine and data models |
| `tests/tools/test_excel_analyzer.py` | CREATE | Unit tests for analyzer heuristics |

---

## Implementation Notes

### Pattern to Follow

The user provided a complete reference implementation in the spec arguments. Use it as the
starting point, adapting to AI-Parrot conventions:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import openpyxl
import pandas as pd
from openpyxl.utils import get_column_letter


@dataclass
class CellRegion:
    """A rectangular region within a sheet."""
    start_row: int
    start_col: int
    end_row: int
    end_col: int

    @property
    def excel_range(self) -> str:
        sc = get_column_letter(self.start_col)
        ec = get_column_letter(self.end_col)
        return f"{sc}{self.start_row}:{ec}{self.end_row}"

    @property
    def row_count(self) -> int:
        return self.end_row - self.start_row + 1

    @property
    def col_count(self) -> int:
        return self.end_col - self.start_col + 1
```

### Key Constraints

- Use `openpyxl` `read_only=True` for the initial analysis pass (memory efficient)
- Reload in normal mode for merged cell detection and random access extraction
- Use `data_only=True` to get calculated values (not formulas)
- Add logging via `logging.getLogger(__name__)`
- Handle datetime header cells by formatting as `"%b %Y"`
- File-size check: warn in logs if file exceeds 100MB

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — DatasetManager pattern
- `packages/ai-parrot/src/parrot/tools/toolkit.py` — AbstractToolkit base class
- `packages/ai-parrot-loaders/src/parrot_loaders/excel.py` — Existing ExcelLoader (different concern)

---

## Acceptance Criteria

- [ ] `CellRegion`, `DetectedTable`, `SheetAnalysis` dataclasses created with all properties
- [ ] `ExcelStructureAnalyzer` discovers header rows using the 3-cell + numeric-below heuristic
- [ ] Table boundary expansion stops at 2 consecutive empty rows
- [ ] Total rows detected by keyword matching (exact and partial)
- [ ] Section titles extracted from rows above headers (up to 3 rows lookback)
- [ ] Merged cells listed in `SheetAnalysis.merged_cells`
- [ ] `extract_table_as_dataframe()` returns clean DataFrame with optional total-row exclusion
- [ ] `extract_cell_range()` returns raw cell values for arbitrary ranges
- [ ] Multi-table sheets correctly detect all tables
- [ ] All tests pass: `pytest tests/tools/test_excel_analyzer.py -v`

---

## Test Specification

```python
# tests/tools/test_excel_analyzer.py
import pytest
import openpyxl
from parrot.tools.dataset_manager.excel_analyzer import (
    ExcelStructureAnalyzer, DetectedTable, SheetAnalysis, CellRegion
)


@pytest.fixture
def complex_excel_path(tmp_path):
    """Create a test Excel file with multiple stacked tables."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Revenue"
    # Section title
    ws["A1"] = "Roadshow Net Revenue"
    # Table 1: header at row 2
    ws["A2"], ws["B2"], ws["C2"] = "Client", "Jan 2024", "Feb 2024"
    ws["A3"], ws["B3"], ws["C3"] = "Client A", 10000, 12000
    ws["A4"], ws["B4"], ws["C4"] = "Client B", 8000, 9500
    ws["A5"], ws["B5"], ws["C5"] = "Total", 18000, 21500
    # Gap rows 6-7 (empty)
    # Table 2: header at row 8
    ws["A8"] = "EBITDA Summary"
    ws["A9"], ws["B9"], ws["C9"] = "Division", "Q1", "Q2"
    ws["A10"], ws["B10"], ws["C10"] = "North", 5000, 6200
    ws["A11"], ws["B11"], ws["C11"] = "South", 3200, 4100
    path = tmp_path / "test_complex.xlsx"
    wb.save(path)
    return path


@pytest.fixture
def simple_excel_path(tmp_path):
    """Single-table Excel file."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"], ws["B1"], ws["C1"] = "Name", "Age", "City"
    ws["A2"], ws["B2"], ws["C2"] = "Alice", 30, "NYC"
    ws["A3"], ws["B3"], ws["C3"] = "Bob", 25, "LA"
    path = tmp_path / "test_simple.xlsx"
    wb.save(path)
    return path


class TestCellRegion:
    def test_excel_range(self):
        region = CellRegion(start_row=2, start_col=1, end_row=5, end_col=3)
        assert region.excel_range == "A2:C5"

    def test_row_count(self):
        region = CellRegion(start_row=2, start_col=1, end_row=5, end_col=3)
        assert region.row_count == 4

    def test_col_count(self):
        region = CellRegion(start_row=2, start_col=1, end_row=5, end_col=3)
        assert region.col_count == 3


class TestExcelStructureAnalyzer:
    def test_analyze_simple_workbook(self, simple_excel_path):
        analyzer = ExcelStructureAnalyzer(simple_excel_path)
        result = analyzer.analyze_workbook()
        assert "Sheet" in result
        sheet = result["Sheet"]
        assert len(sheet.tables) >= 1
        assert sheet.tables[0].columns[0] == "Name"
        analyzer.close()

    def test_multi_table_detection(self, complex_excel_path):
        analyzer = ExcelStructureAnalyzer(complex_excel_path)
        result = analyzer.analyze_workbook()
        sheet = result["Revenue"]
        assert len(sheet.tables) >= 2
        analyzer.close()

    def test_total_row_detection(self, complex_excel_path):
        analyzer = ExcelStructureAnalyzer(complex_excel_path)
        result = analyzer.analyze_workbook()
        sheet = result["Revenue"]
        table1 = sheet.tables[0]
        assert table1.has_total_row is True
        analyzer.close()

    def test_section_title_detection(self, complex_excel_path):
        analyzer = ExcelStructureAnalyzer(complex_excel_path)
        result = analyzer.analyze_workbook()
        sheet = result["Revenue"]
        table1 = sheet.tables[0]
        assert table1.section_label is not None
        assert "Roadshow" in table1.section_label
        analyzer.close()

    def test_extract_table_as_dataframe(self, complex_excel_path):
        analyzer = ExcelStructureAnalyzer(complex_excel_path)
        result = analyzer.analyze_workbook()
        table = result["Revenue"].tables[0]
        df = analyzer.extract_table_as_dataframe("Revenue", table, include_totals=False)
        assert len(df) >= 2  # At least 2 data rows (excluding total)
        assert "Client" in df.columns or "Client" == df.columns[0]
        analyzer.close()

    def test_extract_table_with_totals(self, complex_excel_path):
        analyzer = ExcelStructureAnalyzer(complex_excel_path)
        result = analyzer.analyze_workbook()
        table = result["Revenue"].tables[0]
        df_no_totals = analyzer.extract_table_as_dataframe("Revenue", table, include_totals=False)
        df_with_totals = analyzer.extract_table_as_dataframe("Revenue", table, include_totals=True)
        assert len(df_with_totals) > len(df_no_totals)
        analyzer.close()

    def test_extract_cell_range(self, simple_excel_path):
        analyzer = ExcelStructureAnalyzer(simple_excel_path)
        rows = analyzer.extract_cell_range("Sheet", "A1:C2")
        assert len(rows) == 2
        assert rows[0][0] == "Name"
        analyzer.close()

    def test_empty_sheet(self, tmp_path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Empty"
        path = tmp_path / "empty.xlsx"
        wb.save(path)
        analyzer = ExcelStructureAnalyzer(path)
        result = analyzer.analyze_workbook()
        assert result["Empty"].total_rows == 0
        assert len(result["Empty"].tables) == 0
        analyzer.close()

    def test_to_summary(self, complex_excel_path):
        analyzer = ExcelStructureAnalyzer(complex_excel_path)
        result = analyzer.analyze_workbook()
        summary = result["Revenue"].to_summary()
        assert "Revenue" in summary
        assert "Detected tables:" in summary
        analyzer.close()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-files.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** the `ExcelStructureAnalyzer` class and all data models using the reference code from the spec as a starting point
5. **Run tests**: `pytest tests/tools/test_excel_analyzer.py -v`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
