# TASK-477: DatasetManager File Loading

**Feature**: datasetmanager-files
**Spec**: `sdd/specs/datasetmanager-files.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-475, TASK-478
**Assigned-to**: unassigned

---

## Context

> This task implements Module 3 from the spec. It integrates the Excel analyzer and CSV
> reader into DatasetManager, adding `load_file()`, `get_file_context()`, and
> `get_file_table()` methods. File entries are stored separately from DataFrame entries
> (per resolved open question: keep two paths separated). The ExcelIntelligenceToolkit
> is auto-registered as a dependency of DatasetManager (per resolved open question).

---

## Scope

- Add `FileEntry` dataclass to DatasetManager module
- Add `_file_entries: Dict[str, FileEntry]` storage to `DatasetManager.__init__()`
- Implement `async def load_file(name, path, metadata, max_rows_per_table, output_format) -> str`:
  - Detect file type by extension
  - For CSV: use csv_reader (TASK-478) to produce markdown
  - For Excel: use `ExcelStructureAnalyzer` to analyze + extract all tables as markdown
  - Store result as `FileEntry` in `_file_entries`
  - Add file-size warning for files > 100MB (per resolved open question)
  - Return structural summary string
- Implement `async def get_file_context(name) -> str` — full markdown for all tables
- Implement `async def get_file_table(name, table_id) -> str` — specific table markdown
- Update `df_guide` generation to include file entries alongside DataFrame entries
- Auto-register `ExcelIntelligenceToolkit` when DatasetManager is initialized
- Do NOT modify existing `add_dataframe_from_file()` — paths stay separate
- Write integration tests

**NOT in scope**: Analyzer implementation (TASK-475), toolkit implementation (TASK-476).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Add FileEntry, _file_entries, load_file(), get_file_context(), get_file_table() |
| `tests/tools/test_datasetmanager_files.py` | CREATE | Integration tests |

---

## Implementation Notes

### FileEntry Dataclass

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
from parrot.tools.dataset_manager.excel_analyzer import SheetAnalysis


@dataclass
class FileEntry:
    """A file loaded into DatasetManager (not a DataFrame)."""
    name: str
    path: Path
    file_type: str  # "csv" | "excel"
    markdown_content: Dict[str, str]  # table_id -> markdown string
    structural_summary: str
    analysis: Optional[Dict[str, SheetAnalysis]] = None  # Excel only
    metadata: Optional[Dict[str, Any]] = None
```

### load_file() Pattern

```python
async def load_file(
    self,
    name: str,
    path: Union[str, Path],
    metadata: Optional[Dict[str, Any]] = None,
    max_rows_per_table: int = 200,
    output_format: str = "markdown",
) -> str:
    """Load a CSV or Excel file for LLM context."""
    path = Path(path)
    file_size = path.stat().st_size
    if file_size > 100 * 1024 * 1024:  # 100MB
        self.logger.warning(
            "File '%s' is %.1f MB — loading may be slow",
            path.name, file_size / (1024 * 1024)
        )

    extension = path.suffix.lower().lstrip(".")

    if extension == "csv":
        from parrot.tools.dataset_manager.csv_reader import csv_to_markdown
        markdown = csv_to_markdown(path, max_rows=max_rows_per_table)
        entry = FileEntry(
            name=name, path=path, file_type="csv",
            markdown_content={"table": markdown},
            structural_summary=f"CSV file: {path.name} — loaded as markdown",
            metadata=metadata,
        )
    elif extension in {"xls", "xlsx", "xlsm", "xlsb"}:
        from parrot.tools.dataset_manager.excel_analyzer import ExcelStructureAnalyzer
        analyzer = ExcelStructureAnalyzer(path)
        analysis = analyzer.analyze_workbook()
        # Extract all tables as markdown
        markdown_content = {}
        for sheet_name, sheet_analysis in analysis.items():
            for table in sheet_analysis.tables:
                df = analyzer.extract_table_as_dataframe(
                    sheet_name, table, include_totals=False
                )
                if len(df) > max_rows_per_table:
                    df = df.head(max_rows_per_table)
                markdown_content[table.table_id] = df.to_markdown(index=False)
        # Build summary
        summary_parts = []
        for sheet_name, sa in analysis.items():
            summary_parts.append(sa.to_summary())
        structural_summary = "\n\n".join(summary_parts)
        entry = FileEntry(
            name=name, path=path, file_type="excel",
            markdown_content=markdown_content,
            structural_summary=structural_summary,
            analysis=analysis,
            metadata=metadata,
        )
        analyzer.close()
    else:
        raise ValueError(f"Unsupported file type: .{extension}")

    self._file_entries[name] = entry
    return entry.structural_summary
```

### Key Constraints

