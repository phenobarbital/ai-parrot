# TASK-641: Add per-sheet document generation to ExcelLoader

**Feature**: excelloader-migration
**Spec**: `sdd/specs/excelloader-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The ExcelLoader currently produces one Document per row per sheet. This task adds the
new per-sheet document generation capability using `ExcelStructureAnalyzer` from
DatasetManager. It introduces two new constructor parameters (`output_mode`,
`max_rows_per_table`) and a new private method `_docs_from_sheet_analysis()`.

Implements spec Section 2 (Architectural Design) and Section 3 (Module 1).

---

## Scope

- Add `output_mode: Literal["sheet", "row"] = "sheet"` parameter to `ExcelLoader.__init__()`
- Add `max_rows_per_table: int = 200` parameter to `ExcelLoader.__init__()`
- Implement `_docs_from_sheet_analysis()` method that:
  1. Takes a `Dict[str, SheetAnalysis]`, the `ExcelStructureAnalyzer` instance, and path hint
  2. For each non-empty sheet, builds a single Document containing:
     - Context header (file name, sheet, doc type, source type, table count)
     - Structural summary from `SheetAnalysis.to_summary()`
     - All detected tables rendered as markdown via `df.to_markdown(index=False)`
     - For sheets with NO detected tables: render raw cell content as markdown
  3. Tables exceeding `max_rows_per_table` are truncated with `df.head()`
  4. Uses `self.create_metadata()` and `self.create_document()` from `AbstractLoader`
  5. Metadata includes: `content_type: "sheet"`, `table_count`, `sheet`, `tables` (list of table IDs)
- Rewire `_load()` to:
  - When `output_mode == "sheet"` and source is a file path: use `ExcelStructureAnalyzer` + `_docs_from_sheet_analysis()`
  - When `output_mode == "row"` or source is a `pd.DataFrame`: use the existing `_docs_from_dataframe()` (legacy path)
- Keep all existing methods (`_stringify`, `_row_to_text`, `_row_nonempty_count`, `_docs_from_dataframe`) unchanged for backward compatibility

**NOT in scope**: Writing tests (TASK-640), modifying AbstractLoader, modifying ExcelStructureAnalyzer

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/excel.py` | MODIFY | Add params, new method, rewire `_load()` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.

### Verified Imports

```python
# Already in excel.py (line 2-8):
from typing import List, Optional, Union, Literal, Dict
from pathlib import PurePath
from collections.abc import Callable
import pandas as pd
from navigator.libs.json import JSONContent
from parrot.stores.models import Document  # verified: packages/ai-parrot/src/parrot/stores/models.py:21
from parrot.loaders.abstract import AbstractLoader  # verified: packages/ai-parrot/src/parrot/loaders/abstract.py:35

# NEW imports to add:
from parrot.tools.dataset_manager.excel_analyzer import ExcelStructureAnalyzer  # verified: packages/ai-parrot/src/parrot/tools/dataset_manager/excel_analyzer.py:133
from parrot.tools.dataset_manager.excel_analyzer import SheetAnalysis  # verified: line 99
from parrot.tools.dataset_manager.excel_analyzer import DetectedTable  # verified: line 60
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/src/parrot_loaders/excel.py
class ExcelLoader(AbstractLoader):  # line 11
    extensions: List[str] = ['.xlsx', '.xlsm', '.xls']  # line 21
    def __init__(self, source=None, *, tokenizer=None, text_splitter=None,
                 source_type='file', sheets=None, header=0, usecols=None,
                 drop_empty_rows=True, max_rows=None, date_format="%Y-%m-%d",
                 output_format="markdown", min_row_length=1, title_column=None,
                 **kwargs)  # lines 23-49
    async def _load(self, source: Union[PurePath, str, pd.DataFrame], **kwargs) -> List[Document]  # line 85
    async def _docs_from_dataframe(self, df: pd.DataFrame, sheet_name: str,
                                    path_hint: Union[str, PurePath]) -> List[Document]  # line 142

# packages/ai-parrot/src/parrot/loaders/abstract.py
class AbstractLoader(ABC):  # line 35
    def create_metadata(self, path, doctype='document', source_type='source',
                        doc_metadata=None, **kwargs) -> Dict[str, Any]  # line 677
    def create_document(self, content, path, metadata=None, **kwargs) -> Document  # line 710

# packages/ai-parrot/src/parrot/tools/dataset_manager/excel_analyzer.py
class ExcelStructureAnalyzer:  # line 133
    def __init__(self, path: Union[str, Path]) -> None  # line 144
    def analyze_workbook(self) -> Dict[str, SheetAnalysis]  # line 163
    def extract_table_as_dataframe(self, sheet_name: str, table: DetectedTable,
                                    include_totals: bool = True) -> pd.DataFrame  # line 170
    def close(self) -> None  # line 226

@dataclass
class SheetAnalysis:  # line 99
    name: str; total_rows: int; total_cols: int
    tables: List[DetectedTable]; merged_cells: List[str]
    standalone_labels: List[Tuple[str, str]]
    def to_summary(self) -> str  # line 109

@dataclass
class DetectedTable:  # line 60
    table_id: str; title: Optional[str]; header_row: int
    data_start_row: int; data_end_row: int; start_col: int; end_col: int
    columns: List[str]; row_count: int
    has_total_row: bool = False; section_label: Optional[str] = None
    @property excel_range -> str  # line 75
    def to_summary(self) -> str  # line 82

# packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):  # line 21
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### Does NOT Exist

- ~~`parrot_loaders.excel_analyzer`~~ — ExcelStructureAnalyzer is in `parrot.tools.dataset_manager.excel_analyzer`, NOT in `parrot_loaders`
- ~~`ExcelLoader.output_mode`~~ — does not exist yet; this task creates it
- ~~`ExcelLoader.max_rows_per_table`~~ — does not exist yet; this task creates it
- ~~`ExcelLoader._docs_from_sheet_analysis()`~~ — does not exist yet; this task creates it
- ~~`AbstractLoader.load_file()`~~ — this is a DatasetManager method, not on AbstractLoader
- ~~`SheetAnalysis.to_markdown()`~~ — no such method; use `to_summary()` for text, `extract_table_as_dataframe()` + `df.to_markdown()` for tables

---

## Implementation Notes

### Pattern to Follow

Follow `DatasetManager.load_file()` at `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:1098-1131`:

```python
# Reference: how DatasetManager does it (tool.py:1098-1131)
analyzer = ExcelStructureAnalyzer(path)
analysis = analyzer.analyze_workbook()

