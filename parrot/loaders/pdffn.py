from collections.abc import Callable
from typing import Any, Optional, List, Union
from pathlib import PurePath, Path
from io import StringIO
import fitz  # PyMuPDF
from langchain.docstore.document import Document
from langchain.text_splitter import (
    RecursiveCharacterTextSplitter
)
from .basepdf import BasePDF


class PDFFnLoader(BasePDF):
    """
    Loading a PDF with including function processing.
    """
    def __init__(
        self,
        path: PurePath,
        tokenizer: Callable[..., Any] = None,
        text_splitter: Union[None, Callable[..., Any]] = None,
        source_type: str = 'pdf',
        language: str = "eng",
        **kwargs
    ):
        table_settings = kwargs.pop('table_settings', {})
        super().__init__(
            path=path,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            language=language,
            **kwargs
        )
        if not text_splitter:
            self.text_splitter = RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
                self.tokenizer,
                chunk_size=2000,
                chunk_overlap=100,
                add_start_index=True,  # If `True`, includes chunk's start index in metadata
                strip_whitespace=True,  # strips whitespace from the start and end
                separators=["\n\n", "\n", "\r\n", "\r", "\f", "\v", "\x0b", "\x0c"],
            )
        self.table_settings = {
            "vertical_strategy": "lines",
            "horizontal_strategy": "text",
            "intersection_x_tolerance": 5,
            "intersection_y_tolerance": 5,
            "edge_min_length": 10,
        }
        # Define settings for Fitz Table Processing
        self.table_settings = {**self.table_settings, **table_settings}

    def set_metadata(self, path, page, page_number, **kwargs) -> dict:
        n = page_number + 1
        return {
            "url": '',
            "index": f"{path.name} #{page_number}",
            "source": f"{path.name} #{page_number}",
            "filename": path.name,
            "source_type": self._source_type,
            "type": "pdf",
            "question": "",
            "answer": "",
            "summary": '',
            "document_meta": {
                "page_number": n,
                **kwargs
            }
        }

    def processing_table(self, table, table_idx, page, **kwargs) -> dict:
        df = table.to_pandas()  # convert to pandas DataFrame
        df = df.dropna(axis=1, how='all')
        df = df.dropna(how='all', axis=0)  # Drop empty rows
        table_data = []
        # Extract text from each cell
        for row_idx in range(table.row_count):
            for col_idx in range(table.column_count):
                cell = table[row_idx][col_idx]
                print('CELL ', cell)
                print('---------')
                cell_text = cell.get_text("text", flags=fitz.TEXTFLAGS_HTML)
                print(cell_text)

        return table_data

    def _load_pdf(self, path: PurePath, **kwargs):
        """
        Open a PDF file.

        Args:
            path (PurePath): The path to the PDF file.

        Returns:
            fitz.PDF: The PDF object.
        """
        pdf = fitz.open(path)
        self.logger.info(f"Loading PDF file: {path}")
        for page_num in range(len(pdf)):
            # Will extract first the table and second the block of texts
            page = pdf.load_page(page_num)
            parts = page.get_text("dict", flags=fitz.TEXTFLAGS_HTML)
            # print('PARTS ', parts)
            blocks = page.get_text("dict")["blocks"]
            # print('BLOCKS >', blocks)
            metadata = self.set_metadata(path, page, page_num)
            # print('META > ', metadata)
            tables = page.find_tables(**self.table_settings)
            for tab_idx, table in enumerate(tables):
                table_data = self.processing_table(table, tab_idx, page)
        return []
