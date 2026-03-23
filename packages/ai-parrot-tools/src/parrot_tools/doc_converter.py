"""DocumentConverterTool - Convert documents to JSON/Markdown via Docling."""
from typing import Any, Dict, Literal, Optional

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
        from ..interfaces.doc_converter import DocumentConverterInterface

        interface = DocumentConverterInterface(
            do_ocr=do_ocr,
            use_tesseract=use_tesseract,
            do_table_structure=do_table_structure,
        )

        result = await interface.convert(
            source,
            output_format=output_format,
            max_num_pages=max_num_pages,
        )

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
