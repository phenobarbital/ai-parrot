"""Smoke coverage for FEAT-601 manuals test support."""

from __future__ import annotations

from pathlib import Path

import pytest


async def test_create_edges_never_updates(fake_graph_store):
    """The graph double preserves existing edge properties."""
    await fake_graph_store.create_edges(None, "has_step", [{"_from": "p/1", "_to": "s/1", "order": 1}])
    await fake_graph_store.create_edges(None, "has_step", [{"_from": "p/1", "_to": "s/1", "order": 9}])
    assert fake_graph_store.edges["has_step"][0]["order"] == 1


async def test_query_documents_filters(fake_graph_store):
    """Document filtering excludes soft-deleted vertices."""
    await fake_graph_store.upsert_document(None, "procedures", {"_key": "one", "model": "x", "rank": 1})
    await fake_graph_store.upsert_document(None, "procedures", {"_key": "two", "model": "x", "rank": 2})
    await fake_graph_store.soft_delete_nodes(None, "procedures", ["two"])
    rows = await fake_graph_store.query_documents(None, "procedures", {"model": "x"})
    assert [row["_key"] for row in rows] == ["one"]


async def test_scripted_traversal(fake_graph_store):
    """Traversal scripts receive query bindings and are recorded."""
    fake_graph_store.script_traversal("RETURN procedure", lambda bindings: [{"id": bindings["procedure_id"]}])
    rows = await fake_graph_store.execute_traversal(
        None, "FOR procedure RETURN procedure", {"procedure_id": "procedure-1"}
    )
    assert rows == [{"id": "procedure-1"}]
    assert fake_graph_store.traversals[0][1] == {"procedure_id": "procedure-1"}


async def test_fake_adapter_replays_by_type_and_key(fake_adapter):
    """Keyed adapter scripts override type defaults."""
    class Draft:
        pass

    fallback = Draft()
    selected = Draft()
    fake_adapter.script(Draft, fallback)
    fake_adapter.script(Draft, selected, key="0002")
    assert await fake_adapter.ask_structured("Section node: 0002\ntext", Draft) is selected
    assert await fake_adapter.ask_structured("Section node: 0003\ntext", Draft) is fallback


async def test_fake_file_manager_roundtrip(fake_file_manager, tmp_path: Path):
    """Uploaded bytes can be downloaded under the same key."""
    source = tmp_path / "source.bin"
    destination = tmp_path / "downloads" / "copy.bin"
    source.write_bytes(b"manual image")
    metadata = await fake_file_manager.upload_file(source, "figures/one.png")
    result = await fake_file_manager.download_file("figures/one.png", destination)
    assert metadata.path == "figures/one.png"
    assert result == destination
    assert destination.read_bytes() == b"manual image"


def test_manual_pdf_has_images_and_captions(manual_pdf: Path):
    """The manual contains six pages, two figures, and captions below them."""
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open(manual_pdf)
    try:
        assert len(document) == 6
        image_pages = [page for page in document if page.get_images()]
        assert len(image_pages) == 2
        for page, caption in zip(image_pages, ("Fig. 1", "Fig. 2"), strict=True):
            image_rect = page.get_image_rects(page.get_images()[0][0])[0]
            caption_rect = page.search_for(caption)[0]
            assert caption_rect.y0 > image_rect.y1
    finally:
        document.close()


def test_image_only_pdf_has_no_text(image_only_pdf: Path):
    """A scanned-style PDF contains no extractable text."""
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open(image_only_pdf)
    try:
        assert document[0].get_text().strip() == ""
    finally:
        document.close()
