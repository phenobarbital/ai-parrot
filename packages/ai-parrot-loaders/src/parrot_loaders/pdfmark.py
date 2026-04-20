from __future__ import annotations
from typing import Any, Union, List, TYPE_CHECKING
import logging
import re
from collections.abc import Callable
from pathlib import PurePath
import fitz
from parrot.stores.models import Document
from .basepdf import BasePDF
from parrot._imports import lazy_import

# Option 1: Use MarkItDown (Microsoft's universal document converter)
try:
    _markitdown_mod = lazy_import("markitdown", extra="pdf")
    MarkItDown = _markitdown_mod.MarkItDown
    MARKITDOWN_AVAILABLE = True
except ImportError:
    MarkItDown = None  # type: ignore[assignment,misc]
    MARKITDOWN_AVAILABLE = False

# Option 2: Use pymupdf4llm (updated PyMuPDF library)
try:
    import pymupdf4llm
    PYMUPDF4LLM_AVAILABLE = True
except ImportError:
    PYMUPDF4LLM_AVAILABLE = False


logger = logging.getLogger('pdfminer').setLevel(logging.INFO)

class PDFMarkdownLoader(BasePDF):
    """
    Loader for PDF files converted content to markdown.

    This loader supports multiple backends for PDF to markdown conversion:
    1. MarkItDown (Microsoft's universal document converter)
    2. pymupdf4llm (PyMuPDF's markdown converter)
    3. Fallback manual conversion using PyMuPDF
    """

    extensions: List[str] = {'.pdf'}

    def __init__(
        self,
        source: Union[str, PurePath, List[PurePath]],
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'pdf',
        language: str = "eng",
        markdown_backend: str = "auto",  # "markitdown", "pymupdf4llm", "manual", "auto"
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        preserve_tables: bool = True,
        extract_images: bool = False,
        **kwargs
    ):
        super().__init__(
            source=source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )
        self._language = language
        self.markdown_backend = self._select_backend(markdown_backend)
        self.preserve_tables = preserve_tables
        self.extract_images = extract_images

        # Initialize markdown splitter
        self._splitter = self._get_markdown_splitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

        # Initialize conversion backend
        self._setup_conversion_backend()

    def _select_backend(self, preferred: str) -> str:
        """Select the best available backend for PDF to markdown conversion."""
        if preferred == "auto":
            if MARKITDOWN_AVAILABLE:
                return "markitdown"
            elif PYMUPDF4LLM_AVAILABLE:
                return "pymupdf4llm"
            else:
                return "manual"
        elif preferred == "markitdown" and MARKITDOWN_AVAILABLE:
            return "markitdown"
        elif preferred == "pymupdf4llm" and PYMUPDF4LLM_AVAILABLE:
            return "pymupdf4llm"
        elif preferred == "manual":
            return "manual"
        else:
            # Fallback to available backend
            self.logger.warning(f"Preferred backend '{preferred}' not available, using fallback")
            return self._select_backend("auto")

    def _setup_conversion_backend(self):
        """Initialize the selected conversion backend."""
        if self.markdown_backend == "markitdown":
            self.md_converter = MarkItDown()
            self.logger.info("Using MarkItDown backend for PDF to markdown conversion")
        elif self.markdown_backend == "pymupdf4llm":
            self.logger.info("Using pymupdf4llm backend for PDF to markdown conversion")
        else:
            self.logger.info("Using manual PyMuPDF backend for PDF to markdown conversion")

    def _convert_to_markdown_markitdown(self, path: Union[str, PurePath]) -> str:
        """Convert PDF to markdown using MarkItDown."""
        try:
            result = self.md_converter.convert(str(path))
            return result.text_content if result else ""
        except Exception as e:
            self.logger.error(f"MarkItDown conversion failed: {e}")
            return self._convert_to_markdown_manual(path)

    def _convert_to_markdown_pymupdf4llm(self, path: Union[str, PurePath]) -> str:
        """Convert PDF to markdown using pymupdf4llm."""
        try:
            return pymupdf4llm.to_markdown(str(path))
        except Exception as e:
            self.logger.error(f"pymupdf4llm conversion failed: {e}")
            return self._convert_to_markdown_manual(path)

    def _convert_to_markdown_manual(self, path: Union[str, PurePath]) -> str:
        """Fallback manual conversion using PyMuPDF with basic markdown formatting."""
        try:
            doc = fitz.open(str(path))
            markdown_text = []

            for _, page_num in enumerate(doc):
                page = doc[page_num]

                # Extract text blocks with formatting
                blocks = page.get_text("dict")["blocks"]

                for block in blocks:
                    if "lines" in block:
                        block_text = []
                        for line in block["lines"]:
                            line_text = ""
                            for span in line["spans"]:
                                text = span["text"]
                                font_size = span.get("size", 12)
                                flags = span.get("flags", 0)

                                # Basic formatting based on font properties
                                if font_size > 16:
                                    text = f"# {text}"
                                elif font_size > 14:
                                    text = f"## {text}"
                                elif font_size > 12:
                                    text = f"### {text}"

                                # Bold text
                                if flags & 2**4:  # Bold flag
                                    text = f"**{text}**"

                                # Italic text
                                if flags & 2**6:  # Italic flag
                                    text = f"*{text}*"

                                line_text += text

                            if line_text.strip():
                                block_text.append(line_text)

                        if block_text:
                            markdown_text.append("\n".join(block_text))

                # Extract tables if requested
                if self.preserve_tables:
                    tables = page.find_tables()
                    for table in tables:
                        try:
                            table_data = table.extract()
                            if table_data:
                                markdown_table = self._format_table_as_markdown(table_data)
                                if markdown_table:
                                    markdown_text.append(markdown_table)
                        except Exception as e:
                            self.logger.debug(f"Failed to extract table: {e}")

            doc.close()
            return "\n\n".join(markdown_text)

        except Exception as e:
            self.logger.error(f"Manual PDF conversion failed: {e}")
            return ""

    def _infer_markdown_headers(self, content: str) -> str:
        """Infer markdown headers from flat PDF-to-markdown output.

        MarkItDown and pymupdf4llm often produce flat text without proper
        markdown headers. Detects ALL CAPS lines, bold-wrapped lines, and
        short standalone title-like lines, converting them to headers.

        Args:
            content: Markdown text potentially missing headers.

        Returns:
            Content with inferred headers added.
        """
        existing_headers = re.findall(r'^#{1,6}\s+', content, re.MULTILINE)
        if len(existing_headers) >= 3:
            return content

        lines = content.split('\n')
        result = []
        first_header_seen = False

        toc_pattern = re.compile(r'\.{3,}|\.{2,}\s*\d+\s*$|^\s*\d+\s*$')
        allcaps_pattern = re.compile(r'^[A-Z][A-Z0-9\s:,/&\-–—]{2,}$')
        bold_pattern = re.compile(r'^\*\*(.+?)\*\*\.?$')
        sentence_pattern = re.compile(r'[a-z]{2,}\.\s+[A-Z]')

        def _prefix(default: str) -> str:
            nonlocal first_header_seen
            if not first_header_seen:
                first_header_seen = True
                return '#'
            return default

        for i, raw_line in enumerate(lines):
            line = raw_line.strip()
            prev_blank = (i == 0) or (lines[i - 1].strip() == '')
            next_blank = (i == len(lines) - 1) or (
                i + 1 < len(lines) and lines[i + 1].strip() == ''
            )

            if not line or toc_pattern.search(line):
                result.append(raw_line)
                continue

            if line.startswith('#'):
                first_header_seen = True
                result.append(raw_line)
                continue

            word_count = len(line.split())
            is_short = word_count <= 8 and len(line) <= 80
            is_standalone = prev_blank and next_blank

            if (
                allcaps_pattern.match(line)
                and is_standalone
                and word_count >= 2
                and not sentence_pattern.search(line)
            ):
                result.append(f'{_prefix("##")} {line.title()}')
                continue

            bold_match = bold_pattern.match(line)
            if bold_match and is_standalone and is_short:
                result.append(f'{_prefix("##")} {bold_match.group(1).strip()}')
                continue

            if (
                is_short
                and is_standalone
                and word_count >= 2
                and not sentence_pattern.search(line)
                and not line.endswith('.')
                and not line.startswith(('-', '*', '|', '>'))
                and not re.match(r'^\d+\.\s', line)
            ):
                first_alpha = next((c for c in line if c.isalpha()), '')
                if first_alpha and first_alpha.isupper():
                    result.append(f'{_prefix("###")} {line}')
                    continue

            result.append(raw_line)

        return '\n'.join(result)

    def _format_table_as_markdown(self, table_data: List[List[str]]) -> str:
        """Convert table data to markdown format."""
        if not table_data or len(table_data) < 1:
            return ""

        markdown_rows = []

        # Header row
        header_row = " | ".join(str(cell) if cell else "" for cell in table_data[0])
        markdown_rows.append(f"| {header_row} |")

        # Separator row
        separator = " | ".join("---" for _ in table_data[0])
        markdown_rows.append(f"| {separator} |")

        # Data rows
        for row in table_data[1:]:
            data_row = " | ".join(str(cell) if cell else "" for cell in row)
            markdown_rows.append(f"| {data_row} |")

        return "\n".join(markdown_rows)

    async def _load(self, path: Union[str, PurePath, List[PurePath]], **kwargs) -> List[Document]:
        """
        Load a PDF file and convert to markdown format.

        Args:
            path (Union[str, PurePath, List[PurePath]]): The path to the PDF file.

        Returns:
            List[Document]: A list of AI-Parrot Documents.
        """
        self.logger.info(f"Loading PDF file: {path}")
        docs = []

        # Convert to markdown using selected backend
        if self.markdown_backend == "markitdown":
            md_text = self._convert_to_markdown_markitdown(path)
        elif self.markdown_backend == "pymupdf4llm":
            md_text = self._convert_to_markdown_pymupdf4llm(path)
        else:
            md_text = self._convert_to_markdown_manual(path)

        if not md_text.strip():
            self.logger.warning(f"No markdown content extracted from {path}")
            return docs

        # Infer headers from flat MarkItDown/pymupdf output
        md_text = self._infer_markdown_headers(md_text)

        # Remove form-feed page-break characters that cause mid-sentence splits
        md_text = md_text.replace('\x0c', '')
        md_text = re.sub(r'\n{3,}', '\n\n', md_text)

        # Extract PDF metadata
        try:
            pdf = fitz.open(str(path))
            pdf_metadata = pdf.metadata  # pylint: disable=E1101  # noqa: E1101
            pdf.close()
        except Exception as e:
            self.logger.warning(
                f"Could not extract PDF metadata: {e}"
            )
            pdf_metadata = {}

        # Generate summary if enabled
        try:
            summary = await self.summary_from_text(md_text)
        except Exception as e:
            self.logger.warning(
                f"Summary generation failed: {e}"
            )
            summary = ''

        # Create base metadata
        base_metadata = {
            "url": '',
            "filename": path.name if hasattr(path, 'name') else str(path).rsplit('/', maxsplit=1)[-1],  # noqa
            "source": str(path.name if hasattr(path, 'name') else path),
            "type": 'pdf',
            "data": {},
            "category": self.category,
            "source_type": self._source_type,
            "conversion_backend": self.markdown_backend,
            "document_meta": {
                "title": pdf_metadata.get("title", ""),
                "creationDate": pdf_metadata.get("creationDate", ""),
                "author": pdf_metadata.get("author", ""),
            }
        }

        # Add summary document if available
        if summary:
            summary_metadata = {
                **base_metadata,
                "content_type": "summary"
            }
            docs.append(
                Document(
                    page_content=summary,
                    metadata=summary_metadata
                )
            )

        # Split markdown content into chunks
        try:
            chunks = self._splitter.split_text(md_text)
            self.logger.info(f"Split document into {len(chunks)} chunks")
        except Exception as e:
            self.logger.error(
                f"Failed to split text: {e}"
            )
            # Fallback: use the entire text as one chunk
            chunks = [md_text]

        # Create documents for each chunk
        for chunk_index, chunk in enumerate(chunks):
            chunk_metadata = {
                **base_metadata,
                "content_type": "chunk",
                "chunk_index": chunk_index,
                "total_chunks": len(chunks)
            }

            docs.append(
                Document(
                    page_content=chunk,
                    metadata=chunk_metadata
                )
            )

        return docs

    def get_supported_backends(self) -> List[str]:
        """Get list of available conversion backends."""
        backends = ["manual"]  # Always available

        if MARKITDOWN_AVAILABLE:
            backends.append("markitdown")
        if PYMUPDF4LLM_AVAILABLE:
            backends.append("pymupdf4llm")

        return backends
