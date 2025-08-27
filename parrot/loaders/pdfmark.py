from typing import Any, Union, List
import logging
from collections.abc import Callable
from pathlib import PurePath
import fitz
from ..stores.models import Document
from .basepdf import BasePDF
# Option 1: Use MarkItDown (Microsoft's universal document converter)
try:
    from markitdown import MarkItDown
    MARKITDOWN_AVAILABLE = True
except ImportError:
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
        chunk_size: int = 1024,
        chunk_overlap: int = 10,
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
