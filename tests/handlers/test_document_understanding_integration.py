"""Integration tests for document_understanding() — TASK-1364 (FEAT-203).

These tests call the real Gemini API. They are gated behind the
``@pytest.mark.integration`` marker and require a valid ``GOOGLE_API_KEY``
environment variable to be set.

Run with:
    pytest tests/handlers/test_document_understanding_integration.py -v -m integration
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from parrot.clients.google import GoogleGenAIClient
from parrot.models import AIMessage, StructuredOutputConfig


# ---------------------------------------------------------------------------
# Minimal inline PDF bytes
# ---------------------------------------------------------------------------

# A minimal, valid PDF that contains readable text.  This avoids any external
# file dependency and keeps the uploaded document under 1 KB.
_MINIMAL_PDF_BYTES: bytes = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj

2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj

3 0 obj
<<
  /Type /Page
  /Parent 2 0 R
  /MediaBox [0 0 612 792]
  /Contents 4 0 R
  /Resources << /Font << /F1 5 0 R >> >>
>>
endobj

4 0 obj
<< /Length 44 >>
stream
BT /F1 12 Tf 100 700 Td (Hello from AI-Parrot test.) Tj ET
endstream
endobj

5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj

xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000062 00000 n
0000000119 00000 n
0000000274 00000 n
0000000369 00000 n

trailer
<< /Size 6 /Root 1 0 R >>
startxref
451
%%EOF
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def client() -> GoogleGenAIClient:
    """Real GoogleGenAIClient — requires GOOGLE_API_KEY env var."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("GOOGLE_API_KEY not set — skipping integration tests")
    return GoogleGenAIClient(api_key=api_key)


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Write the inline minimal PDF to a temp file."""
    pdf_path = tmp_path / "ai_parrot_test.pdf"
    pdf_path.write_bytes(_MINIMAL_PDF_BYTES)
    return pdf_path


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDocumentUnderstandingIntegration:
    """End-to-end tests for document_understanding() against the Gemini API."""

    async def test_real_pdf_analysis(
        self, client: GoogleGenAIClient, sample_pdf: Path
    ) -> None:
        """Send a small real PDF to Gemini and verify a non-empty AIMessage response."""
        result = await client.document_understanding(
            prompt="What is the main text content of this document? Reply in one sentence.",
            documents=sample_pdf,
        )

        assert isinstance(result, AIMessage), "Expected an AIMessage instance"
        assert result.provider == "google_genai", (
            f"Expected provider='google_genai', got {result.provider!r}"
        )
        assert result.output, "Expected non-empty output from Gemini"
        assert result.usage is not None, "Expected usage metadata to be populated"

    async def test_real_structured_output(
        self, client: GoogleGenAIClient, sample_pdf: Path
    ) -> None:
        """Extract structured data from a PDF and verify AIMessage.structured_output."""

        class DocumentSummary(BaseModel):
            title: str = Field(description="A short title for the document")
            main_text: str = Field(
                description="The main text content found in the document"
            )

        result = await client.document_understanding(
            prompt=(
                "Extract the title and main text content from this document. "
                "Return only the JSON structure — no markdown fences."
            ),
            documents=sample_pdf,
            structured_output=DocumentSummary,
        )

        assert isinstance(result, AIMessage), "Expected an AIMessage instance"
        assert result.provider == "google_genai"
        assert result.structured_output is not None, (
            "Expected structured_output to be populated when DocumentSummary was requested"
        )
        assert isinstance(result.structured_output, DocumentSummary), (
            f"Expected structured_output to be DocumentSummary, got "
            f"{type(result.structured_output)}"
        )
