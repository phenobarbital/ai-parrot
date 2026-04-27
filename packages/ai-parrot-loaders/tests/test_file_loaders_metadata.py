"""Tests for file/document loader canonical metadata (TASK-857 / FEAT-125).

Verifies:
- txt.py passes kwargs through to create_document
- pdfmark.py base_metadata routes through create_metadata
- pdftables.py metadata routes through create_metadata
- imageunderstanding.py base_metadata routes through create_metadata
- Light-touch loaders produce document_meta with only canonical keys
- Loader-specific extras live at top level (not in document_meta)
"""
import pytest
from pathlib import Path

CANONICAL_DOC_META_KEYS = frozenset({"source_type", "category", "type", "language", "title"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_canonical_shape(meta: dict, *, test_name: str = "") -> None:
    """Assert that *meta* has canonical shape."""
    assert "document_meta" in meta, f"[{test_name}] missing document_meta"
    dm = meta["document_meta"]
    assert set(dm.keys()) == CANONICAL_DOC_META_KEYS, (
        f"[{test_name}] document_meta keys mismatch: got {set(dm.keys())}"
    )


# ---------------------------------------------------------------------------
# TextLoader
# ---------------------------------------------------------------------------

class TestTextLoaderMetadata:
    def test_emits_canonical_metadata(self):
        """create_metadata via create_document produces canonical document_meta."""
        from parrot_loaders.txt import TextLoader

        class ConcreteText(TextLoader):
            pass

        loader = ConcreteText()
        meta = loader.create_metadata(Path("/tmp/test.txt"))
        _assert_canonical_shape(meta, test_name="TextLoader")

    def test_language_in_document_meta(self):
        from parrot_loaders.txt import TextLoader

        class ConcreteText(TextLoader):
            pass

        loader = ConcreteText(language="fr")
        meta = loader.create_metadata(Path("/tmp/test.txt"))
        assert meta["document_meta"]["language"] == "fr"


# ---------------------------------------------------------------------------
# PDFMarkdownLoader (pdfmark.py)
# ---------------------------------------------------------------------------

class TestPDFMarkMetadata:
    def test_document_meta_closed_shape(self):
        """create_metadata via build_default_meta or direct call is canonical."""
        from parrot_loaders.pdfmark import PDFMarkdownLoader

        class ConcretePDFMark(PDFMarkdownLoader):
            pass

        loader = ConcretePDFMark(source=None)
        meta = loader.create_metadata(Path("/tmp/test.pdf"), doctype="pdf")
        _assert_canonical_shape(meta, test_name="PDFMarkdownLoader")

    def test_conversion_backend_at_top_level(self):
        """Non-canonical extras must be at top level, not in document_meta."""
        from parrot_loaders.pdfmark import PDFMarkdownLoader

        class ConcretePDFMark(PDFMarkdownLoader):
            pass

        loader = ConcretePDFMark(source=None)
        meta = loader.create_metadata(
            Path("/tmp/test.pdf"),
            doctype="pdf",
            conversion_backend="manual",
            pdf_author="Test Author",
        )
        assert "conversion_backend" in meta
        assert "pdf_author" in meta
        assert "conversion_backend" not in meta["document_meta"]
        assert "pdf_author" not in meta["document_meta"]

    def test_pdf_title_in_document_meta(self):
        """Title passed explicitly goes to document_meta.title."""
        from parrot_loaders.pdfmark import PDFMarkdownLoader

        class ConcretePDFMark(PDFMarkdownLoader):
            pass

        loader = ConcretePDFMark(source=None)
        meta = loader.create_metadata(
            Path("/tmp/test.pdf"),
            doctype="pdf",
            title="My PDF Document",
        )
        assert meta["document_meta"]["title"] == "My PDF Document"


# ---------------------------------------------------------------------------
# PDFTablesLoader (pdftables.py)
# ---------------------------------------------------------------------------

class TestPDFTablesMetadata:
    def test_document_meta_closed_shape(self):
        from parrot_loaders.pdftables import PDFTablesLoader

        class ConcretePDFTables(PDFTablesLoader):
            pass

        loader = ConcretePDFTables(source=None)
        meta = loader.create_metadata(Path("/tmp/test.pdf"), doctype="pdf_table")
        _assert_canonical_shape(meta, test_name="PDFTablesLoader")

    def test_table_info_at_top_level(self):
        """table_info (non-canonical) must be at top level."""
        from parrot_loaders.pdftables import PDFTablesLoader

        class ConcretePDFTables(PDFTablesLoader):
            pass

        loader = ConcretePDFTables(source=None)
        meta = loader.create_metadata(
            Path("/tmp/test.pdf"),
            doctype="pdf_table",
            table_info={"page_number": 1, "table_index": 0},
        )
        assert "table_info" in meta
        assert "table_info" not in meta["document_meta"]


# ---------------------------------------------------------------------------
# ImageUnderstandingLoader (imageunderstanding.py)
# ---------------------------------------------------------------------------

class TestImageUnderstandingMetadata:
    def test_extras_at_top_level(self):
        """Non-canonical extras like model_name live at top level."""
        from parrot_loaders.imageunderstanding import ImageUnderstandingLoader

        loader = ImageUnderstandingLoader()
        meta = loader.create_metadata(
            Path("/tmp/img.jpg"),
            doctype="image_analysis",
            source_type="file",
            model_name="gpt-4o",
        )
        assert "model_name" in meta
        assert "model_name" not in meta["document_meta"]

    def test_document_meta_closed_shape(self):
        from parrot_loaders.imageunderstanding import ImageUnderstandingLoader

        loader = ImageUnderstandingLoader()
        meta = loader.create_metadata(
            Path("/tmp/img.jpg"),
            doctype="image_understanding",
            source_type="image_understanding",
        )
        _assert_canonical_shape(meta, test_name="ImageUnderstandingLoader")

    def test_language_propagated(self):
        """Language passed to constructor flows to document_meta.language."""
        from parrot_loaders.imageunderstanding import ImageUnderstandingLoader

        loader = ImageUnderstandingLoader(language="de")
        meta = loader.create_metadata(
            Path("/tmp/img.jpg"),
            doctype="image_understanding",
            source_type="image_understanding",
            language=loader._language,
        )
        assert meta["document_meta"]["language"] == "de"


# ---------------------------------------------------------------------------
# Light-touch loaders — canonical shape via create_metadata
# ---------------------------------------------------------------------------

class TestDatabaseLoaderMetadata:
    def test_extras_at_top_level(self):
        """database.py: table, schema, row_index, driver are top-level extras."""
        from parrot_loaders.database import DatabaseLoader

        loader = DatabaseLoader(driver="postgresql", table="users")
        meta = loader.create_metadata(
            "users",
            doctype="db_row",
            source_type="database",
            table="users",
            schema="public",
            row_index=0,
            driver="postgresql",
        )
        assert "table" in meta
        assert "schema" in meta
        assert "table" not in meta["document_meta"]
        _assert_canonical_shape(meta, test_name="DatabaseLoader")


class TestDocxLoaderMetadata:
    def test_title_in_document_meta(self):
        """docx.py: title is canonical and must live in document_meta."""
        from parrot_loaders.docx import MSWordLoader

        loader = MSWordLoader()
        meta = loader.create_metadata(
            Path("/tmp/test.docx"),
            doctype="docx",
            source_type="file",
            title="My Document",
            author="Test Author",
            version="1.0",
        )
        assert meta["document_meta"]["title"] == "My Document"
        assert "author" in meta
        assert "version" in meta
        assert "author" not in meta["document_meta"]
        _assert_canonical_shape(meta, test_name="WordLoader")


class TestQALoaderMetadata:
    def test_question_answer_at_top_level(self):
        """qa.py: question and answer are non-canonical extras at top level."""
        from parrot_loaders.qa import QAFileLoader

        loader = QAFileLoader()
        meta = loader.create_metadata(
            Path("/tmp/test.csv"),
            doctype="faq",
            source_type="file",
            question="What is AI?",
            answer="Artificial Intelligence.",
        )
        assert "question" in meta
        assert "answer" in meta
        assert "question" not in meta["document_meta"]
        assert "answer" not in meta["document_meta"]
        _assert_canonical_shape(meta, test_name="QALoader")


class TestImageLoaderMetadata:
    def test_language_in_document_meta(self):
        """image.py: language= kwarg goes to document_meta.language."""
        from parrot_loaders.image import ImageLoader

        loader = ImageLoader()
        meta = loader.create_metadata(
            Path("/tmp/img.png"),
            doctype="image",
            source_type="image_ocr",
            language="es",
            ocr_backend="TesseractBackend",
        )
        assert meta["document_meta"]["language"] == "es"
        assert "ocr_backend" in meta
        assert "ocr_backend" not in meta["document_meta"]
        _assert_canonical_shape(meta, test_name="ImageLoader")


class TestExcelLoaderMetadata:
    def test_sheet_at_top_level(self):
        """excel.py: sheet, row_index etc are non-canonical extras."""
        from parrot_loaders.excel import ExcelLoader

        loader = ExcelLoader()
        meta = loader.create_metadata(
            Path("/tmp/test.xlsx"),
            doctype="excel",
            source_type="excel_sheet",
            sheet="Sheet1",
            content_type="sheet",
            total_rows=100,
        )
        assert "sheet" in meta
        assert "sheet" not in meta["document_meta"]
        _assert_canonical_shape(meta, test_name="ExcelLoader")


class TestCSVLoaderMetadata:
    def test_csv_extras_at_top_level(self):
        """csv.py: row_index, csv_info etc are non-canonical extras."""
        from parrot_loaders.csv import CSVLoader

        loader = CSVLoader()
        meta = loader.create_metadata(
            Path("/tmp/test.csv"),
            doctype="csv_row",
            source_type="csv",
            row_index=0,
            row_number=1,
            content_type="application/json",
        )
        assert "row_index" in meta
        assert "row_index" not in meta["document_meta"]
        _assert_canonical_shape(meta, test_name="CSVLoader")


class TestPPTLoaderMetadata:
    def test_slide_extras_at_top_level(self):
        """ppt.py: slide_number, extraction_backend etc are non-canonical extras."""
        from parrot_loaders.ppt import PowerPointLoader

        loader = PowerPointLoader()
        meta = loader.create_metadata(
            Path("/tmp/test.pptx"),
            doctype="pptx",
            source_type="powerpoint",
            slide_number=1,
            extraction_backend="markitdown",
        )
        assert "slide_number" in meta
        assert "slide_number" not in meta["document_meta"]
        _assert_canonical_shape(meta, test_name="PPTLoader")