markdown_content: Dict[str, str] = {}
for sheet_name, sheet_analysis in analysis.items():
    for table in sheet_analysis.tables:
        df = analyzer.extract_table_as_dataframe(
            sheet_name, table, include_totals=False,
        )
        if len(df) > max_rows_per_table:
            df = df.head(max_rows_per_table)
        key = f"{sheet_name}::{table.table_id}"
        markdown_content[key] = df.to_markdown(index=False)

summary_parts = [sa.to_summary() for sa in analysis.values()]
analyzer.close()
```

### Document content format for sheet mode

```
File Name: report.xlsx
Sheet: Sales
Document Type: excel
Source Type: file
Tables: 2 (T1, T2)
======

## Sheet: Sales
  Dimensions: 50 rows x 8 cols
  Detected tables: 2
  - T1: Revenue (range A1:D25, 24 data rows)

### T1: Revenue
| Product | Q1 | Q2 |
|---|---|---|
| Widget A | 1000 | 1200 |
...
```

### Sheets with no detected tables

Per spec resolution: produce a Document with raw cell content. Read all cells via
`pd.read_excel()` for that sheet and render as markdown table using `df.to_markdown(index=False)`.

### Key Constraints

- Must close the `ExcelStructureAnalyzer` after use (call `analyzer.close()`)
- DataFrame inputs cannot use `ExcelStructureAnalyzer` (requires file path) — fall back to row mode
- Use `self.logger` for info/warning messages
- Keep all existing private methods intact for backward compat

---

## Acceptance Criteria

- [ ] `ExcelLoader(output_mode="sheet")` produces one Document per non-empty sheet
- [ ] Each sheet-Document contains structural header + tables as markdown
- [ ] Sheets with no detected tables produce Document with raw cell content
- [ ] `ExcelLoader(output_mode="row")` preserves the exact current per-row behavior
- [ ] Default `output_mode` is `"sheet"`
- [ ] `max_rows_per_table` truncates large tables
- [ ] DataFrame input falls back to row mode regardless of `output_mode`
- [ ] `ExcelStructureAnalyzer` is properly closed after use
- [ ] No modifications to `AbstractLoader` or `ExcelStructureAnalyzer`

---

## Test Specification

Tests are in TASK-640. This task focuses on implementation only.
Verify manually that the module imports correctly:

```python
from parrot_loaders.excel import ExcelLoader
loader = ExcelLoader(output_mode="sheet")
assert loader.output_mode == "sheet"
assert loader.max_rows_per_table == 200
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/excelloader-migration.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` -> `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-641-excelloader-sheet-mode-core.md`
8. **Update index** -> `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
