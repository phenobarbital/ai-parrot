"""FEAT-845 end to end: layout structure through import_pdf, fallbacks, and failure without publication."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION
from parrot.knowledge.pageindex.layout import PDFStructureError
from parrot.knowledge.pageindex.schemas import (
    PageIndexDetection,
    PhysicalIndexFix,
    TitleAppearanceCheck,
    TitleStartCheck,
    TocCompletionCheck,
    TocDetectionResult,
)
from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.segments import normalize_title, validate_ownership
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.utils import structure_to_list

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "arxiv_2408_09869.pdf"
REFERENCE = FIXTURES / "docling_structure.json"
SENTENCE = "Uniform body text sentence number {n} about deterministic structure."


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    approx = lambda text, model="gpt-4o": max(1, len(text or ""))  # noqa: E731
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", approx)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )


def _headed_pdf(path: Path) -> Path:
    """Build a four-page PDF with deterministic headings and running lines."""
    document = pymupdf.open()
    try:
        for number in range(1, 5):
            page = document.new_page()
            page.insert_text((72, 30), "ACME Manual", fontsize=9, fontname="helv")
            if number in (1, 3):
                page.insert_text((72, 100), f"Chapter {number}", fontsize=16, fontname="hebo")
            page.insert_text((72, 140), f"Section {number}.1", fontsize=12, fontname="hebo")
            for index in range(20):
                page.insert_text((72, 180 + 18 * index), SENTENCE.format(n=index), fontsize=10, fontname="helv")
            page.insert_text((72, 810), f"Page {number}", fontsize=9, fontname="helv")
        document.save(path)
    finally:
        document.close()
    return path


def _headingless_pdf(path: Path) -> Path:
    """Build a three-page PDF with uniform text and no deterministic headings."""
    document = pymupdf.open()
    try:
        for number in range(1, 4):
            page = document.new_page()
            for index in range(30):
                page.insert_text(
                    (72, 80 + 18 * index), SENTENCE.format(n=number * 100 + index), fontsize=10, fontname="helv"
                )
        document.save(path)
    finally:
        document.close()
    return path


class _ScriptedAdapter:
    """Record LLM calls and provide the small, valid no-TOC response sequence."""

    model = "scripted"
    client = None

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def ask_structured(self, prompt, output_type, temperature=0.0, system_prompt=None):
        """Return the requested structured response while recording framing arguments."""
        self.calls.append(("ask_structured", prompt, system_prompt))
        if output_type is TocDetectionResult:
            return TocDetectionResult(thinking="t", toc_detected="no")
        if output_type is PageIndexDetection:
            return PageIndexDetection(thinking="t", page_index_given_in_toc="no")
        if output_type is TocCompletionCheck:
            return TocCompletionCheck(thinking="t", completed="yes")
        if output_type is TitleAppearanceCheck:
            return TitleAppearanceCheck(thinking="t", answer="yes")
        if output_type is TitleStartCheck:
            return TitleStartCheck(thinking="t", start_begin="yes")
        if output_type is PhysicalIndexFix:
            return PhysicalIndexFix(thinking="t", physical_index="<physical_index_1>")
        raise AssertionError(f"Unexpected structured output type: {output_type}")

    async def ask_with_finish_info(self, prompt, temperature=0.0, chat_history=None, system_prompt=None):
        """Return one valid generated TOC entry and a successful finish reason."""
        self.calls.append(("ask_with_finish_info", prompt, system_prompt))
        return (
            '[{"structure": "1", "title": "Part One", "physical_index": "<physical_index_1>"}, '
            '{"structure": "2", "title": "Part Two", "physical_index": "<physical_index_3>"}]',
            "finished",
        )

    async def ask_json(self, prompt, temperature=0.0, system_prompt=None):
        """Return an empty JSON result for optional cleanup prompts."""
        self.calls.append(("ask_json", prompt, system_prompt))
        return []

    async def ask(self, prompt, structured_output=None, temperature=0.0, system_prompt=None):
        """Return an empty text result for disabled summary paths."""
        self.calls.append(("ask", prompt, system_prompt))
        return ""


def _depths(nodes: list[dict[str, Any]], depth: int = 1) -> list[tuple[int, dict[str, Any]]]:
    """Flatten nodes with their one-based nesting depth."""
    out: list[tuple[int, dict[str, Any]]] = []
    for node in nodes:
        out.append((depth, node))
        out.extend(_depths(node.get("nodes") or [], depth + 1))
    return out


async def test_fixture_import_is_hybrid_and_anchored(tmp_path):
    """The fixture imports as hybrid, preserves bookmark placement, and owns every segment exactly once."""
    toolkit = PageIndexToolkit(storage_dir=tmp_path)
    await toolkit.create_tree("fixture")
    imported = await toolkit.import_pdf("fixture", str(FIXTURE))

    assert imported["structure_source"] == "hybrid"
    reference = json.loads(REFERENCE.read_text())
    expected = [
        (depth, normalize_title(node["title"]), node["start_index"])
        for depth, node in _depths(reference["structure"])
    ]
    tree = toolkit._store.load("fixture")
    nodes = structure_to_list(tree["structure"])
    actual = [(depth, normalize_title(node["title"]), node["start_index"]) for depth, node in _depths(tree["structure"])]
    for entry in expected:
        assert entry in actual
    assert [(depth, node["title"]) for depth, node in _depths(tree["structure"]) if node["title"] in {"References", "Appendix"}] == [
        (1, "References"),
        (1, "Appendix"),
    ]
    revision = SegmentStore(tmp_path).load_revision("fixture", imported["doc_id"], imported["revision"])
    assert revision is not None
    bookmark_titles = {title for _, title, _ in expected}
    for node in nodes:
        if normalize_title(node["title"]) not in bookmark_titles:
            continue
        assert node["span"] is not None
        assert revision.segments[node["span"][0]].kind == "heading"
    assert validate_ownership(nodes, revision) == []
    assert all("anchor" not in node for node in nodes)


async def test_fixture_read_pages_after_layout_import(tmp_path):
    """A layout-backed import serves the expected heading as a page-addressed segment."""
    toolkit = PageIndexToolkit(storage_dir=tmp_path)
    await toolkit.create_tree("fixture")
    imported = await toolkit.import_pdf("fixture", str(FIXTURE))
    result = await toolkit.read_pages("fixture", imported["doc_id"], "2")

    segment = next(item for item in result["segments"] if "### **2 Getting Started**" in item["text"])
    assert segment["address"]["page"] == 2


async def test_low_confidence_pdf_uses_framed_llm(tmp_path):
    """The LLM fallback frames all document text when layout confidence is insufficient."""
    adapter = _ScriptedAdapter()
    pdf = _headingless_pdf(tmp_path / "headingless.pdf")
    toolkit = PageIndexToolkit(adapter=adapter, storage_dir=tmp_path)
    await toolkit.create_tree("llm")
    imported = await toolkit.import_pdf("llm", str(pdf), with_summaries=False)

    assert imported["structure_source"] == "llm"
    assert adapter.calls
    for _, prompt, system_prompt in adapter.calls:
        assert system_prompt == DATA_FRAMING_INSTRUCTION
        frames = re.findall(r"<document_text[^>]*>.*?</document_text>", prompt, flags=re.DOTALL)
        assert frames
        unframed = re.sub(r"<document_text[^>]*>.*?</document_text>", "", prompt, flags=re.DOTALL)
        assert SENTENCE.format(n=100) not in unframed


@pytest.mark.parametrize("failure", ["analysis", "extraction", "empty"])
async def test_failed_extraction_does_not_publish(tmp_path, monkeypatch, failure):
    """Failed layout work leaves both existing trees and Bookstore publication untouched."""
    pdf = _headed_pdf(tmp_path / "headed.pdf")
    toolkit = PageIndexToolkit(storage_dir=tmp_path / "toolkit")
    await toolkit.create_tree("t")
    await toolkit.import_pdf("t", str(pdf))
    before_tree = copy.deepcopy(toolkit._store.load("t"))
    before_generation = await toolkit.get_generation("t")

    if failure == "analysis":
        monkeypatch.setattr(
            "parrot.knowledge.pageindex.builder.analyze_layout",
            lambda path: (_ for _ in ()).throw(ValueError("boom")),
        )
        pattern = "analysis"
    elif failure == "extraction":
        monkeypatch.setattr(
            "parrot.knowledge.pageindex.builder.extract_markdown_per_page",
            lambda path, **kwargs: (_ for _ in ()).throw(ValueError("boom")),
        )
        pattern = "extraction"
    else:
        monkeypatch.setattr(
            "parrot.knowledge.pageindex.builder.extract_markdown_per_page",
            lambda path, **kwargs: [(number, "") for number in range(1, 5)],
        )
        pattern = "produced no text"

    with pytest.raises(PDFStructureError, match=pattern):
        await toolkit.import_pdf("t", str(pdf))
    assert toolkit._store.load("t") == before_tree
    assert await toolkit.get_generation("t") == before_generation

    bookstore = Bookstore(
        [
            LibraryLocation("project", tmp_path / "project" / "library"),
            LibraryLocation("global", tmp_path / "global" / "library"),
        ]
    )
    with pytest.raises(BookstoreError, match="Cannot index headed.pdf"):
        await bookstore.add_book(pdf)
    assert bookstore.list_books() == []


async def test_page_fallback_retains_content(tmp_path):
    """No-adapter, low-confidence PDFs retain their extracted text in the page fallback revision."""
    pdf = _headingless_pdf(tmp_path / "headingless.pdf")
    toolkit = PageIndexToolkit(storage_dir=tmp_path)
    await toolkit.create_tree("pages")
    imported = await toolkit.import_pdf("pages", str(pdf))

    assert imported["structure_source"] == "pages"
    assert imported["revision"] is not None
    result = await toolkit.read_pages("pages", imported["doc_id"], "1", max_chars=12000)
    assert SENTENCE.format(n=100) in "".join(segment["text"] for segment in result["segments"])
