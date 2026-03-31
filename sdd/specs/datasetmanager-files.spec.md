# Feature Specification: DatasetManager File Intelligence

**Feature ID**: FEAT-068
**Date**: 2026-03-28
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

DatasetManager currently handles files (CSV, Excel) by converting them into pandas DataFrames
via `add_dataframe_from_file()`. This works well for simple, rectangular data but fails for
complex real-world Excel workbooks that contain:

- **Multiple tables stacked vertically or side-by-side** within a single sheet
- **Merged cells** used as section titles (e.g., "Roadshow Net Revenue")
- **Mixed data regions** (revenue tables + EBITDA tables + overhead tables on one sheet)
- **Summary/total rows** interspersed with data
- **Non-rectangular layouts** that break `pd.read_excel()`

When an LLM agent needs to answer questions about such files, converting to a single DataFrame
loses structural context. The agent needs the file's **structural layout** — what tables exist,
where they are, what their headers are — so it can request specific tables as clean markdown
to include directly in the LLM context.

Additionally, CSV files with complex structures (multi-header rows, mixed delimiters) also
benefit from a markdown-first approach rather than forced DataFrame conversion.

### Goals

- Add a `load_file()` async method to DatasetManager that ingests CSV/Excel files and
  produces a **structural map + markdown representation** instead of (or in addition to) DataFrames
- Create an `ExcelIntelligenceToolkit` (inheriting `AbstractToolkit`) that exposes
  `inspect_workbook`, `extract_table`, and `query_cells` as LLM-callable tools
- Support CSV files via simple markdown conversion (using pandas `to_markdown()` or direct parsing)
- Ensure the structural analysis and extracted markdown can be passed directly as LLM context
- Integrate with existing DatasetManager catalog so files appear alongside DataFrame datasets

### Non-Goals (explicitly out of scope)

- Replacing the existing `add_dataframe_from_file()` — it remains for users who want DataFrames
- Supporting non-tabular file formats (PDF, DOCX, images) — those are handled by `parrot/loaders/`
- Real-time streaming of large files — files are loaded in full, with `max_rows` truncation
- Chart/image extraction from Excel — only cell data is extracted

---

## 2. Architectural Design

### Overview

Two new components work together:

1. **`ExcelStructureAnalyzer`** — A pure-Python engine (using `openpyxl`) that scans Excel
   workbooks and discovers table structures via header-row heuristics. Produces `SheetAnalysis`
   and `DetectedTable` data models describing the structural layout.

2. **`ExcelIntelligenceToolkit`** — An `AbstractToolkit` subclass that wraps the analyzer
   and exposes three LLM-callable tools: `inspect_workbook`, `extract_table`, `query_cells`.

3. **`DatasetManager.load_file()`** — A new async method that:
   - Detects file type (CSV vs Excel)
   - For Excel: runs structural analysis, stores the analysis + per-table markdown in a
     `FileEntry` alongside the existing `DatasetEntry` catalog
   - For CSV: converts to markdown directly
   - Returns a structural summary string suitable for LLM context

### Component Diagram

```
User / Agent
     │
     ▼
DatasetManager.load_file(name, path)
     │
     ├── CSV? ──→ pandas.read_csv() ──→ df.to_markdown() ──→ FileEntry
     │
     └── Excel? ──→ ExcelStructureAnalyzer
                        │
                        ├── analyze_workbook() ──→ SheetAnalysis[]
                        │                              │
                        │                              └── DetectedTable[]
                        │
                        ├── extract_table_as_dataframe() ──→ df.to_markdown()
                        │
                        └── extract_cell_range() ──→ raw values
                              │
                              ▼
                    ExcelIntelligenceToolkit (AbstractToolkit)
                        ├── inspect_workbook()   ← LLM tool
                        ├── extract_table()      ← LLM tool
                        └── query_cells()        ← LLM tool
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DatasetManager` | extends | New `load_file()` method, new `_file_entries` dict |
| `AbstractToolkit` | inherits | `ExcelIntelligenceToolkit` is a standalone toolkit |
| `DatasetEntry` | sibling | New `FileEntry` dataclass for file-based datasets |
| `parrot_loaders/excel.py` | none | Separate concern — loaders produce Documents, this produces structured markdown |

### Data Models

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

