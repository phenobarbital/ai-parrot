"""FEAT-845 M5 — build_page_index layout-first pipeline, fallbacks, and errors."""
from __future__ import annotations

from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from parrot.knowledge.pageindex import builder  # noqa: E402
from parrot.knowledge.pageindex.layout import NoTextLayerError, PDFStructureError, UnreadablePDFError  # noqa: E402
from parrot.knowledge.pageindex.utils import structure_to_list  # noqa: E402

BODY = "Body text that fills the page with ordinary sentences about the manual and its many topics."
KEYS = {"doc_name", "structure", "structure_source", "structure_report", "_node_markdown", "_pages", "_segments"}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda text, model="gpt-4o": max(1, len(text)))


def _pdf(path: Path, pages: list[list[tuple[float, str, float, str]]], toc=None) -> Path:
    """Create a PDF from ``(y, text, size, font)`` lines."""
    doc = pymupdf.open()
    try:
        for lines in pages:
            page = doc.new_page()
            for y, text, size, font in lines:
                page.insert_text((72, y), text, fontsize=size, fontname=font)
        if toc:
            doc.set_toc(toc)
        doc.save(str(path))
    finally:
        doc.close()
    return path


@pytest.fixture
def headed_pdf(tmp_path) -> Path:
    """Four pages with layout headings, running text, and body text."""
    pages = []
    for number in range(1, 5):
        lines = [(30, "ACME Manual", 9, "helv")]
        if number in (1, 3):
            lines.append((100, f"Chapter {number}", 16, "hebo"))
        lines.append((140, f"Section {number}.1", 12, "hebo"))
        lines.extend((180 + 18 * index, BODY, 10, "helv") for index in range(20))
        lines.append((810, f"Page {number}", 9, "helv"))
        pages.append(lines)
    return _pdf(tmp_path / "headed.pdf", pages)


@pytest.fixture
def headingless_pdf(tmp_path) -> Path:
    """Uniform text with no deterministic heading candidate."""
    pages = [[(80 + 18 * index, BODY, 10, "helv") for index in range(30)] for _ in range(3)]
    return _pdf(tmp_path / "plain.pdf", pages)


class FakeAdapter:
    """Adapter probe for summary calls in layout mode."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ask(self, prompt, structured_output=None, temperature=0.0, system_prompt=None):
        self.calls.append("ask")
        return "summary"


async def test_no_adapter_layout(headed_pdf):
    """No adapter chooses layout and returns the complete hand-off contract."""
    result = await builder.build_page_index(str(headed_pdf), None)
    assert set(result) == KEYS
    assert result["structure_source"] == "layout"
    assert result["structure_report"]["confidence"] >= 0.6
    assert all("summary" not in node for node in structure_to_list(result["structure"]))
    assert all(node["structure_source"] == "layout" for node in structure_to_list(result["structure"]))


async def test_auto_falls_back_to_llm(headingless_pdf, monkeypatch):
    """Insufficient deterministic evidence invokes LLM structure generation."""
    async def fake_tree_parser(page_list, opt, adapter, light_adapter=None):
        return [{"title": "Doc", "start_index": 1, "end_index": 3}]

    monkeypatch.setattr(builder, "tree_parser", fake_tree_parser)
    result = await builder.build_page_index(str(headingless_pdf), FakeAdapter(), {"if_add_node_summary": "no"})
    assert result["structure_source"] == "llm"
    assert result["structure_report"]["llm_used"] is True
    assert len(result["structure_report"]["candidates"]) == 2


async def test_llm_failure_falls_back_to_pages(headingless_pdf, monkeypatch):
    """A failed LLM pass produces page structure while retaining segments."""
    async def fail_tree_parser(page_list, opt, adapter, light_adapter=None):
        raise RuntimeError("model down")

    monkeypatch.setattr(builder, "tree_parser", fail_tree_parser)
    result = await builder.build_page_index(str(headingless_pdf), FakeAdapter(), {"if_add_node_summary": "no"})
    assert result["structure_source"] == "pages"
    assert "model down" in result["structure_report"]["llm_error"]
    assert [node["title"] for node in result["structure"][0]["nodes"]] == ["Page 1", "Page 2", "Page 3"]
    assert result["_segments"]


async def test_modes_and_errors(headed_pdf, tmp_path):
    """Invalid modes and unusable PDFs expose their prescribed public errors."""
    with pytest.raises(ValueError, match="Unknown structure_mode"):
        await builder.build_page_index(str(headed_pdf), None, {"structure_mode": "bogus"})
    with pytest.raises(ValueError, match="needs an LLM adapter"):
        await builder.build_page_index(str(headed_pdf), None, {"structure_mode": "llm"})
    image_only = _pdf(tmp_path / "image-only.pdf", [[]])
    with pytest.raises(NoTextLayerError):
        await builder.build_page_index(str(image_only), None)
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(UnreadablePDFError):
        await builder.build_page_index(str(bad), None)


@pytest.mark.parametrize("stage", ["analysis", "extraction", "segmentation", "empty"])
async def test_extraction_failure_is_explicit(headed_pdf, monkeypatch, stage):
    """Each layout stage failure is explicit and retains the original cause."""
    if stage == "analysis":
        monkeypatch.setattr(builder, "analyze_layout", lambda path: (_ for _ in ()).throw(ValueError("boom")))
    elif stage == "extraction":
        monkeypatch.setattr(builder, "extract_markdown_per_page", lambda path, **kwargs: (_ for _ in ()).throw(ValueError("boom")))
    elif stage == "segmentation":
        monkeypatch.setattr(builder, "segment_pages", lambda pages: (_ for _ in ()).throw(ValueError("boom")))
    else:
        monkeypatch.setattr(builder, "extract_markdown_per_page", lambda path, **kwargs: [(number, "   ") for number in range(1, 5)])
    message = stage if stage != "empty" else "produced no text"
    with pytest.raises(PDFStructureError, match=message) as exc_info:
        await builder._layout_pages(str(headed_pdf))
    if stage == "empty":
        assert exc_info.value.__cause__ is None
    else:
        assert isinstance(exc_info.value.__cause__, ValueError)


async def test_layout_mode_summary_options(headed_pdf, monkeypatch):
    """Layout mode skips structure LLM calls but honors summary options."""
    async def unexpected_tree_parser(*args, **kwargs):
        raise AssertionError("layout mode called tree_parser")

    monkeypatch.setattr(builder, "tree_parser", unexpected_tree_parser)
    with_summaries = FakeAdapter()
    result = await builder.build_page_index(str(headed_pdf), with_summaries, {"structure_mode": "layout", "if_add_node_summary": "yes"})
    assert "ask" in with_summaries.calls
    assert all("summary" in node for node in structure_to_list(result["structure"]))
    no_calls = FakeAdapter()
    await builder.build_page_index(str(headed_pdf), no_calls, {"structure_mode": "layout", "if_add_node_summary": "no", "if_add_doc_description": "no"})
    assert no_calls.calls == []
