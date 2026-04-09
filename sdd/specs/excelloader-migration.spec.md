# Feature Specification: ExcelLoader Migration to Per-Sheet Documents

**Feature ID**: FEAT-093
**Date**: 2026-04-09
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The current `ExcelLoader` (in `parrot_loaders`) creates **one Document per row per sheet**.
For a workbook with 500 rows across 3 sheets, that produces 500+ Documents — each containing
a single row's key-value pairs with no surrounding context. This approach has several problems
for RAG-based agents:

1. **Lost structural context** — each row-document is isolated; the agent cannot see column
   relationships, table boundaries, or the overall sheet layout.
2. **Token waste** — the context header (file name, sheet, row number, doc type) is repeated
   in every row-document, consuming embedding dimensions on boilerplate.
3. **Poor retrieval quality** — semantic search on row-level snippets rarely surfaces the
   right document because individual rows lack enough semantic signal.
4. **Inconsistency with DatasetManager** — `DatasetManager.load_file()` already implements
   a superior approach using `ExcelStructureAnalyzer`: it detects table structures, extracts
   per-table markdown with structural summaries (sheet dimensions, merged cells, detected
   tables with ranges), and stores them as `FileEntry` objects with composite keys
   (`sheet::table_id`). The ExcelLoader should adopt the same structural analysis approach
   to produce **one Document per sheet** with full structural context.

### Goals

- Migrate `ExcelLoader._load()` to produce **one Document per sheet** instead of one per row
- Reuse `ExcelStructureAnalyzer` from `DatasetManager` to detect table structures within sheets
- Each sheet-document includes: structural summary header + all tables rendered as markdown
- Preserve backward compatibility via an `output_mode` parameter (`"sheet"` default, `"row"` legacy)
- Metadata reflects the new granularity (`content_type: "sheet"`, table count, structural info)

### Non-Goals (explicitly out of scope)

- Changing `DatasetManager.load_file()` — it already works correctly
- Supporting non-Excel formats (CSV, PDF, etc.) — those have their own loaders
- Chart/image extraction from Excel — only cell data
- Replacing the `ExcelStructureAnalyzer` — reuse it as-is
- Modifying the `AbstractLoader` base class

---

## 2. Architectural Design

### Overview

The migration rewrites `ExcelLoader._load()` and `ExcelLoader._docs_from_dataframe()` to use
`ExcelStructureAnalyzer` for structural analysis, then renders each sheet as a single Document
containing a structural header followed by all detected tables as markdown.

```
ExcelLoader._load(path)
    │
    ├── ExcelStructureAnalyzer(path)
    │       ├── analyze_workbook() → Dict[str, SheetAnalysis]
    │       └── extract_table_as_dataframe(sheet, table) → pd.DataFrame
    │
    └── For each sheet:
            ├── SheetAnalysis.to_summary() → structural header
            ├── df.to_markdown() for each DetectedTable → table content
            └── Combine into single Document(page_content, metadata)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractLoader` | inherits | No changes to base class |
| `ExcelStructureAnalyzer` | uses | Import from `parrot.tools.dataset_manager.excel_analyzer` |
| `SheetAnalysis` / `DetectedTable` | uses | Dataclasses for structural metadata |
| `Document` | produces | From `parrot.stores.models` |

### Data Models

No new data models required. The existing `SheetAnalysis`, `DetectedTable`, and `Document`
models are sufficient.

### New Public Interfaces

```python
class ExcelLoader(AbstractLoader):
    def __init__(
        self,
        source=None,
        *,
        # ... existing params ...
        output_mode: Literal["sheet", "row"] = "sheet",  # NEW
        max_rows_per_table: int = 200,                    # NEW
        **kwargs
    ):
        ...
```

- `output_mode="sheet"` (default): one Document per sheet with structural context
- `output_mode="row"` (legacy): current per-row behavior, preserved for backward compatibility
- `max_rows_per_table`: truncate tables longer than this (token budget control)

---

## 3. Module Breakdown

