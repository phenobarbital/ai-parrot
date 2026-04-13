"""Tests for PrintPDFHandler."""
import pytest


class TestPrintPDFHandlerImport:
    """Verify the handler is importable."""

    def test_handler_class_exists(self):
        from parrot.handlers.print_pdf import PrintPDFHandler
        assert PrintPDFHandler is not None

    def test_lazy_import_from_package(self):
        from parrot.handlers import PrintPDFHandler
        assert PrintPDFHandler is not None

    def test_handler_has_post_method(self):
        from parrot.handlers.print_pdf import PrintPDFHandler
        assert hasattr(PrintPDFHandler, "post")

    def test_handler_logger_name(self):
        from parrot.handlers.print_pdf import PrintPDFHandler
        assert PrintPDFHandler._logger_name == "Parrot.PrintPDF"


class TestPDFGeneration:
    """Test the PDF generation logic directly (no HTTP mocking)."""

    @pytest.fixture
    def sample_html(self):
        return """<!DOCTYPE html>
<html><head><title>Test</title></head>
<body><h1>Hello PDF</h1><p>Test content.</p></body>
</html>"""

    @pytest.fixture
    def minimal_html(self):
        return "<h1>Minimal</h1>"

    def test_weasyprint_produces_pdf_bytes(self, sample_html):
        """weasyprint converts HTML to valid PDF bytes."""
        try:
            from parrot._imports import lazy_import
            _weasyprint = lazy_import("weasyprint", extra="pdf")
        except ImportError:
            pytest.skip("weasyprint not installed")

        pdf_bytes = _weasyprint.HTML(string=sample_html).write_pdf(
            presentational_hints=True
        )
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0
        # PDF magic bytes
        assert pdf_bytes[:5] == b"%PDF-"

    def test_minimal_html_produces_pdf(self, minimal_html):
        """Even minimal HTML (no doctype) produces valid PDF."""
        try:
            from parrot._imports import lazy_import
            _weasyprint = lazy_import("weasyprint", extra="pdf")
        except ImportError:
            pytest.skip("weasyprint not installed")

        pdf_bytes = _weasyprint.HTML(string=minimal_html).write_pdf(
            presentational_hints=True
        )
        assert pdf_bytes[:5] == b"%PDF-"
