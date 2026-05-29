"""
PrintPDFHandler — Convert HTML to PDF via HTTP.

Provides a simple utility endpoint that accepts an HTML body and returns
a PDF binary response using weasyprint.
"""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session


@is_authenticated()
@user_session()
class PrintPDFHandler(BaseView):
    """Converts HTML to PDF and returns the PDF as a binary response.

    Endpoints:
        POST /api/v1/utilities/print2pdf

    Accepts:
        - Content-Type: text/html — raw HTML body.
        - Content-Type: application/json — ``{"html": "...", "filename": "...", "disposition": "..."}``.

    Returns:
        application/pdf binary with Content-Disposition header.
    """

    _logger_name: str = "Parrot.PrintPDF"

    def post_init(self, *args: Any, **kwargs: Any) -> None:
        self.logger = logging.getLogger(self._logger_name)

    async def post(self) -> web.Response:
        """Accept HTML body and return a PDF binary response."""
        content_type = self.request.content_type or ""
        filename = "document.pdf"
        disposition = "attachment"

        # Extract HTML from request body
        if "application/json" in content_type:
            try:
                body = await self.request.json()
            except Exception:
                return self.error(
                    response={"error": "Invalid JSON body"},
                    status=400,
                )
            if not isinstance(body, dict) or "html" not in body:
                return self.error(
                    response={"error": "JSON body must contain an 'html' field"},
                    status=400,
                )
            html = body["html"]
            filename = body.get("filename", filename)
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            disposition = body.get("disposition", disposition)
            if disposition not in ("inline", "attachment"):
                disposition = "attachment"
        else:
            # Treat as raw HTML (text/html or any other content type)
            html = await self.request.text()

        if not html or not html.strip():
            return self.error(
                response={"error": "Empty HTML body"},
                status=400,
            )

        # Convert HTML to PDF via weasyprint in a thread executor
        try:
            from parrot._imports import lazy_import
            _weasyprint = lazy_import("weasyprint", extra="pdf")

            loop = asyncio.get_event_loop()
            pdf_bytes = await loop.run_in_executor(
                None,
                partial(
                    _weasyprint.HTML(string=html).write_pdf,
                    presentational_hints=True,
                ),
            )
        except ImportError as exc:
            self.logger.error("weasyprint not installed: %s", exc)
            return self.error(
                response={
                    "error": "PDF generation is not available. "
                    "Install the 'pdf' extra: pip install ai-parrot[pdf]"
                },
                status=503,
            )
        except Exception as exc:
            self.logger.error("PDF generation failed: %s", exc, exc_info=True)
            return self.error(
                response={"error": f"PDF generation failed: {exc}"},
                status=500,
            )

        self.logger.info(
            "Generated PDF: %d bytes, filename=%s", len(pdf_bytes), filename
        )

        return web.Response(
            body=pdf_bytes,
            content_type="application/pdf",
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"',
            },
        )
