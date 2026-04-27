# parrot/loaders/excel.py
from typing import List, Optional, Union, Literal, Dict
from pathlib import PurePath
from collections.abc import Callable
import pandas as pd
from navigator.libs.json import JSONContent
from parrot.stores.models import Document
from parrot.loaders.abstract import AbstractLoader

try:
    from parrot.tools.dataset_manager.excel_analyzer import (
        ExcelStructureAnalyzer,
        SheetAnalysis,
        DetectedTable,
    )
    _HAS_ANALYZER = True
except ImportError:
    _HAS_ANALYZER = False


class ExcelLoader(AbstractLoader):
    """Excel loader that converts an Excel workbook (or DataFrame) into Documents.

    Supports two output modes:

    - ``output_mode="sheet"`` (default): one Document per non-empty sheet,
      using ``ExcelStructureAnalyzer`` for structural context (table detection,
      structural summaries, markdown rendering).
    - ``output_mode="row"`` (legacy): one Document per row per sheet — the
      original behaviour preserved for backward compatibility.

    Works for ``.xlsx`` / ``.xlsm`` / ``.xls`` files.  Also accepts a
    ``pandas.DataFrame`` (always falls back to row mode).
    """

    extensions: List[str] = ['.xlsx', '.xlsm', '.xls']

    def __init__(
        self,
        source: Optional[Union[str, PurePath, List[PurePath]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',

        sheets: Optional[Union[str, int, List[Union[str, int]]]] = None,
        header: Union[int, List[int], None] = 0,
        usecols: Optional[Union[str, List[Union[int, str]]]] = None,
        drop_empty_rows: bool = True,
        max_rows: Optional[int] = None,
        date_format: str = "%Y-%m-%d",
        output_format: Literal["markdown", "plain", "json"] = "markdown",
        min_row_length: int = 1,  # skip rows with < N non-empty fields
        title_column: Optional[str] = None,

        output_mode: Literal["sheet", "row"] = "sheet",
        max_rows_per_table: int = 200,

        **kwargs
    ):
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )
        self.doctype = 'excel'
        self._source_type = source_type
        self.sheets = sheets
        self.header = header
        self.usecols = usecols
        self.drop_empty_rows = drop_empty_rows
        self.max_rows = max_rows
        self.date_format = date_format
        self.output_format = output_format
        self.min_row_length = int(min_row_length)
        self.title_column = title_column
        self.output_mode = output_mode
        self.max_rows_per_table = max_rows_per_table

    # ------------------------------------------------------------------
    # Row-mode helpers (unchanged from original)
    # ------------------------------------------------------------------

    def _stringify(self, v):
        if pd.isna(v):
            return ""
        if isinstance(v, (pd.Timestamp, )):
            return v.strftime(self.date_format)
        return str(v)

    def _row_to_text(self, row: Dict[str, object]) -> str:
        """Render a single row dict to text in the chosen output_format."""
        if self.output_format == "json":
            return JSONContent.dumps(row, indent=2)

        items = [(k, self._stringify(v)) for k, v in row.items()]
        if self.output_format == "plain":
            # key: value per line
            return "\n".join(f"{k}: {v}" for k, v in items if v != "")

        # markdown: list of **key**: value
        return "\n".join(f"- **{k}**: {v}" for k, v in items if v != "")

    def _row_nonempty_count(self, row: Dict[str, object]) -> int:
        return sum(1 for v in row.values() if (not pd.isna(v)) and str(v).strip() != "")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def _load(self, source: Union[PurePath, str, pd.DataFrame], **kwargs) -> List[Document]:
        """Load an Excel file (or DataFrame) and return Documents.

        When ``output_mode="sheet"`` and *source* is a file path, uses
        ``ExcelStructureAnalyzer`` for per-sheet document generation.
        Otherwise falls back to the legacy per-row path.
        """
        docs: List[Document] = []

        # Case A: DataFrame input — always use row mode
        if isinstance(source, pd.DataFrame):
            sheet_name = "DataFrame"
            docs.extend(await self._docs_from_dataframe(source, sheet_name, path_hint="dataframe"))
            return docs

        path = PurePath(source) if not isinstance(source, PurePath) else source
        self.logger.info(f"Loading Excel file: {path}")

        # Case B: sheet mode with ExcelStructureAnalyzer
        if self.output_mode == "sheet" and _HAS_ANALYZER:
            try:
                docs = await self._docs_from_sheet_analysis(path)
                return docs
            except Exception as exc:
                self.logger.warning(
                    "Sheet-mode analysis failed for %s: %s — falling back to row mode",
                    path, exc,
                )
                # Fall through to row mode

        # Case C: row mode (legacy) or fallback
        return await self._load_row_mode(path)

    # ------------------------------------------------------------------
    # Sheet mode — per-sheet Documents via ExcelStructureAnalyzer
    # ------------------------------------------------------------------

    async def _docs_from_sheet_analysis(
        self,
        path: PurePath,
    ) -> List[Document]:
        """Produce one Document per non-empty sheet using structural analysis.

        Args:
            path: Path to the Excel workbook.

        Returns:
            List of Documents, one per non-empty sheet.
        """
        analyzer = ExcelStructureAnalyzer(str(path))
        try:
            analysis = analyzer.analyze_workbook()
            docs: List[Document] = []

            for sheet_name, sheet_analysis in analysis.items():
                # Skip empty sheets (no rows at all)
                if sheet_analysis.total_rows == 0:
                    self.logger.info(f"Sheet '{sheet_name}' is empty; skipping.")
                    continue

                # Build table markdown sections
                table_sections: List[str] = []
                table_ids: List[str] = []

                if sheet_analysis.tables:
                    for table in sheet_analysis.tables:
                        df = analyzer.extract_table_as_dataframe(
                            sheet_name, table, include_totals=False,
                        )
                        if len(df) > self.max_rows_per_table:
                            df = df.head(self.max_rows_per_table)
                            truncation_note = (
                                f"\n\n*Table truncated to {self.max_rows_per_table} rows "
                                f"(original: {table.row_count} rows)*"
                            )
                        else:
                            truncation_note = ""

                        title_part = f": {table.title}" if table.title else ""
                        section = f"### {table.table_id}{title_part}\n{df.to_markdown(index=False)}{truncation_note}"
                        table_sections.append(section)
                        table_ids.append(table.table_id)
                else:
                    # No detected tables — render raw cell content as markdown
                    raw_df = pd.read_excel(
                        str(path),
                        sheet_name=sheet_name,
                        header=self.header,
                        dtype=object,
                    )
                    if self.drop_empty_rows:
                        raw_df = raw_df.dropna(how="all")
                    if raw_df.empty:
                        self.logger.info(
                            f"Sheet '{sheet_name}' has no data after cleanup; skipping."
                        )
                        continue
                    raw_df.columns = [str(c) for c in raw_df.columns]
                    table_sections.append(raw_df.to_markdown(index=False))

                # Structural summary from SheetAnalysis
                structural_summary = sheet_analysis.to_summary()

                # Build tables list string for the context header
                if table_ids:
                    tables_header = f"{len(table_ids)} ({', '.join(table_ids)})"
                else:
                    tables_header = "0 (raw cell content)"

                # Context header — semantic position only (filename/type/source
                # already live in `metadata`; do NOT prepend them to page_content)
                context = [
                    f"Sheet: {sheet_name}",
                    f"Tables: {tables_header}",
                ]
                context_header = "\n".join(context) + "\n======"

                # Full content: header + structural summary + table sections
                body_parts = [structural_summary] + table_sections
                full_content = context_header + "\n\n" + "\n\n".join(body_parts)

                # Metadata — non-canonical extras as explicit kwargs.
                meta = self.create_metadata(
                    path=path,
                    doctype="excel",
                    source_type="excel_sheet",
                    sheet=sheet_name,
                    content_type="sheet",
                    table_count=len(sheet_analysis.tables),
                    tables=table_ids,
                    total_rows=sheet_analysis.total_rows,
                    total_cols=sheet_analysis.total_cols,
                    output_format=self.output_format,
                )

                docs.append(self.create_document(full_content, path, meta))

            return docs
        finally:
            analyzer.close()

    # ------------------------------------------------------------------
    # Row mode (legacy) — per-row Documents
    # ------------------------------------------------------------------

    async def _load_row_mode(self, path: PurePath) -> List[Document]:
        """Load an Excel file in legacy row mode (one Document per row).

        Args:
            path: Path to the Excel workbook.

        Returns:
            List of per-row Documents.
        """
        docs: List[Document] = []

        try:
            xls = pd.read_excel(
                str(path),
                sheet_name=self.sheets if self.sheets is not None else None,
                header=self.header,
                usecols=self.usecols,
                dtype=object,
            )
        except Exception as e:
            self.logger.error(f"Failed to read Excel {path}: {e}")
            return docs

        # Normalize to dict[str, DataFrame]
        if isinstance(xls, pd.DataFrame):
            frames = {"Sheet1" if self.sheets is None else str(self.sheets): xls}
        else:
            frames = {str(k): v for k, v in xls.items()}

        for sheet_name, df in frames.items():
            if self.drop_empty_rows:
                df = df.dropna(how="all")

            if self.max_rows is not None:
                df = df.head(self.max_rows)

            if df.empty:
                self.logger.info(f"Sheet '{sheet_name}' is empty; skipping.")
                continue

            df.columns = [str(c) for c in df.columns]
            docs.extend(await self._docs_from_dataframe(df, sheet_name, path_hint=path))

        return docs

    async def _docs_from_dataframe(
        self,
        df: pd.DataFrame,
        sheet_name: str,
        path_hint: Union[str, PurePath]
    ) -> List[Document]:
        """Convert a DataFrame into per-row Documents."""
        docs: List[Document] = []

        # Convert to records for easy iteration
        records = df.to_dict(orient="records")

        for i, row in enumerate(records, start=1):
            if self.min_row_length > 1 and self._row_nonempty_count(row) < self.min_row_length:
                continue

            content_body = self._row_to_text(row)

            # Context header — semantic position only (filename/type/source
            # already live in `metadata`; do NOT prepend them to page_content)
            title_val = None
            if self.title_column and self.title_column in row:
                title_val = self._stringify(row[self.title_column]).strip() or None

            context = [
                f"Sheet: {sheet_name}",
                f"Row: {i}",
            ]
            if title_val:
                context.append(f"Title: {title_val}")

            full_content = "\n".join(context) + "\n======\n\n" + content_body

            # Metadata — non-canonical extras as explicit kwargs.
            meta = self.create_metadata(
                path=path_hint,
                doctype="excel",
                source_type="excel_row",
                sheet=sheet_name,
                row_index=i,
                columns=list(df.columns),
                content_type="row",
                output_format=self.output_format,
            )

            docs.append(
                self.create_document(full_content, path_hint, meta)
            )

        return docs