@dataclass
class CellRegion:
    """A rectangular region within a sheet."""
    start_row: int
    start_col: int
    end_row: int
    end_col: int

    @property
    def excel_range(self) -> str: ...
    @property
    def row_count(self) -> int: ...
    @property
    def col_count(self) -> int: ...


@dataclass
class DetectedTable:
    """A table discovered within a sheet."""
    table_id: str
    title: Optional[str]
    header_row: int
    data_start_row: int
    data_end_row: int
    start_col: int
    end_col: int
    columns: List[str]
    row_count: int
    has_total_row: bool = False
    section_label: Optional[str] = None

    @property
    def excel_range(self) -> str: ...
    def to_summary(self) -> str: ...


@dataclass
class SheetAnalysis:
    """Complete structural analysis of one sheet."""
    name: str
    total_rows: int
    total_cols: int
    tables: List[DetectedTable]
    merged_cells: List[str]
    standalone_labels: List[Tuple[str, str]]

    def to_summary(self) -> str: ...


@dataclass
class FileEntry:
    """A file loaded into DatasetManager (not a DataFrame)."""
    name: str
    path: Path
    file_type: str  # "csv" | "excel"
    markdown_content: Dict[str, str]  # table_id -> markdown string
    structural_summary: str  # Human-readable summary for LLM
    analysis: Optional[Dict[str, SheetAnalysis]] = None  # Excel only
    metadata: Optional[Dict[str, Any]] = None
```

### New Public Interfaces

```python
# On DatasetManager:
class DatasetManager(AbstractToolkit):
    async def load_file(
        self,
        name: str,
        path: Union[str, Path],
        metadata: Optional[Dict[str, Any]] = None,
        max_rows_per_table: int = 200,
        output_format: str = "markdown",
    ) -> str:
        """Load a CSV or Excel file for LLM context.

        Unlike add_dataframe_from_file() which converts to DataFrame,
        this method preserves the file's structural layout and produces
        clean markdown that can be passed directly to the LLM.

        Args:
            name: Identifier for the file in the catalog.
            path: Path to CSV or Excel file.
            metadata: Optional metadata.
            max_rows_per_table: Max rows per extracted table (token budget).
            output_format: 'markdown', 'csv', or 'json'.

        Returns:
            Structural summary string.
        """

    async def get_file_context(self, name: str) -> str:
        """Get the full markdown context for a loaded file."""

    async def get_file_table(self, name: str, table_id: str) -> str:
        """Get markdown for a specific table from a loaded file."""


# Standalone toolkit:
class ExcelIntelligenceToolkit(AbstractToolkit):
    async def inspect_workbook(
        self, file_path: str, sheet_name: Optional[str] = None
    ) -> str:
        """Analyze workbook structure. Returns map of sheets and tables."""

    async def extract_table(
        self, file_path: str, sheet_name: str, table_id: str,
        include_totals: bool = False, max_rows: int = 200,
        output_format: str = "markdown"
    ) -> str:
        """Extract a specific discovered table as clean tabular data."""

    async def query_cells(
        self, file_path: str, sheet_name: str, cell_range: str
    ) -> str:
        """Read raw cell values from a specific range."""
```

---

## 3. Module Breakdown

### Module 1: Excel Structure Analysis Engine

- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/excel_analyzer.py`
- **Responsibility**: Core Excel analysis engine using `openpyxl`.
  Contains `CellRegion`, `DetectedTable`, `SheetAnalysis` data models and
  `ExcelStructureAnalyzer` class with header-row heuristic detection,
  table boundary expansion, merged cell handling, and total-row detection.
- **Depends on**: `openpyxl`, `pandas` (for DataFrame extraction)

### Module 2: ExcelIntelligenceToolkit

- **Path**: `packages/ai-parrot/src/parrot/tools/excel_intelligence.py`
- **Responsibility**: `AbstractToolkit` subclass wrapping the analyzer.
  Exposes `inspect_workbook`, `extract_table`, `query_cells` as async
  LLM-callable tools. Manages analyzer and analysis caches. Handles
  error messages and token-budget truncation.
- **Depends on**: Module 1, `AbstractToolkit`

### Module 3: DatasetManager File Loading

- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (modify)
- **Responsibility**: Add `load_file()`, `get_file_context()`, `get_file_table()`
  methods to `DatasetManager`. Introduce `FileEntry` dataclass and `_file_entries`
  storage. CSV files are handled directly via pandas `to_markdown()`.
  Excel files delegate to `ExcelStructureAnalyzer`. Update `df_guide` generation
  to include file entries.