- `load_file()` and `get_file_context()` should be included in the toolkit tools (NOT in `exclude_tools`)
- `get_file_table()` should also be a tool
- Keep DataFrame path (`add_dataframe_from_file`) completely unchanged
- File-size check uses `Path.stat().st_size`, warns but does NOT block
- Auto-register `ExcelIntelligenceToolkit` — import and instantiate in `DatasetManager.__init__()` or `setup()`

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — all modifications here
- `packages/ai-parrot/src/parrot/tools/dataset_manager/excel_analyzer.py` — from TASK-475
- `packages/ai-parrot/src/parrot/tools/dataset_manager/csv_reader.py` — from TASK-478

---

## Acceptance Criteria

- [ ] `FileEntry` dataclass created
- [ ] `DatasetManager._file_entries` dict initialized in `__init__`
- [ ] `load_file()` loads CSV files and returns markdown
- [ ] `load_file()` loads Excel files, runs structural analysis, stores per-table markdown
- [ ] `load_file()` warns for files > 100MB
- [ ] `get_file_context()` returns full markdown for a loaded file
- [ ] `get_file_table()` returns specific table markdown by ID
- [ ] File entries are separate from DataFrame entries (two paths)
- [ ] `add_dataframe_from_file()` unchanged
- [ ] `load_file`, `get_file_context`, `get_file_table` appear as LLM tools
- [ ] All tests pass: `pytest tests/tools/test_datasetmanager_files.py -v`

---

## Test Specification

```python
# tests/tools/test_datasetmanager_files.py
import pytest
import openpyxl
from parrot.tools.dataset_manager.tool import DatasetManager


@pytest.fixture
def complex_excel_path(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Revenue"
    ws["A1"] = "Roadshow Net Revenue"
    ws["A2"], ws["B2"], ws["C2"] = "Client", "Jan 2024", "Feb 2024"
    ws["A3"], ws["B3"], ws["C3"] = "Client A", 10000, 12000
    ws["A4"], ws["B4"], ws["C4"] = "Client B", 8000, 9500
    path = tmp_path / "test.xlsx"
    wb.save(path)
    return path


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "test.csv"
    path.write_text("Name,Age,City\nAlice,30,NYC\nBob,25,LA\n")
    return path


@pytest.fixture
def manager():
    return DatasetManager(generate_guide=False)


class TestLoadFile:
    @pytest.mark.asyncio
    async def test_load_csv(self, manager, csv_path):
        result = await manager.load_file("test_csv", csv_path)
        assert "csv" in result.lower() or "Name" in result
        assert "test_csv" in manager._file_entries

    @pytest.mark.asyncio
    async def test_load_excel(self, manager, complex_excel_path):
        result = await manager.load_file("test_excel", complex_excel_path)
        assert "Revenue" in result
        assert "test_excel" in manager._file_entries
        entry = manager._file_entries["test_excel"]
        assert entry.file_type == "excel"
        assert len(entry.markdown_content) >= 1

    @pytest.mark.asyncio
    async def test_unsupported_file(self, manager, tmp_path):
        path = tmp_path / "test.txt"
        path.write_text("hello")
        with pytest.raises(ValueError, match="Unsupported"):
            await manager.load_file("test", path)


class TestGetFileContext:
    @pytest.mark.asyncio
    async def test_get_context(self, manager, csv_path):
        await manager.load_file("test_csv", csv_path)
        context = await manager.get_file_context("test_csv")
        assert "Name" in context

    @pytest.mark.asyncio
    async def test_not_found(self, manager):
        with pytest.raises((KeyError, ValueError)):
            await manager.get_file_context("nonexistent")


class TestGetFileTable:
    @pytest.mark.asyncio
    async def test_get_table(self, manager, complex_excel_path):
        await manager.load_file("test_excel", complex_excel_path)
        entry = manager._file_entries["test_excel"]
        table_id = list(entry.markdown_content.keys())[0]
        result = await manager.get_file_table("test_excel", table_id)
        assert "Client" in result


class TestSeparation:
    @pytest.mark.asyncio
    async def test_file_and_dataframe_separate(self, manager, csv_path):
        # Load as file
        await manager.load_file("file_csv", csv_path)
        # Load as dataframe
        manager.add_dataframe_from_file("df_csv", csv_path)
        assert "file_csv" in manager._file_entries
        assert "df_csv" in manager._datasets
        assert "file_csv" not in manager._datasets
        assert "df_csv" not in manager._file_entries
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-files.spec.md`
2. **Check dependencies** — verify TASK-475 and TASK-478 are completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` fully
5. **Implement** FileEntry, _file_entries, load_file(), get_file_context(), get_file_table()
6. **Run tests**: `pytest tests/tools/test_datasetmanager_files.py -v`
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
