"""FEAT-845 M5 — builder return contract and layout-stage propagation."""
from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from parrot.knowledge.pageindex import builder  # noqa: E402
from parrot.knowledge.pageindex.layout import LayoutHeaders, PDFStructureError  # noqa: E402

KEYS = {"doc_name", "structure", "structure_source", "structure_report", "_node_markdown", "_pages", "_segments"}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda text, model="gpt-4o": max(1, len(text)))


@pytest.fixture
def small_pdf(tmp_path) -> Path:
    doc = pymupdf.open()
    try:
        for number in (1, 2):
            page = doc.new_page()
            page.insert_text((72, 100), f"Heading {number}", fontsize=16, fontname="hebo")
            for index in range(15):
                page.insert_text((72, 140 + 18 * index), "Plain body sentence for the page.", fontsize=10, fontname="helv")
        doc.save(str(tmp_path / "small.pdf"))
    finally:
        doc.close()
    return tmp_path / "small.pdf"


async def test_single_return_dict_keys(small_pdf):
    """One return dict contains the PageIndex layout hand-off fields."""
    result = await builder.build_page_index(str(small_pdf))
    assert set(result) == KEYS
    assert result["_pages"]
    assert result["_segments"]


async def test_layout_pages_propagates_errors(small_pdf, monkeypatch):
    """Layout extraction receives LayoutHeaders and stage failures retain their cause."""
    seen: dict = {}

    def extract(path, **kwargs):
        seen.update(kwargs)
        return [(1, "# A\n\nx"), (2, "y")]

    monkeypatch.setattr(builder, "extract_markdown_per_page", extract)
    _, _, segments = await builder._layout_pages(str(small_pdf))
    assert isinstance(seen["hdr_info"], LayoutHeaders)
    assert segments

    def fail_extract(path, **kwargs):
        raise FileNotFoundError("missing converter")

    monkeypatch.setattr(builder, "extract_markdown_per_page", fail_extract)
    with pytest.raises(PDFStructureError, match="extraction") as exc_info:
        await builder._layout_pages(str(small_pdf))
    assert isinstance(exc_info.value.__cause__, FileNotFoundError)


async def test_layout_work_runs_in_threads(small_pdf, monkeypatch):
    """All CPU-bound layout calls use asyncio.to_thread."""
    calls: list[str] = []
    original_to_thread = asyncio.to_thread

    async def recording_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(builder.asyncio, "to_thread", recording_to_thread)
    await builder.build_page_index(str(small_pdf))
    assert {"get_page_tokens", "analyze_layout", "extract_markdown_per_page", "segment_pages"} <= set(calls)


async def test_bytesio_skips_layout(small_pdf, monkeypatch):
    """Streams use page fallback without path-only layout stages."""
    monkeypatch.setattr(builder, "analyze_layout", lambda path: (_ for _ in ()).throw(AssertionError("layout called")))
    result = await builder.build_page_index(BytesIO(small_pdf.read_bytes()))
    assert result["structure_source"] == "pages"
    assert result["_pages"] == []
    assert result["_segments"] == []
