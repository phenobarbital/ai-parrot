from typing import Any, Union, List, Dict, Literal
import re
from collections.abc import Callable
from pathlib import PurePath
import json
import fitz
from ..stores.models import Document
from .basepdf import BasePDF

# Optional dependencies for enhanced table extraction
try:
    from markitdown import MarkItDown
    import pandas as pd
    ENHANCED_BACKENDS_AVAILABLE = True
except ImportError:
    ENHANCED_BACKENDS_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


class PDFTablesLoader(BasePDF):
    """
    Specialized loader for extracting tables from PDF files.

    This loader focuses on table extraction with multiple backends:
    1. PyMuPDF (fitz) with configurable table detection settings
    2. MarkItDown for universal table extraction (optional)

    Supports output formats:
    - JSON (via pandas DataFrame serialization)
    - Markdown table format
    - Raw table data (list of lists)
    """

    def __init__(
        self,
        source: Union[str, PurePath, List[PurePath]],
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'pdf',

        # Backend selection
        table_backend: str = "auto",  # "fitz", "markitdown", "auto"

        # Output format
        output_format: Literal["json", "markdown", "raw"] = "json",

        # PyMuPDF table extraction settings
        intersection_tolerance: float = 3.0,
        vertical_strategy: str = "lines",  # "lines", "text", "explicit"
        horizontal_strategy: str = "lines",  # "lines", "text", "explicit"
        min_words_vertical: int = 3,
        min_words_horizontal: int = 1,
        keep_blank_chars: bool = False,
        snap_tolerance: float = 3.0,
        join_tolerance: float = 3.0,
        edge_min_length: float = 3.0,

        # Table filtering and processing
        min_table_rows: int = 2,
        min_table_cols: int = 2,
        min_cell_content_length: int = 1,
        skip_empty_tables: bool = True,
        merge_duplicate_headers: bool = True,

        # Content processing
        clean_whitespace: bool = True,
        strip_html: bool = True,

        **kwargs
    ):
        super().__init__(
            source=source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )

        # Backend configuration
        self.table_backend = self._select_backend(table_backend)
        self.output_format = output_format

        # PyMuPDF table settings
        self.table_settings = {
            "intersection_tolerance": intersection_tolerance,
            "vertical_strategy": vertical_strategy,
            "horizontal_strategy": horizontal_strategy,
            "min_words_vertical": min_words_vertical,
            "min_words_horizontal": min_words_horizontal,
            "keep_blank_chars": keep_blank_chars,
            "snap_tolerance": snap_tolerance,
            "join_tolerance": join_tolerance,
            "edge_min_length": edge_min_length,
        }

        # Table filtering
        self.min_table_rows = min_table_rows
        self.min_table_cols = min_table_cols
        self.min_cell_content_length = min_cell_content_length
        self.skip_empty_tables = skip_empty_tables
        self.merge_duplicate_headers = merge_duplicate_headers

        # Content processing
        self.clean_whitespace = clean_whitespace
        self.strip_html = strip_html

        # Initialize backend
        self._setup_backend()

    def _select_backend(self, preferred: str) -> str:
        """Select the best available backend for table extraction."""
        if preferred == "auto":
            if ENHANCED_BACKENDS_AVAILABLE:
                return "markitdown"
            else:
                return "fitz"
        elif preferred == "markitdown" and ENHANCED_BACKENDS_AVAILABLE:
            return "markitdown"
        elif preferred == "fitz":
            return "fitz"
        else:
            self.logger.warning(f"Backend '{preferred}' not available, falling back to fitz")
            return "fitz"

    def _setup_backend(self):
        """Initialize the selected backend."""
        if self.table_backend == "markitdown":
            self.md_converter = MarkItDown()
            self.logger.info("Using MarkItDown backend for table extraction")
        else:
            self.logger.info("Using PyMuPDF (fitz) backend for table extraction")

    def _clean_cell_content(self, content: str) -> str:
        """Clean and normalize cell content."""
        if not content:
            return ""

        content = str(content)

        if self.clean_whitespace:
            # Normalize whitespace
            content = " ".join(content.split())

        if self.strip_html:
            # Basic HTML tag removal
            import re
            content = re.sub(r'<[^>]+>', '', content)

        return content.strip()

    def _is_valid_table(self, table_data: List[List[str]]) -> bool:
        """Check if extracted table meets minimum requirements."""
        if not table_data:
            return False

        # Check dimensions
        if len(table_data) < self.min_table_rows:
            return False

        if not all(len(row) >= self.min_table_cols for row in table_data):
            return False

        # Check if table has meaningful content
        if self.skip_empty_tables:
            non_empty_cells = 0
            total_cells = 0

            for row in table_data:
                for cell in row:
                    total_cells += 1
                    if cell and len(str(cell).strip()) >= self.min_cell_content_length:
                        non_empty_cells += 1

            # Require at least 30% non-empty cells
            if total_cells > 0 and (non_empty_cells / total_cells) < 0.3:
                return False

        return True

    def _format_table_as_json(self, table_data: List[List[str]], table_index: int) -> str:
        """Convert table data to JSON format using pandas."""
        if not PANDAS_AVAILABLE:
            # Fallback to basic JSON without pandas
            return json.dumps({
                "table_index": table_index,
                "headers": table_data[0] if table_data else [],
                "data": table_data[1:] if len(table_data) > 1 else [],
                "rows": len(table_data),
                "cols": len(table_data[0]) if table_data else 0
            }, ensure_ascii=False, indent=2)

        try:
            # Use pandas for better JSON structure
            df = pd.DataFrame(table_data[1:], columns=table_data[0] if table_data else [])

            # Create structured JSON
            result = {
                "table_index": table_index,
                "shape": {"rows": len(df), "cols": len(df.columns)},
                "columns": df.columns.tolist(),
                "data": df.to_dict('records'),  # List of row dictionaries
                "summary": {
                    "total_cells": len(df) * len(df.columns),
                    "empty_cells": df.isnull().sum().sum(),
                    "data_types": df.dtypes.astype(str).to_dict()
                }
            }

            return json.dumps(result, ensure_ascii=False, indent=2, default=str)

        except Exception as e:
            self.logger.warning(f"Pandas JSON conversion failed: {e}, using fallback")
            return json.dumps({
                "table_index": table_index,
                "headers": table_data[0] if table_data else [],
                "data": table_data[1:] if len(table_data) > 1 else [],
                "error": str(e)
            }, ensure_ascii=False, indent=2)

    def _format_table_as_markdown(self, table_data: List[List[str]]) -> str:
        """Convert table data to markdown format."""
        if not table_data or len(table_data) < 1:
            return ""

        markdown_lines = []

        # Header row
        headers = [self._clean_cell_content(cell) for cell in table_data[0]]
        header_row = " | ".join(headers)
        markdown_lines.append(f"| {header_row} |")

        # Separator row
        separator = " | ".join("---" for _ in headers)
        markdown_lines.append(f"| {separator} |")

        # Data rows
        for row in table_data[1:]:
            cleaned_row = [self._clean_cell_content(cell) for cell in row]
            # Ensure row has same number of columns as header
            while len(cleaned_row) < len(headers):
                cleaned_row.append("")
            data_row = " | ".join(cleaned_row[:len(headers)])
            markdown_lines.append(f"| {data_row} |")

        return "\n".join(markdown_lines)

    def _extract_tables_with_fitz(self, path: Union[str, PurePath]) -> List[Dict]:
        """Extract tables using PyMuPDF with configurable settings."""
        tables_data = []

        try:
            doc = fitz.open(str(path))

            for _, page_num in enumerate(doc):
                page = doc[page_num]

                # Find tables with custom settings
                tables = page.find_tables(
                    vertical_strategy=self.table_settings["vertical_strategy"],
                    horizontal_strategy=self.table_settings["horizontal_strategy"],
                    intersection_tolerance=self.table_settings["intersection_tolerance"],
                    min_words_vertical=self.table_settings["min_words_vertical"],
                    min_words_horizontal=self.table_settings["min_words_horizontal"],
                    keep_blank_chars=self.table_settings["keep_blank_chars"],
                    snap_tolerance=self.table_settings["snap_tolerance"],
                    join_tolerance=self.table_settings["join_tolerance"],
                    edge_min_length=self.table_settings["edge_min_length"],
                )

                for table_index, table in enumerate(tables):
                    try:
                        # Extract table data
                        raw_data = table.extract()

                        if not raw_data or not self._is_valid_table(raw_data):
                            continue

                        # Clean cell contents
                        cleaned_data = []
                        for row in raw_data:
                            cleaned_row = [self._clean_cell_content(cell) for cell in row]
                            cleaned_data.append(cleaned_row)

                        # Get table bbox for positioning info
                        bbox = table.bbox

                        table_info = {
                            "page_number": page_num + 1,
                            "table_index": table_index,
                            "global_table_index": len(tables_data),
                            "data": cleaned_data,
                            "dimensions": {
                                "rows": len(cleaned_data),
                                "cols": len(cleaned_data[0]) if cleaned_data else 0
                            },
                            "bbox": {
                                "x0": bbox.x0, "y0": bbox.y0,
                                "x1": bbox.x1, "y1": bbox.y1
                            },
                            "extraction_backend": "fitz",
                            "extraction_settings": self.table_settings.copy()
                        }

                        tables_data.append(table_info)

                    except Exception as e:
                        self.logger.warning(
                            f"Failed to extract table {table_index} from page {page_num + 1}: {e}"
                        )
                        continue

            doc.close()

        except Exception as e:
            self.logger.error(f"Failed to extract tables with fitz: {e}")

        return tables_data

    def _extract_tables_with_markitdown(self, path: Union[str, PurePath]) -> List[Dict]:
        """Extract tables using MarkItDown backend."""
        tables_data = []

        try:
            result = self.md_converter.convert(str(path))
            if not result or not result.text_content:
                return tables_data

            markdown_content = result.text_content

            # Extract markdown tables using regex
            table_pattern = r'(\|[^|\n]*\|(?:\n\|[^|\n]*\|)*)'
            tables = re.findall(table_pattern, markdown_content)

            for global_index, table_text in enumerate(tables):
                try:
                    lines = [line.strip() for line in table_text.split('\n') if line.strip()]
                    if len(lines) < 2:  # Need at least header and separator
                        continue

                    # Parse table rows
                    table_rows = []
                    for line in lines:
                        if '---' in line:  # Skip separator line
                            continue

                        # Split by | and clean
                        cells = [cell.strip() for cell in line.split('|')[1:-1]]  # Remove first and last empty
                        if cells:
                            table_rows.append(cells)

                    if not table_rows or not self._is_valid_table(table_rows):
                        continue

                    table_info = {
                        "page_number": 1,  # MarkItDown doesn't provide page info
                        "table_index": global_index,
                        "global_table_index": global_index,
                        "data": table_rows,
                        "dimensions": {
                            "rows": len(table_rows),
                            "cols": len(table_rows[0]) if table_rows else 0
                        },
                        "extraction_backend": "markitdown"
                    }

                    tables_data.append(table_info)

                except Exception as e:
                    self.logger.warning(f"Failed to parse table {global_index}: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Failed to extract tables with markitdown: {e}")

        return tables_data

    async def _load(self, path: Union[str, PurePath, List[PurePath]], **kwargs) -> List[Document]:
        """
        Load tables from PDF file.

        Args:
            path: Path to the PDF file

        Returns:
            List of Document objects, one per extracted table
        """
        self.logger.info(f"Extracting tables from PDF: {path}")
        docs = []

        # Extract tables using selected backend
        if self.table_backend == "markitdown":
            tables_data = self._extract_tables_with_markitdown(path)
        else:
            tables_data = self._extract_tables_with_fitz(path)

        if not tables_data:
            self.logger.warning(f"No tables found in {path}")
            return docs

        self.logger.info(f"Found {len(tables_data)} tables in {path}")

        # Extract PDF metadata
        try:
            pdf = fitz.open(str(path))
            pdf_metadata = pdf.metadata  # pylint: disable=E1101  # noqa: E1101
            pdf.close()
        except Exception as e:
            self.logger.warning(f"Could not extract PDF metadata: {e}")
            pdf_metadata = {}

        # Create documents for each table
        for table_info in tables_data:
            table_data = table_info["data"]

            # Format table content based on output format
            if self.output_format == "json":
                content = self._format_table_as_json(table_data, table_info["global_table_index"])
                content_type = "application/json"
            elif self.output_format == "markdown":
                content = self._format_table_as_markdown(table_data)
                content_type = "text/markdown"
            else:  # raw
                content = json.dumps(table_data, ensure_ascii=False, indent=2)
                content_type = "application/json"

            # Create metadata
            metadata = {
                "filename": path.name if hasattr(path, 'name') else str(path).split('/')[-1],
                "source": str(path),
                "type": "pdf_table",
                "category": self.category,
                "source_type": self._source_type,
                "content_type": content_type,
                "output_format": self.output_format,

                # Table-specific metadata
                "table_info": {
                    "page_number": table_info["page_number"],
                    "table_index": table_info["table_index"],
                    "global_table_index": table_info["global_table_index"],
                    "dimensions": table_info["dimensions"],
                    "extraction_backend": table_info["extraction_backend"]
                },

                # PDF metadata
                "document_meta": {
                    "title": pdf_metadata.get("title", ""),
                    "author": pdf_metadata.get("author", ""),
                    "creationDate": pdf_metadata.get("creationDate", ""),
                }
            }

            # Add backend-specific metadata
            if "bbox" in table_info:
                metadata["table_info"]["bbox"] = table_info["bbox"]
            if "extraction_settings" in table_info:
                metadata["table_info"]["extraction_settings"] = table_info["extraction_settings"]

            docs.append(
                Document(
                    page_content=content,
                    metadata=metadata
                )
            )

        return docs

    def get_table_settings(self) -> Dict[str, Any]:
        """Get current table extraction settings."""
        return {
            "backend": self.table_backend,
            "output_format": self.output_format,
            "table_settings": self.table_settings.copy(),
            "filtering": {
                "min_table_rows": self.min_table_rows,
                "min_table_cols": self.min_table_cols,
                "min_cell_content_length": self.min_cell_content_length,
                "skip_empty_tables": self.skip_empty_tables,
            }
        }

    def update_table_settings(self, **settings):
        """Update table extraction settings."""
        for key, value in settings.items():
            if key in self.table_settings:
                self.table_settings[key] = value
                self.logger.info(f"Updated table setting {key} = {value}")
            elif hasattr(self, key):
                setattr(self, key, value)
                self.logger.info(f"Updated loader setting {key} = {value}")
            else:
                self.logger.warning(f"Unknown setting: {key}")

    def get_supported_backends(self) -> List[str]:
        """Get list of available backends."""
        backends = ["fitz"]  # Always available

        if ENHANCED_BACKENDS_AVAILABLE:
            backends.append("markitdown")

        return backends
