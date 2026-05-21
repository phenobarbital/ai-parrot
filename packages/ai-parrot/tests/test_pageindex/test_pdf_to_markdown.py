"""Tests for parrot.pageindex.pdf_to_markdown."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from parrot.pageindex.pdf_to_markdown import (
    build_node_markdown_map,
    extract_markdown_per_page,
)


def _make_pdf(path: Path, n_pages: int = 3) -> Path:
    """Create a tiny multi-page PDF using pymupdf."""
    import pymupdf  # type: ignore[import-not-found]

    doc = pymupdf.open()
    try:
        for i in range(n_pages):
            page = doc.new_page()
            page.insert_text(
                (72, 72),
                f"Page {i + 1} body — token-{i}",
                fontsize=14,
            )
        doc.save(str(path))
    finally:
        doc.close()
    return path


def test_extract_markdown_per_page_indexing(tmp_path: Path):
    pdf = _make_pdf(tmp_path / "tiny.pdf", n_pages=3)
    pages = extract_markdown_per_page(pdf)
    assert len(pages) == 3
    assert [p[0] for p in pages] == [1, 2, 3]
    # Every page is non-blank because we inserted text on each.
    for _, text in pages:
        assert text.strip(), "expected non-empty markdown for each page"
    # Each page's body text appears in its own slot.
    assert "token-0" in pages[0][1]
    assert "token-1" in pages[1][1]
    assert "token-2" in pages[2][1]


def test_extract_markdown_per_page_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        extract_markdown_per_page(tmp_path / "no_such.pdf")


def test_extract_markdown_per_page_count_mismatch_raises(tmp_path: Path):
    pdf = _make_pdf(tmp_path / "tiny.pdf", n_pages=3)
    # Force pymupdf4llm to return fewer chunks than the real page count.
    with patch(
        "parrot.pageindex.pdf_to_markdown.pymupdf4llm.to_markdown",
        return_value=[{"text": "only one"}],
    ):
        with pytest.raises(ValueError):
            extract_markdown_per_page(pdf)


def test_build_node_markdown_map_slices_by_index():
    pages = [(1, "alpha\n"), (2, "beta\n"), (3, "gamma\n"), (4, "delta\n")]
    structure = [
        {
            "node_id": "0000",
            "title": "Root A",
            "start_index": 1,
            "end_index": 2,
            "nodes": [
                {
                    "node_id": "0001",
                    "title": "Child A1",
                    "start_index": 2,
                    "end_index": 2,
                },
            ],
        },
        {
            "node_id": "0002",
            "title": "Root B",
            "start_index": 3,
            "end_index": 4,
        },
    ]
    out = build_node_markdown_map(structure, pages)
    assert out["0000"] == "alpha\nbeta\n"
    assert out["0001"] == "beta\n"
    assert out["0002"] == "gamma\ndelta\n"


def test_build_node_markdown_map_skips_folder_nodes():
    # Folder/synthetic nodes have no page range; result is empty string.
    structure = [
        {"node_id": "0000", "title": "Folder", "nodes": []},
    ]
    out = build_node_markdown_map(structure, [(1, "x")])
    assert out["0000"] == ""
