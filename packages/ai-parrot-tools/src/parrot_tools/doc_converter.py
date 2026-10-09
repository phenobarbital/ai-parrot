"""DocumentConverterTool - Convert documents to JSON/Markdown via Docling."""
import os
import tempfile
from typing import Any, Dict, Literal, Optional
from urllib.parse import urlparse

import aiohttp

from pydantic import Field

from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult


class DocumentConverterToolArgs(AbstractToolArgsSchema):
    """Arguments for DocumentConverterTool."""

    source: str = Field(
        ...,
        description="Local file path or URL of the document to convert",
    )
    output_format: Literal["json", "markdown"] = Field(
        default="json",
        description="Desired output format: 'json' or 'markdown'",
    )
    max_num_pages: Optional[int] = Field(
        default=100,
        description="Maximum number of pages to process",
    )
    do_ocr: bool = Field(
        default=False,
        description="Enable OCR for scanned documents",
    )
    use_tesseract: bool = Field(
        default=False,
        description="Use Tesseract OCR engine (requires tesserocr)",
    )
    do_table_structure: bool = Field(
        default=True,
        description="Enable table structure extraction",
    )


class DocumentConverterTool(AbstractTool):
    """Convert documents (PDF, DOCX, PPTX) to structured JSON or Markdown using Docling."""

    name = "DocumentConverterTool"
    description = (
        "Converts PDF, DOCX, and PPTX documents into structured JSON or Markdown "
        "using the Docling library. Supports OCR (Tesseract) and table extraction."
    )
    args_schema = DocumentConverterToolArgs
    max_download_bytes = 50 * 1024 * 1024

    def __init__(self, url_only: bool = False, **kwargs: Any) -> None:
        """Create the tool.

        Args:
            url_only: PA-14 host switch (forced through the PA-9 hook): ``source`` must be an http(s) URL and is
                downloaded by the tool itself (through the egress guard); a local path is refused and never read.
        """
        super().__init__(**kwargs)
        self.url_only = bool(url_only)

    async def _download(self, source: str) -> str:
        """Fetch ``source`` into a private temp file (egress-guarded, size-capped) and return its path."""
        from parrot.tools.egress import egress_session

        parsed = urlparse(source)
        suffix = os.path.splitext(parsed.path)[1][:10]
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="docconv_")
        try:
            total = 0
            async with egress_session(timeout=aiohttp.ClientTimeout(total=120)) as session:
                async with session.get(source) as resp:
                    if resp.status != 200:
                        raise ValueError(f"download failed with HTTP status {resp.status}")
                    with os.fdopen(fd, "wb") as fh:
                        async for chunk in resp.content.iter_chunked(65536):
                            total += len(chunk)
                            if total > self.max_download_bytes:
                                raise ValueError("document exceeds the download size limit")
                            fh.write(chunk)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            os.unlink(path)
            raise
        return path

    async def _execute(
        self,
        source: str,
        output_format: str = "json",
        max_num_pages: int = 100,
        do_ocr: bool = False,
        use_tesseract: bool = False,
        do_table_structure: bool = True,
        **_: Any,
    ) -> ToolResult:
        from parrot.interfaces.doc_converter import DocumentConverterInterface

        local_copy: Optional[str] = None
        if self.url_only:
            if urlparse(source).scheme not in ("http", "https"):
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error="source must be an http(s) URL; local files are not accepted",
                    metadata={"tool_name": self.name},
                )
            try:
                local_copy = await self._download(source)
            except Exception as exc:  # pylint: disable=broad-except
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=f"could not fetch the document: {exc}",
                    metadata={"tool_name": self.name},
                )
        interface = DocumentConverterInterface(
            do_ocr=do_ocr,
            use_tesseract=use_tesseract,
            do_table_structure=do_table_structure,
        )

        try:
            result = await interface.convert(
                local_copy or source,
                output_format=output_format,
                max_num_pages=max_num_pages,
            )
        finally:
            if local_copy:
                os.unlink(local_copy)

        return ToolResult(
            success=True,
            status="success",
            result=result,
            metadata={
                "source": source,
                "output_format": output_format,
                "tool_name": self.name,
            },
        )
