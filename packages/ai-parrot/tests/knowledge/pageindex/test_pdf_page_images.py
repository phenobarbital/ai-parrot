"""FEAT-601 M6 — additive image extraction in pdf_to_markdown (AC12)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

pymupdf = pytest.importorskip("pymupdf")

from parrot.knowledge.pageindex import pdf_to_markdown as p2m  # noqa: E402


def _two_image_pdf(path: Path) -> Path:
    """Build a 1-page PDF carrying two raster images at known rects."""
    doc = pymupdf.open()
    try:
        page = doc.new_page()
        rect1 = pymupdf.Rect(50, 50, 250, 250)
        pix1 = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), 0)
        pix1.set_rect(pix1.irect, (255, 0, 0))
        page.insert_image(rect1, pixmap=pix1)

        rect2 = pymupdf.Rect(300, 300, 500, 500)
        pix2 = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), 0)
        pix2.set_rect(pix2.irect, (0, 255, 0))
        page.insert_image(rect2, pixmap=pix2)

        doc.save(str(path))
    finally:
        doc.close()
    return path


def test_extract_markdown_per_page_unchanged_without_images_dir(tmp_path: Path) -> None:
    pdf = _two_image_pdf(tmp_path / "a.pdf")
    with mock.patch.object(p2m.pymupdf4llm, "to_markdown", return_value=[{"text": "x"}]) as tm:
        assert p2m.extract_markdown_per_page(pdf) == [(1, "x")]
    tm.assert_called_once_with(str(pdf), page_chunks=True)

    images_dir = tmp_path / "img"
    with mock.patch.object(p2m.pymupdf4llm, "to_markdown", return_value=[{"text": "y"}]) as tm2:
        assert p2m.extract_markdown_per_page(pdf, images_dir=images_dir) == [(1, "y")]
    assert images_dir.is_dir()
    tm2.assert_called_once_with(
        str(pdf),
        page_chunks=True,
        write_images=True,
        image_path=str(images_dir),
        image_format="png",
        dpi=150,
        image_size_limit=0.05,
    )
    _, call_kwargs = tm2.call_args
    assert "pages" not in call_kwargs


def test_extract_page_images_bbox(tmp_path: Path) -> None:
    pdf = _two_image_pdf(tmp_path / "b.pdf")
    images = p2m.extract_page_images(pdf, tmp_path / "img")
    assert len(images) == 2

    expected_bboxes = [(50.0, 50.0, 250.0, 250.0), (300.0, 300.0, 500.0, 500.0)]
    for image, expected_bbox in zip(images, expected_bboxes):
        assert image.page == 1
        for actual, expected in zip(image.bbox, expected_bbox):
            assert actual == pytest.approx(expected, abs=1.0)
        assert len(image.sha256) == 64
        assert all(c in "0123456789abcdef" for c in image.sha256)
        assert image.path.is_file()

    # Order is stable across runs (page, index).
    assert [image.index for image in images] == sorted(image.index for image in images)
