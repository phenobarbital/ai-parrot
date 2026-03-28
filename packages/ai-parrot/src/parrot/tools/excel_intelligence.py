"""ExcelIntelligenceToolkit — LLM-callable tools for Excel file analysis.

Wraps :class:`ExcelStructureAnalyzer` and exposes three async tools:

* ``inspect_workbook`` — structural map of sheets and tables
* ``extract_table`` — clean tabular data for a specific table
* ``query_cells`` — raw cell values for arbitrary ranges
"""
from __future__ import annotations

from typing import Dict, Optional

from .toolkit import AbstractToolkit
from .dataset_manager.excel_analyzer import (
    ExcelStructureAnalyzer,
    SheetAnalysis,
)


class ExcelIntelligenceToolkit(AbstractToolkit):
    """Toolkit for intelligent Excel file analysis.

    Provides LLM agents with tools to analyze complex Excel workbooks:

    1. ``inspect_workbook`` — structural map of sheets and tables
    2. ``extract_table`` — clean tabular data for a specific table
    3. ``query_cells`` — raw cell values for arbitrary ranges

    Analyzers are cached by file path so repeated calls against the same
    workbook do not re-parse the file.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._analyzer_cache: dict[str, ExcelStructureAnalyzer] = {}
        self._analysis_cache: dict[str, dict[str, SheetAnalysis]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_analyzer(self, file_path: str) -> ExcelStructureAnalyzer:
        """Return (and cache) an analyzer for *file_path*."""
        if file_path not in self._analyzer_cache:
            self._analyzer_cache[file_path] = ExcelStructureAnalyzer(file_path)
        return self._analyzer_cache[file_path]

    def _get_analysis(self, file_path: str) -> dict[str, SheetAnalysis]:
        """Return (and cache) the full workbook analysis for *file_path*."""
        if file_path not in self._analysis_cache:
            analyzer = self._get_analyzer(file_path)
            self._analysis_cache[file_path] = analyzer.analyze_workbook()
        return self._analysis_cache[file_path]

    # ------------------------------------------------------------------
    # LLM Tools
    # ------------------------------------------------------------------

    async def inspect_workbook(
        self, file_path: str, sheet_name: Optional[str] = None,
    ) -> str:
        """Analyze the structure of an Excel workbook.

        Returns a map showing all sheets, detected tables with IDs,
        column names, and ranges. Use table IDs with extract_table.

        Args:
            file_path: Path to the Excel file (.xlsx, .xls).
            sheet_name: Specific sheet to analyze. If None, analyzes all.

        Returns:
            Human-readable structural map of the workbook.
        """
        try:
            analysis = self._get_analysis(file_path)
        except FileNotFoundError:
            return f"Error: file not found — {file_path}"
        except Exception as exc:
            self.logger.error("Failed to analyze workbook: %s", exc)
            return f"Error: could not open workbook — {exc}"

        if sheet_name is not None:
            if sheet_name not in analysis:
                available = ", ".join(analysis.keys())
                return (
                    f"Sheet '{sheet_name}' not found. "
                    f"Available sheets: {available}"
                )
            return analysis[sheet_name].to_summary()

        parts: list[str] = []
        for sa in analysis.values():
            parts.append(sa.to_summary())
        return "\n\n".join(parts)

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
            file_path: Path to the Excel file.
            sheet_name: Name of the sheet containing the table.
            table_id: Table ID (e.g. 'T1', 'T2') from inspect_workbook.
            include_totals: Include total/summary rows.
            max_rows: Maximum rows to return.
            output_format: 'markdown', 'csv', or 'json'.

        Returns:
            Table data in the requested format.
        """
        try:
            analysis = self._get_analysis(file_path)
        except Exception as exc:
            return f"Error: could not open workbook — {exc}"

        if sheet_name not in analysis:
            available = ", ".join(analysis.keys())
            return (
                f"Sheet '{sheet_name}' not found. "
                f"Available sheets: {available}"
            )

        sheet = analysis[sheet_name]
        table = None
        for t in sheet.tables:
            if t.table_id == table_id:
                table = t
                break

        if table is None:
            available_ids = ", ".join(t.table_id for t in sheet.tables)
            return (
                f"Table '{table_id}' not found in sheet '{sheet_name}'. "
                f"Available tables: {available_ids or 'none'}"
            )

        analyzer = self._get_analyzer(file_path)
        df = analyzer.extract_table_as_dataframe(
            sheet_name, table, include_totals=include_totals,
        )

        truncated = False
        if len(df) > max_rows:
            total = len(df)
            df = df.head(max_rows)
            truncated = True

        fmt = output_format.lower()
        if fmt == "csv":
            result = df.to_csv(index=False)
        elif fmt == "json":
            result = df.to_json(orient="records", indent=2)
        else:
            result = df.to_markdown(index=False)

        if truncated:
            result += f"\n\n(Showing first {max_rows} of {total} rows)"

        return result

    async def query_cells(
        self, file_path: str, sheet_name: str, cell_range: str,
    ) -> str:
        """Read raw cell values from a specific range.

        Args:
            file_path: Path to the Excel file.
            sheet_name: Sheet name.
            cell_range: Excel-style range (e.g. 'B10:I16').

        Returns:
            Tab-separated cell values, one row per line.
        """
        try:
            analyzer = self._get_analyzer(file_path)
        except Exception as exc:
            return f"Error: could not open workbook — {exc}"

        try:
            rows = analyzer.extract_cell_range(sheet_name, cell_range)
        except KeyError:
            available = ", ".join(analyzer._wb_ro.sheetnames)
            return (
                f"Sheet '{sheet_name}' not found. "
                f"Available sheets: {available}"
            )
        except Exception as exc:
            return f"Error reading range {cell_range}: {exc}"

        lines: list[str] = []
        for row in rows:
            lines.append("\t".join(str(v) if v is not None else "" for v in row))
        return "\n".join(lines)

    async def cleanup(self) -> None:
        """Close all cached workbooks and clear caches."""
        for analyzer in self._analyzer_cache.values():
            analyzer.close()
        self._analyzer_cache.clear()
        self._analysis_cache.clear()
