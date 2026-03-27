"""Tests for DocumentConverterLoader using Docling."""
import asyncio
import tempfile
from pathlib import Path

import pytest
import httpx

from parrot.stores.models import Document
from parrot.loaders.doc_converter import DocumentConverterLoader


ARXIV_PDF_URL = "https://arxiv.org/pdf/2408.09869"


@pytest.fixture(scope="module")
def pdf_path(tmp_path_factory) -> Path:
    """Download the arxiv PDF to a temporary file once per module."""
    dest = tmp_path_factory.mktemp("docs") / "docling_paper.pdf"
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        resp = client.get(ARXIV_PDF_URL)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


@pytest.mark.asyncio
async def test_loader_returns_documents(pdf_path: Path):
    """Load a real PDF and verify we get Document objects back."""
    loader = DocumentConverterLoader(source=pdf_path)
    docs = await loader.load(split_documents=False)

    assert isinstance(docs, list), "Expected a list of documents"
    assert len(docs) > 0, "Expected at least one document"

    for doc in docs:
        assert isinstance(doc, Document), f"Expected Document, got {type(doc)}"
        assert doc.page_content, "Document page_content should not be empty"
        assert doc.metadata, "Document metadata should not be empty"


@pytest.mark.asyncio
async def test_loader_metadata_keys(pdf_path: Path):
    """Verify expected metadata keys are present."""
    loader = DocumentConverterLoader(source=pdf_path)
    docs = await loader.load(split_documents=False)

    expected_keys = {"filename", "type", "source_type", "document_meta"}
    for doc in docs:
        assert expected_keys.issubset(
            doc.metadata.keys()
        ), f"Missing metadata keys. Got: {list(doc.metadata.keys())}"

        doc_meta = doc.metadata.get("document_meta", {})
        assert "document_type" in doc_meta, "document_meta should contain 'document_type'"


@pytest.mark.asyncio
async def test_loader_with_sections(pdf_path: Path):
    """Verify section splitting produces multiple documents."""
    loader = DocumentConverterLoader(
        source=pdf_path,
        use_sections=True,
        min_section_length=20,
    )
    docs = await loader.load(split_documents=False)

    assert len(docs) > 1, "Expected multiple documents when splitting by sections"

    for doc in docs:
        assert isinstance(doc, Document)


@pytest.mark.asyncio
async def test_loader_from_url():
    """Load a document directly from a URL."""
    loader = DocumentConverterLoader()
    docs = await loader.load(source=ARXIV_PDF_URL, split_documents=False)

    assert isinstance(docs, list)
    assert len(docs) > 0
    assert docs[0].page_content, "Content from URL should be non-empty"
