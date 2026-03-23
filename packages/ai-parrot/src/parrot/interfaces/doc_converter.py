"""DocumentConverterInterface - Helper for document conversion via Docling."""
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from navconfig.logging import logging


logger = logging.getLogger("Parrot.Interfaces.DocConverter")

# Supported input formats (kept as constants for reference)
SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.pptx', '.html', '.md', '.asciidoc'}


class DocumentConverterInterface:
    """Wraps Docling's DocumentConverter with async support and configurable options."""

    def __init__(
        self,
        *,
        do_ocr: bool = False,
        use_tesseract: bool = False,
        do_table_structure: bool = True,
        do_cell_matching: bool = True,
        artifacts_path: Optional[str] = None,
        max_num_pages: int = 100,
        max_file_size: int = 20971520,
    ):
        self.do_ocr = do_ocr
        self.use_tesseract = use_tesseract
        self.do_table_structure = do_table_structure
        self.do_cell_matching = do_cell_matching
        self.artifacts_path = artifacts_path
        self.max_num_pages = max_num_pages
        self.max_file_size = max_file_size
        self._converter = None

    def _get_converter(self):
        """Lazy-initialise the Docling DocumentConverter."""
        if self._converter is not None:
            return self._converter

        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_options = PdfPipelineOptions(
            do_table_structure=self.do_table_structure,
        )
        pipeline_options.table_structure_options.do_cell_matching = self.do_cell_matching

        if self.artifacts_path:
            pipeline_options.artifacts_path = self.artifacts_path

        if self.do_ocr:
            pipeline_options.do_ocr = True
            if self.use_tesseract:
                from docling.datamodel.pipeline_options import TesseractOcrOptions
                pipeline_options.ocr_options = TesseractOcrOptions()

        format_options = {
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }

        self._converter = DocumentConverter(format_options=format_options)
        logger.info("Docling DocumentConverter initialised")
        return self._converter

    def _convert_sync(
        self,
        source: str,
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> Any:
        """Run the blocking Docling conversion (called inside an executor)."""
        converter = self._get_converter()
        kwargs: Dict[str, Any] = {}
        if max_num_pages is not None:
            kwargs["max_num_pages"] = max_num_pages
        if max_file_size is not None:
            kwargs["max_file_size"] = max_file_size
        return converter.convert(source, **kwargs)

    async def convert(
        self,
        source: Union[str, Path],
        *,
        output_format: str = "markdown",
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> Union[str, Dict[str, Any]]:
        """Convert a document source to the requested output format.

        Args:
            source: Local path or URL to the document.
            output_format: ``"markdown"`` or ``"json"``.
            max_num_pages: Override for page limit.
            max_file_size: Override for file-size limit (bytes).

        Returns:
            Markdown string when *output_format* is ``"markdown"``,
            JSON-serializable dict when ``"json"``.
        """
        source_str = str(source)
        _max_pages = max_num_pages or self.max_num_pages
        _max_size = max_file_size or self.max_file_size

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            self._convert_sync,
            source_str,
            _max_pages,
            _max_size,
        )

        if output_format == "json":
            return result.document.export_to_dict()
        return result.document.export_to_markdown()

    async def convert_to_markdown(
        self,
        source: Union[str, Path],
        **kwargs,
    ) -> str:
        """Convenience wrapper returning markdown."""
        return await self.convert(source, output_format="markdown", **kwargs)

    async def convert_to_json(
        self,
        source: Union[str, Path],
        **kwargs,
    ) -> Dict[str, Any]:
        """Convenience wrapper returning a JSON-serializable dict."""
        return await self.convert(source, output_format="json", **kwargs)