### Module 1: ExcelLoader Migration
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/excel.py`
- **Responsibility**: Rewrite `_load()` to produce per-sheet Documents using
  `ExcelStructureAnalyzer`. Add `output_mode` parameter for backward compatibility.
  Add `_docs_from_sheet_analysis()` method for the new per-sheet path.
  Keep `_docs_from_dataframe()` for the legacy `output_mode="row"` path.
- **Depends on**: ExcelStructureAnalyzer (already exists)

### Module 2: Unit Tests
- **Path**: `packages/ai-parrot-loaders/tests/test_excel_loader.py`
- **Responsibility**: Test both `output_mode="sheet"` and `output_mode="row"`.
  Verify structural context in sheet-mode documents.
  Verify backward compatibility in row-mode.
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_sheet_mode_one_doc_per_sheet` | Module 1 | Single-sheet workbook → exactly 1 Document |
| `test_sheet_mode_multi_sheet` | Module 1 | 3-sheet workbook → exactly 3 Documents |
| `test_sheet_mode_structural_header` | Module 1 | Document contains sheet name, dimensions, table summary |
| `test_sheet_mode_tables_as_markdown` | Module 1 | Each detected table rendered as markdown in content |
| `test_sheet_mode_metadata` | Module 1 | Metadata has `content_type: "sheet"`, `table_count`, `sheet` |
| `test_sheet_mode_max_rows_truncation` | Module 1 | Tables exceeding `max_rows_per_table` are truncated |
| `test_sheet_mode_empty_sheet_skipped` | Module 1 | Empty sheets produce no Documents |
| `test_row_mode_backward_compat` | Module 1 | `output_mode="row"` produces per-row Documents (legacy) |
| `test_default_mode_is_sheet` | Module 1 | Default `output_mode` is `"sheet"` |
| `test_dataframe_input` | Module 1 | DataFrame input still works (falls back to row-mode) |

### Test Data / Fixtures

```python
@pytest.fixture
def simple_excel(tmp_path):
    """Single-sheet workbook with 5 rows."""
    import openpyxl
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
    """3-sheet workbook with different table structures."""
    import openpyxl
    wb = openpyxl.Workbook()
    # Sheet 1: Sales
    ws1 = wb.active
    ws1.title = "Sales"
    ws1.append(["Product", "Q1", "Q2"])
    for i in range(3):
        ws1.append([f"Item {i}", i * 10, i * 20])
    # Sheet 2: Expenses
    ws2 = wb.create_sheet("Expenses")
    ws2.append(["Category", "Amount"])
    ws2.append(["Rent", 5000])
    ws2.append(["Utilities", 800])
    # Sheet 3: Empty
    wb.create_sheet("Empty")
    path = tmp_path / "multi.xlsx"
    wb.save(path)
    return path
```

---

## 5. Acceptance Criteria

- [ ] `ExcelLoader(output_mode="sheet")` produces one Document per non-empty sheet
- [ ] Each sheet-Document contains a structural header (sheet name, dimensions, table info)
- [ ] Each sheet-Document contains all detected tables rendered as markdown
- [ ] `ExcelLoader(output_mode="row")` preserves the current per-row behavior exactly
- [ ] Default `output_mode` is `"sheet"`
- [ ] `max_rows_per_table` truncates large tables in sheet mode
- [ ] DataFrame input (via `from_dataframe`) continues to work
- [ ] All unit tests pass: `pytest packages/ai-parrot-loaders/tests/test_excel_loader.py -v`
- [ ] No breaking changes to existing public API (row mode still available)
- [ ] `ExcelStructureAnalyzer` import works from `parrot_loaders` context

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# ExcelLoader lives in the loaders package
from parrot_loaders.excel import ExcelLoader  # verified: packages/ai-parrot-loaders/src/parrot_loaders/excel.py:11

# AbstractLoader base class
from parrot.loaders.abstract import AbstractLoader  # verified: packages/ai-parrot/src/parrot/loaders/abstract.py:35

# Document model
from parrot.stores.models import Document  # verified: packages/ai-parrot/src/parrot/stores/models.py:21

# ExcelStructureAnalyzer and data models
from parrot.tools.dataset_manager.excel_analyzer import ExcelStructureAnalyzer  # verified: packages/ai-parrot/src/parrot/tools/dataset_manager/excel_analyzer.py:133
from parrot.tools.dataset_manager.excel_analyzer import SheetAnalysis  # verified: line 99
from parrot.tools.dataset_manager.excel_analyzer import DetectedTable  # verified: line 60

