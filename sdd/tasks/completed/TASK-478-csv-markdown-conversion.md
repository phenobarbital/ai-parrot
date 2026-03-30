# TASK-478: CSV Markdown Conversion

**Feature**: datasetmanager-files
**Spec**: `sdd/specs/datasetmanager-files.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 4 from the spec. A lightweight CSV-to-markdown converter
> that handles edge cases like encoding detection, large files (truncation), and
> multi-header rows. Simpler than the Excel analyzer — no structural analysis needed.

---

## Scope

- Create `csv_to_markdown()` function that:
  - Reads a CSV file using pandas
  - Converts to markdown via `DataFrame.to_markdown(index=False)`
  - Handles encoding detection (try UTF-8, fall back to Latin-1)
  - Truncates at `max_rows` with a note showing total row count
  - Returns clean markdown string with file info header
- Create `csv_to_structural_summary()` function that returns a brief summary:
  - File name, row count, column count, column names
- Write unit tests

**NOT in scope**: Excel handling (TASK-475), toolkit (TASK-476), DatasetManager integration (TASK-477).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/csv_reader.py` | CREATE | CSV-to-markdown converter |
| `tests/tools/test_csv_reader.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
"""CSV-to-markdown converter for DatasetManager file loading."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)


def csv_to_markdown(
    path: Union[str, Path],
    max_rows: int = 200,
    separator: Optional[str] = None,
    **kwargs,
) -> str:
    """Convert a CSV file to a clean markdown table.

    Args:
        path: Path to the CSV file.
        max_rows: Maximum rows to include (truncates with note).
        separator: Column separator. Auto-detected if None.
        **kwargs: Passed to pandas.read_csv().

    Returns:
        Markdown string with table header and data.
    """
    path = Path(path)

    # Try UTF-8 first, fall back to Latin-1
    for encoding in ("utf-8", "latin-1"):
        try:
            df = pd.read_csv(
                path, encoding=encoding, sep=separator, **kwargs
            )
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Cannot decode CSV file: {path.name}")

    total_rows = len(df)
    truncated = False
    if total_rows > max_rows:
        df = df.head(max_rows)
        truncated = True

    header = f"File: {path.name} ({total_rows} rows x {len(df.columns)} cols)\n"
    markdown = df.to_markdown(index=False)

    if truncated:
        markdown += f"\n\n(Showing first {max_rows} of {total_rows} rows)"

    return header + markdown


def csv_to_structural_summary(path: Union[str, Path]) -> str:
    """Return a brief structural summary of a CSV file.

    Args:
        path: Path to the CSV file.

    Returns:
        Summary string with file info.
    """
    path = Path(path)
    for encoding in ("utf-8", "latin-1"):
        try:
            df = pd.read_csv(path, encoding=encoding, nrows=5)
            total_rows = sum(1 for _ in open(path, encoding=encoding)) - 1
            break
        except UnicodeDecodeError:
            continue
    else:
        return f"CSV file: {path.name} (unable to read)"

    cols = ", ".join(df.columns[:10])
    if len(df.columns) > 10:
        cols += f", ... (+{len(df.columns) - 10} more)"

    return (
        f"CSV file: {path.name}\n"
        f"  Rows: ~{total_rows}, Columns: {len(df.columns)}\n"
        f"  Headers: {cols}"
    )
```

### Key Constraints

- Keep it simple — CSV is the easy case compared to Excel
- Auto-detect separator via pandas defaults (sniffing)
- Encoding fallback chain: UTF-8 → Latin-1
- `to_markdown()` requires the `tabulate` package (already a dependency)
- No async needed — this is a pure utility function called by `load_file()`

### References in Codebase

- `packages/ai-parrot-loaders/src/parrot_loaders/csv.py` — Existing CSVLoader (different concern: produces Documents)
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — `add_dataframe_from_file()` as reference

---

## Acceptance Criteria

- [ ] `csv_to_markdown()` reads CSV and returns markdown table string
- [ ] UTF-8 and Latin-1 encoding handled with fallback
- [ ] Truncation at `max_rows` with note showing total count
- [ ] `csv_to_structural_summary()` returns brief file info
- [ ] Custom separator support
- [ ] All tests pass: `pytest tests/tools/test_csv_reader.py -v`

---

## Test Specification

```python
# tests/tools/test_csv_reader.py
import pytest
from parrot.tools.dataset_manager.csv_reader import (
    csv_to_markdown, csv_to_structural_summary
)


@pytest.fixture
def simple_csv(tmp_path):
    path = tmp_path / "simple.csv"
    path.write_text("Name,Age,City\nAlice,30,NYC\nBob,25,LA\n", encoding="utf-8")
    return path


@pytest.fixture
def large_csv(tmp_path):
    path = tmp_path / "large.csv"
    lines = ["Id,Value\n"] + [f"{i},{i*10}\n" for i in range(500)]
    path.write_text("".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def latin1_csv(tmp_path):
    path = tmp_path / "latin1.csv"
    path.write_bytes("Nombre,Ciudad\nJosé,São Paulo\nMaría,Córdoba\n".encode("latin-1"))
    return path


@pytest.fixture
def tsv_file(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("Name\tAge\nAlice\t30\nBob\t25\n", encoding="utf-8")
    return path


class TestCsvToMarkdown:
    def test_simple_csv(self, simple_csv):
        result = csv_to_markdown(simple_csv)
        assert "Name" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_truncation(self, large_csv):
        result = csv_to_markdown(large_csv, max_rows=10)
        assert "Showing first 10 of 500" in result

    def test_no_truncation_when_small(self, simple_csv):
        result = csv_to_markdown(simple_csv, max_rows=200)
        assert "Showing first" not in result

    def test_latin1_encoding(self, latin1_csv):
        result = csv_to_markdown(latin1_csv)
        assert "José" in result or "Nombre" in result

    def test_custom_separator(self, tsv_file):
        result = csv_to_markdown(tsv_file, separator="\t")
        assert "Name" in result
        assert "Alice" in result

    def test_file_header(self, simple_csv):
        result = csv_to_markdown(simple_csv)
        assert "simple.csv" in result
        assert "2 rows" in result


class TestCsvStructuralSummary:
    def test_summary(self, simple_csv):
        result = csv_to_structural_summary(simple_csv)
        assert "simple.csv" in result
        assert "Name" in result
        assert "Columns: 3" in result
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-files.spec.md`
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** `csv_to_markdown()` and `csv_to_structural_summary()`
5. **Run tests**: `pytest tests/tools/test_csv_reader.py -v`
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
