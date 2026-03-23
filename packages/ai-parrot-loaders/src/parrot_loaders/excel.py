# parrot/loaders/excel.py
from typing import List, Optional, Union, Literal, Dict
from pathlib import PurePath
from collections.abc import Callable
import pandas as pd
from navigator.libs.json import JSONContent
from ..stores.models import Document
from .abstract import AbstractLoader


class ExcelLoader(AbstractLoader):
    """
    Excel loader that converts an Excel workbook (or DataFrame) into per-row Documents.

    - One Document per row per sheet (rows with all-empty values are skipped).
    - Works for .xlsx / .xlsm / .xls files (pandas engine auto-detects).
    - Also accepts a pandas.DataFrame (sheet='DataFrame').
    - Output formats: markdown (default), plain, or json.
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

    async def _load(self, source: Union[PurePath, str, pd.DataFrame], **kwargs) -> List[Document]:
        """
        Load an Excel file (or DataFrame) and return per-row Documents.
        """
        docs: List[Document] = []

        # Case A: already a DataFrame (from AbstractLoader.from_dataframe)
        # (sheet name is synthetic: "DataFrame")
        if isinstance(source, pd.DataFrame):
            sheet_name = "DataFrame"
            docs.extend(await self._docs_from_dataframe(source, sheet_name, path_hint="dataframe"))
            return docs

        # Case B: excel path
        path = PurePath(source) if not isinstance(source, PurePath) else source
        self.logger.info(f"Loading Excel file: {path}")

        # Read one or multiple sheets
        try:
            # If sheets=None -> pd returns dict of DataFrames (all sheets)
            # If sheets is a single name/index -> returns a DataFrame
            xls = pd.read_excel(
                str(path),
                sheet_name=self.sheets if self.sheets is not None else None,
                header=self.header,
                usecols=self.usecols,
                dtype=object  # keep as objects → stringify ourselves
            )
        except Exception as e:
            self.logger.error(f"Failed to read Excel {path}: {e}")
            return docs

        # Normalize to dict[str, DataFrame]
        if isinstance(xls, pd.DataFrame):
            frames = {"Sheet1" if self.sheets is None else str(self.sheets): xls}
        else:
            # dict of {sheet_name: df}
            frames = {str(k): v for k, v in xls.items()}

        for sheet_name, df in frames.items():
            # Drop fully empty rows
            if self.drop_empty_rows:
                df = df.dropna(how="all")

            if self.max_rows is not None:
                df = df.head(self.max_rows)

            if df.empty:
                self.logger.info(f"Sheet '{sheet_name}' is empty; skipping.")
                continue

            # Ensure columns are strings
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

            # Context header (aligns with PDF/PPT style: header + "======")
            title_val = None
            if self.title_column and self.title_column in row:
                title_val = self._stringify(row[self.title_column]).strip() or None

            context = [
                f"File Name: {path_hint.name if hasattr(path_hint, 'name') else str(path_hint)}",
                f"Sheet: {sheet_name}",
                f"Row: {i}",
                f"Document Type: excel",
                f"Source Type: {self._source_type}",
            ]
            if title_val:
                context.append(f"Title: {title_val}")

            full_content = "\n".join(context) + "\n======\n\n" + content_body

            # Metadata
            doc_meta = {
                "filename": path_hint.name if hasattr(path_hint, 'name') else str(path_hint),
                "file_path": str(path_hint),
                "sheet": sheet_name,
                "row_index": i,
                "columns": list(df.columns),
                "content_type": "row",
                "output_format": self.output_format,
            }

            meta = self.create_metadata(
                path=path_hint,
                doctype="excel",
                source_type="excel_row",
                doc_metadata=doc_meta,
            )

            docs.append(
                self.create_document(full_content, path_hint, meta)
            )

        return docs