- **Depends on**: Module 1, existing DatasetManager

### Module 4: CSV Markdown Conversion

- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/csv_reader.py`
- **Responsibility**: Lightweight CSV-to-markdown converter. Handles edge cases:
  multi-header rows, encoding detection, large files (truncation with row count).
  Returns clean markdown string. Simpler than Excel — no structural analysis needed.
- **Depends on**: `pandas`

### Module 5: Tests

- **Path**: `tests/tools/test_excel_analyzer.py`, `tests/tools/test_excel_toolkit.py`,
  `tests/tools/test_datasetmanager_files.py`
- **Responsibility**: Unit tests for analyzer heuristics, toolkit tool methods,
  and DatasetManager integration. Uses fixture Excel/CSV files.
- **Depends on**: Modules 1-4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_header_row_detection` | Module 1 | Detects rows with 3+ string cells followed by numeric data below |
| `test_table_boundary_expansion` | Module 1 | Correctly finds data_end_row with 2-empty-row gap detection |
| `test_total_row_detection` | Module 1 | Identifies rows containing "Total", "Subtotal", etc. |
| `test_merged_cell_handling` | Module 1 | Reads merged cells as section titles |
| `test_multi_table_sheet` | Module 1 | Discovers multiple stacked tables in one sheet |
| `test_inspect_workbook_output` | Module 2 | Returns human-readable structural map |
| `test_extract_table_markdown` | Module 2 | Returns clean markdown table for a given table_id |
| `test_extract_table_csv` | Module 2 | Returns CSV format when requested |
| `test_extract_table_truncation` | Module 2 | Respects max_rows parameter |
| `test_query_cells_range` | Module 2 | Returns raw cell values for arbitrary range |
| `test_load_file_csv` | Module 3 | Loads CSV and produces markdown |
| `test_load_file_excel` | Module 3 | Loads Excel and produces structural summary + markdown |
| `test_get_file_context` | Module 3 | Returns full markdown for a loaded file |
| `test_get_file_table` | Module 3 | Returns specific table markdown by ID |
| `test_csv_markdown_encoding` | Module 4 | Handles UTF-8 and Latin-1 CSV files |
| `test_csv_markdown_truncation` | Module 4 | Truncates at max_rows with note |

### Integration Tests

| Test | Description |
|---|---|
| `test_load_complex_excel_end_to_end` | Load a multi-sheet Excel with stacked tables, verify all tables detected |
| `test_toolkit_with_agent` | Register ExcelIntelligenceToolkit with an agent, verify tools are discoverable |
| `test_dataset_manager_mixed` | Load both DataFrame and file entries, verify catalog lists both |

### Test Data / Fixtures

```python
@pytest.fixture
def complex_excel_path(tmp_path):
    """Create a test Excel file with multiple stacked tables."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Revenue"
    # Table 1: header at row 2, data rows 3-7
    ws["A1"] = "Roadshow Net Revenue"
    ws["A2"], ws["B2"], ws["C2"] = "Client", "Jan 2024", "Feb 2024"
    ws["A3"], ws["B3"], ws["C3"] = "Client A", 10000, 12000
    ws["A4"], ws["B4"], ws["C4"] = "Client B", 8000, 9500
    ws["A5"], ws["B5"], ws["C5"] = "Total", 18000, 21500
    # Gap row 6-7
    # Table 2: header at row 8
    ws["A8"] = "EBITDA Summary"
    ws["A9"], ws["B9"], ws["C9"] = "Division", "Q1", "Q2"
    ws["A10"], ws["B10"], ws["C10"] = "North", 5000, 6200
    ws["A11"], ws["B11"], ws["C11"] = "South", 3200, 4100
    path = tmp_path / "test_complex.xlsx"
    wb.save(path)
    return path

@pytest.fixture
def simple_csv_path(tmp_path):
    """Create a simple test CSV file."""
    path = tmp_path / "test.csv"
    path.write_text("Name,Age,City\nAlice,30,NYC\nBob,25,LA\n")
    return path
```

---

## 5. Acceptance Criteria

