"""Toolkit integration of the layout structure builder (FEAT-845 M7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.pageindex.segments import segment_pages, validate_ownership
from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.utils import structure_to_list

PAGES = [(1, "# Ch 1\n\nIntro.\n\n## 1.1 Scope\n\nScope."), (2, "More.")]


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    approx = lambda text, model="gpt-4o": max(1, len(text or ""))  # noqa: E731
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", approx)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )


@pytest.fixture
def toolkit(tmp_path: Path) -> PageIndexToolkit:
    return PageIndexToolkit(storage_dir=tmp_path)


def _structure() -> list[dict[str, Any]]:
    """Return the anchored layout structure corresponding to ``PAGES``."""
    return [
        {
            "title": "Ch 1",
            "node_id": "0000",
            "start_index": 1,
            "end_index": 2,
            "structure_source": "layout",
            "anchor": {"page": 1, "ordinal": 0},
            "nodes": [
                {
                    "title": "1.1 Scope",
                    "node_id": "0001",
                    "start_index": 1,
                    "end_index": 2,
                    "structure_source": "layout",
                    "anchor": {"page": 1, "ordinal": 2},
                }
            ],
        }
    ]


def _fake(*, with_segments: bool, with_pages: bool = True, calls: list | None = None):
    async def fake_build(doc, adapter, options=None, **kwargs):
        if calls is not None:
            calls.append(options)
        result = {
            "doc_name": "doc.pdf",
            "structure": _structure(),
            "_node_markdown": {},
            "structure_source": "layout",
            "structure_report": {"source": "layout", "confidence": 0.9},
        }
        if with_pages:
            result["_pages"] = PAGES
        if with_segments:
            result["_segments"] = segment_pages(PAGES)
        return result

    return fake_build


@pytest.mark.asyncio
async def test_import_pdf_result_and_segments_reuse(toolkit, tmp_path, monkeypatch):
    """Builder segments are reused, result metadata is returned, and _pages fakes retain their fallback."""
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    calls: list = []
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", _fake(with_segments=True, calls=calls))

    def fail_segment_pages(pages):
        raise AssertionError("toolkit must reuse builder-provided segments")

    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.segment_pages", fail_segment_pages)
    await toolkit.create_tree("with-segments")
    result = await toolkit.import_pdf("with-segments", str(pdf), structure_mode="layout")

    assert result["structure_source"] == "layout"
    assert result["structure_confidence"] == 0.9
    assert result["structure_report"] == {"source": "layout", "confidence": 0.9}
    assert calls[0]["structure_mode"] == "layout"
    revision = SegmentStore(tmp_path).load_revision("with-segments", result["doc_id"], result["revision"])
    assert revision is not None
    nodes = structure_to_list(toolkit._store.load("with-segments")["structure"])
    assert validate_ownership(nodes, revision) == []
    assert all("anchor" not in node for node in nodes)

    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.segment_pages", segment_pages)
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", _fake(with_segments=False))
    await toolkit.create_tree("pages-only")
    fallback = await toolkit.import_pdf("pages-only", str(pdf))
    assert fallback["structure_source"] == "layout"
    assert fallback["doc_id"] is not None


@pytest.mark.asyncio
async def test_list_documents_structure_source(toolkit, tmp_path, monkeypatch):
    """PDF rows report their source while markdown rows retain ``None``."""
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", _fake(with_segments=True))
    await toolkit.create_tree("docs")
    markdown = await toolkit.insert_markdown(
        "docs",
        "# Notes\n\n" + "Plain text that remains in the markdown section. " * 4,
        doc_name="notes.md",
    )
    imported = await toolkit.import_pdf("docs", str(pdf))

    rows = {row["doc_id"]: row for row in await toolkit.list_documents("docs")}
    assert rows[imported["doc_id"]]["structure_source"] == "layout"
    assert rows[markdown["doc_id"]]["structure_source"] is None


@pytest.mark.asyncio
async def test_anchor_stripped_without_revision(toolkit, tmp_path, monkeypatch):
    """No pages produces no revision and persists no transient anchors."""
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.build_page_index", _fake(with_segments=False, with_pages=False)
    )
    await toolkit.create_tree("no-revision")
    result = await toolkit.import_pdf("no-revision", str(pdf))

    assert result["doc_id"] is None
    nodes = structure_to_list(toolkit._store.load("no-revision")["structure"])
    assert all("anchor" not in node for node in nodes)