# IMPORTANT: ExcelLoader imports AbstractLoader from parrot.loaders.abstract (line 8 of excel.py)
# but references Document from parrot.stores.models (line 7 of excel.py)
```

### Existing Class Signatures

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
    name: str
    total_rows: int
    total_cols: int
    tables: List[DetectedTable]
    merged_cells: List[str]
    standalone_labels: List[Tuple[str, str]]
    def to_summary(self) -> str  # line 109

@dataclass
class DetectedTable:  # line 60
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
    def excel_range(self) -> str  # property, line 75
    def to_summary(self) -> str  # line 82

# packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):  # line 21
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ExcelLoader._load()` (new sheet path) | `ExcelStructureAnalyzer` | constructor + `analyze_workbook()` | `excel_analyzer.py:133, 163` |
| `ExcelLoader._load()` (new sheet path) | `ExcelStructureAnalyzer.extract_table_as_dataframe()` | method call | `excel_analyzer.py:170` |
| `ExcelLoader._load()` (new sheet path) | `SheetAnalysis.to_summary()` | method call | `excel_analyzer.py:109` |
| `ExcelLoader._load()` (new sheet path) | `AbstractLoader.create_metadata()` | inherited method | `abstract.py:677` |
| `ExcelLoader._load()` (new sheet path) | `AbstractLoader.create_document()` | inherited method | `abstract.py:710` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_loaders.excel_analyzer`~~ — `ExcelStructureAnalyzer` is in `parrot.tools.dataset_manager.excel_analyzer`, NOT in `parrot_loaders`
- ~~`ExcelLoader.output_mode`~~ — does not exist yet; must be added by this feature
- ~~`ExcelLoader.max_rows_per_table`~~ — does not exist yet; must be added
- ~~`ExcelLoader._docs_from_sheet_analysis()`~~ — does not exist yet; must be created
- ~~`AbstractLoader.load_file()`~~ — this is a `DatasetManager` method, not on `AbstractLoader`
- ~~`parrot.loaders.excel_analyzer`~~ — no such module in the loaders package

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **DatasetManager.load_file() as reference** — the per-sheet approach at
  `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:1098-1131` is the model
  implementation. The ExcelLoader migration should follow the same pattern:
  1. Create `ExcelStructureAnalyzer(path)`
  2. Call `analyze_workbook()` → `Dict[str, SheetAnalysis]`
  3. For each sheet, extract tables via `extract_table_as_dataframe()`
  4. Render tables as markdown via `df.to_markdown(index=False)`
  5. Build structural header from `SheetAnalysis.to_summary()`
  6. Combine header + tables into a single Document per sheet

- **Document content format** — follow the existing ExcelLoader context header pattern
  (file name, sheet, doc type, source type + `======` separator) but replace per-row
  content with the structural summary + tables:
  ```
  File Name: report.xlsx
  Sheet: Sales
  Document Type: excel
  Source Type: file
  Tables: 2 (T1: Revenue, T2: Expenses)
  ======

  ## Sheet: Sales
    Dimensions: 50 rows x 8 cols
    Detected tables: 2
    - T1: Revenue (range A1:D25, 24 data rows)
    - T2: Expenses (range A28:C45, 17 data rows)

  ### T1: Revenue
  | Product | Q1 | Q2 | Q3 |
  |---|---|---|---|
  | Widget A | 1000 | 1200 | 1100 |
  ...

  ### T2: Expenses
  | Category | Amount | Notes |
  |---|---|---|
  | Rent | 5000 | Monthly |
  ...
  ```

- **Cross-package import** — `ExcelStructureAnalyzer` lives in `parrot.tools.dataset_manager`
  (the `ai-parrot` package), while `ExcelLoader` lives in `parrot_loaders` (the
  `ai-parrot-loaders` package). Verify at implementation time that `ai-parrot` is a
  dependency of `ai-parrot-loaders`, or if not, handle the import gracefully with a
  try/except and fallback to the simpler pandas-based approach.

- **DataFrame input path** — when `source` is a `pd.DataFrame` (not a file path),
  `ExcelStructureAnalyzer` cannot be used (it requires a file path). In this case,
  fall back to the legacy row-mode behavior regardless of `output_mode`.

### Known Risks / Gotchas

- **Cross-package dependency**: `parrot_loaders` importing from `parrot.tools.dataset_manager`
  may create a circular or missing dependency. Check `pyproject.toml` for both packages.
  If `ai-parrot` is not a dependency of `ai-parrot-loaders`, the import must be optional
  with a graceful fallback.
- **openpyxl dependency**: `ExcelStructureAnalyzer` requires `openpyxl`. The ExcelLoader
  currently uses `pandas.read_excel()` which can use either `openpyxl` or `xlrd`. Ensure
  `openpyxl` is in `ai-parrot-loaders` dependencies.
- **Large workbooks**: `ExcelStructureAnalyzer` opens the workbook twice (read-only + normal
  mode). For very large files this doubles memory usage. The `max_rows_per_table` parameter
  mitigates token-budget issues but not memory.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `openpyxl` | `>=3.1` | Required by `ExcelStructureAnalyzer` |
| `pandas` | `>=2.0` | Already used; needed for `to_markdown()` |
| `tabulate` | `>=0.9` | Required by `pandas.to_markdown()` |

---

## 8. Open Questions

- [ ] Is `ai-parrot` a declared dependency of `ai-parrot-loaders`? If not, should we move
  `ExcelStructureAnalyzer` into `parrot_loaders` or add the dependency? — *Owner: Jesus*
- [ ] Should sheet-mode be the default for new installations, or should we keep row-mode
  as default for a deprecation period? — *Owner: Jesus*
- [ ] Should sheets with no detected tables (e.g., freeform text) produce a Document with
  just the raw cell content, or be skipped? — *Owner: Jesus*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All tasks modify the same file (`excel.py`) plus tests — no parallelism benefit.
- **Cross-feature dependencies**: None. This spec is self-contained.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-09 | Jesus Lara | Initial draft |