- [ ] `ExcelStructureAnalyzer` discovers tables in multi-table Excel sheets
- [ ] `ExcelIntelligenceToolkit` exposes 3 async tools: `inspect_workbook`, `extract_table`, `query_cells`
- [ ] `ExcelIntelligenceToolkit` inherits from `AbstractToolkit` and tools are auto-generated
- [ ] `DatasetManager.load_file()` loads CSV files and returns markdown
- [ ] `DatasetManager.load_file()` loads Excel files, runs structural analysis, and stores per-table markdown
- [ ] `DatasetManager.get_file_context()` returns full markdown context for a loaded file
- [ ] `DatasetManager.get_file_table()` returns specific table markdown by ID
- [ ] File entries appear in DatasetManager catalog alongside DataFrame entries
- [ ] Token-budget control via `max_rows_per_table` parameter
- [ ] Total/summary rows are detected and optionally excluded
- [ ] Merged cells are handled gracefully (used as section titles)
- [ ] All unit tests pass: `pytest tests/tools/test_excel_analyzer.py tests/tools/test_excel_toolkit.py tests/tools/test_datasetmanager_files.py -v`
- [ ] No breaking changes to existing `add_dataframe_from_file()` or DatasetManager API
- [ ] `openpyxl` and `pandas` are the only new/existing dependencies used

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- **Async toolkit methods**: All tools in `ExcelIntelligenceToolkit` must be `async def`
  (required by `AbstractToolkit` auto-generation). The underlying openpyxl work is sync
  but lightweight, so wrapping in `asyncio.to_thread()` is optional for large files.
- **Pydantic models**: Use dataclasses for internal data models (`DetectedTable`, etc.)
  and Pydantic `BaseModel` only for tool argument schemas if needed.
- **Logging**: Use `self.logger` throughout. Log warnings for sheets with no detected tables.
- **The provided ExcelIntelligenceToolkit code** in the user's description should be used as
  the reference implementation. Adapt it to:
  - Inherit from `AbstractToolkit` properly
  - Make tool methods `async`
  - Follow AI-Parrot conventions (type hints, docstrings)

### Header-Row Heuristic

The table detection algorithm:
1. Scan each row — a "header row" has 3+ non-empty cells where 40%+ are strings,
   and the row below contains numeric/date values
2. From each header, expand downward until 2 consecutive empty rows
3. Look 1-3 rows above the header for section titles (often in merged cells)
4. Detect total rows by keyword matching ("Total", "Subtotal", "Grand Total", etc.)

### Known Risks / Gotchas

- **False positives in header detection**: Some sheets have annotation rows that look like
  headers. Mitigation: require numeric data in the row below, and allow users to manually
  specify table ranges via `query_cells`.
- **Large files**: Opening workbooks twice (read_only for analysis, normal for extraction)
  has memory cost. Mitigation: cache analyzers, close workbooks in `cleanup()`.
- **Calculated cells**: Using `data_only=True` requires the file to have been saved with
  calculated values. If not, formulas appear as `None`. Document this limitation.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `openpyxl` | `>=3.1` | Excel structural analysis, cell access, merged cell detection |
| `pandas` | `>=2.0` | DataFrame extraction, `to_markdown()` output |

Both are already project dependencies.

---

## 7. Open Questions

- [ ] Should `load_file()` also register a DataFrame via `add_dataframe()` for simple single-table files, or keep the two paths completely separate? — *Owner: Jesus Lara*: keep two paths separated.
- [ ] Should the ExcelIntelligenceToolkit be auto-registered with agents that have a DatasetManager, or must it be added explicitly? — *Owner: Jesus Lara*: auto-registered as a dependency of DatasetManager.
- [ ] For very large Excel files (100+ MB), should we add a file-size warning/limit? — *Owner: Jesus Lara*: yes, add a warning/limit.

---

## Worktree Strategy

**Isolation**: per-spec (sequential tasks)

All 5 modules build on each other sequentially:
- Module 1 (analyzer engine) is the foundation
- Module 2 (toolkit) wraps Module 1
- Module 3 (DatasetManager integration) uses Modules 1 + 4
- Module 4 (CSV reader) is small and independent but needed by Module 3
- Module 5 (tests) covers all modules

Recommended order: Module 1 → Module 4 → Module 2 → Module 3 → Module 5

No cross-feature dependencies. Can proceed independently of FEAT-067.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-28 | Jesus Lara | Initial draft |
