"""Layout analysis of synthetic PDFs (FEAT-845 M1)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pymupdf = pytest.importorskip("pymupdf")
pymupdf4llm = pytest.importorskip("pymupdf4llm")

from parrot.knowledge.pageindex.layout import (  # noqa: E402
    Bookmark,
    BoldLine,
    LayoutHeaders,
    LayoutProfile,
    RunningLine,
    UnreadablePDFError,
    _read_bookmarks,
    analyze_layout,
)

FILLER = "body text line with plenty of ordinary words for the statistics"
Item = tuple[float, float, str, float, str]


def _write_pdf(path: Path, pages: list[list[Item]], toc: list[list] | None = None) -> Path:
    """Write one A4 page per item list and optionally set its table of contents."""
    doc = pymupdf.open()
    try:
        for items in pages:
            page = doc.new_page()
            for x, y, text, size, font in items:
                page.insert_text((x, y), text, fontsize=size, fontname=font)
        if toc:
            doc.set_toc(toc)
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _body(y0: float, n: int) -> list[Item]:
    """Build regular body-text PDF items."""
    return [(72, y0 + index * 14, FILLER, 10, "helv") for index in range(n)]


@pytest.fixture
def headed_pdf(tmp_path: Path) -> Path:
    """Create four pages with body, size headings, and running text."""
    pages = []
    for number in range(1, 5):
        pages.append(
            [
                (72, 40, "ACME Manual", 9, "helv"),
                (280, 815, f"Page {number}", 9, "helv"),
                (72, 100, f"{number} Chapter {number}", 16, "helv"),
                (72, 130, f"{number}.1 Section {number}", 12, "helv"),
                *_body(160, 30),
            ]
        )
    return _write_pdf(tmp_path / "headed.pdf", pages)


def test_body_size_and_heading_sizes(headed_pdf: Path) -> None:
    """The dominant body size and sparse heading sizes are identified."""
    profile = analyze_layout(str(headed_pdf))
    assert profile.page_count == 4
    assert profile.body_size == 10
    assert profile.heading_sizes == [16, 12]


def test_running_lines_excluded(tmp_path: Path) -> None:
    """Running headers and footers are excluded from heading and bold signals."""
    pages = []
    for number in range(1, 5):
        pages.append(
            [
                (72, 40, "ACME Manual", 20, "hebo"),
                (280, 815, f"Page {number}", 9, "helv"),
                *_body(160, 30),
            ]
        )
    profile = analyze_layout(str(_write_pdf(tmp_path / "running.pdf", pages)))
    assert {(line.band, line.key) for line in profile.running} == {("top", "acme manual"), ("bottom", "page #")}
    assert 20 not in profile.heading_sizes
    assert not any(line.text == "acme manual" for page in profile.bold_lines.values() for line in page)

    short_profile = analyze_layout(str(_write_pdf(tmp_path / "short.pdf", pages[:2])))
    assert short_profile.running == []


def test_bold_standalone_lines(tmp_path: Path) -> None:
    """Standalone bold body lines are retained while a bold run-in word is not."""
    doc = pymupdf.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 100), "Important Notes", fontsize=10, fontname="hebo")
        page.insert_text((72, 200), "Important ", fontsize=10, fontname="hebo")
        offset = pymupdf.get_text_length("Important ", fontname="hebo", fontsize=10)
        page.insert_text((72 + offset, 200), "begins this ordinary body line", fontsize=10, fontname="helv")
        page.insert_text((72, 400), "Important Notes", fontsize=10, fontname="hebo")
        for x, y, text, size, font in _body(450, 20):
            page.insert_text((x, y), text, fontsize=size, fontname=font)
        path = tmp_path / "bold.pdf"
        doc.save(str(path))
    finally:
        doc.close()

    profile = analyze_layout(str(path))
    bold_lines = profile.bold_lines[1]
    assert [line.text for line in bold_lines] == ["important notes", "important notes"]
    assert bold_lines[0].bbox != bold_lines[1].bbox


def test_bookmarks_usable_and_levels_normalized() -> None:
    """Invalid bookmark entries are skipped and level jumps are normalized."""
    bookmarks, rejection = _read_bookmarks([[1, "A", 1], [3, "B", 2], [1, "C", 9], [1, "  ", 2], [2, "D", 3]], 4)
    assert [bookmark.title for bookmark in bookmarks] == ["A", "B", "D"]
    assert [bookmark.level for bookmark in bookmarks] == [1, 2, 2]
    assert [bookmark.page for bookmark in bookmarks] == [1, 2, 3]
    assert rejection is None


def test_bookmarks_rejected_non_monotonic(tmp_path: Path) -> None:
    """A decreasing bookmark page order is rejected but preserved diagnostically."""
    pdf = _write_pdf(tmp_path / "nonmonotonic.pdf", [_body(100, 3) for _ in range(3)], [[1, "A", 3], [1, "B", 1]])
    profile = analyze_layout(str(pdf))
    assert [bookmark.title for bookmark in profile.bookmarks] == ["A", "B"]
    assert profile.bookmark_rejection is not None
    assert "non-monotonic" in profile.bookmark_rejection


def test_bookmarks_rejected_per_page_enumeration(tmp_path: Path) -> None:
    """A page-number TOC is identified as a per-page enumeration."""
    pdf = _write_pdf(
        tmp_path / "enumeration.pdf",
        [_body(100, 3) for _ in range(4)],
        [[1, f"Page {number}", number] for number in range(1, 5)],
    )
    profile = analyze_layout(str(pdf))
    assert profile.bookmark_rejection is not None
    assert "per-page enumeration" in profile.bookmark_rejection


def test_unreadable_pdf(tmp_path: Path) -> None:
    """Unreadable PDF bytes raise the dedicated ValueError subclass."""
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(UnreadablePDFError) as error:
        analyze_layout(str(path))
    assert isinstance(error.value, ValueError)


def _span(text: str, size: float, bbox: tuple[float, float, float, float], bold: bool = False) -> dict:
    """Build a span dict shaped like pymupdf4llm's output."""
    return {
        "text": text,
        "size": size,
        "flags": 16 if bold else 0,
        "char_flags": 0,
        "font": "Helvetica-Bold" if bold else "Helvetica",
        "bbox": pymupdf.Rect(bbox),
    }


def _page(number: int) -> SimpleNamespace:
    """Build a minimal PyMuPDF page-compatible object."""
    return SimpleNamespace(number=number, rect=SimpleNamespace(height=842.0))


def test_header_detector_rules() -> None:
    """Apply header detector rules one through six to hand-built spans."""
    profile = LayoutProfile(
        page_count=2,
        body_size=10,
        heading_sizes=[16, 12],
        running=[RunningLine(key="acme manual", band="top", pages=4)],
        bold_lines={1: [BoldLine(text="important notes", bbox=(72.0, 89.3, 148.7, 103.1))]},
        bookmarks=[Bookmark(level=1, title="2 Getting Started", page=2)],
    )
    headers = LayoutHeaders(profile)

    assert headers.get_header_id(_span("  ", 16, (72, 100, 160, 116)), page=_page(0)) == ""
    assert headers.get_header_id(_span("ACME Manual", 16, (72, 30, 160, 46), bold=True), page=_page(0)) == ""
    assert headers.get_header_id(_span("Chapter", 16, (72, 100, 160, 116)), page=_page(0)) == "# "
    assert headers.get_header_id(_span("Section", 12, (72, 120, 160, 136)), page=_page(0)) == "## "
    assert headers.get_header_id(_span("Rounded", 15.6, (72, 140, 160, 156)), page=_page(0)) == "# "
    assert headers.get_header_id(_span("Chapter", 16, (72, 100, 160, 116))) == "# "
    assert (
        headers.get_header_id(_span("Important Notes", 10, (72.0, 92.7, 148.7, 102.2), bold=True), page=_page(0))
        == "### "
    )
    assert headers.get_header_id(_span("Important ", 10, (72.0, 132.7, 120.9, 142.2), bold=True), page=_page(0)) == ""
    assert headers.get_header_id(_span("Important Notes", 10, (72.0, 92.7, 148.7, 102.2), bold=True)) == ""
    assert headers.get_header_id(_span("Getting Started", 10, (72, 200, 200, 212), bold=True), page=_page(1)) == "### "
    assert headers.get_header_id(_span("Getting Started is easy", 10, (72, 220, 250, 232)), page=_page(1)) == ""
    rejected_headers = LayoutHeaders(profile.model_copy(update={"bookmark_rejection": "non-monotonic: page decreases"}))
    assert (
        rejected_headers.get_header_id(_span("Getting Started", 10, (72, 200, 200, 212), bold=True), page=_page(1))
        == ""
    )
    assert headers.get_header_id(_span("ordinary body", 10, (72, 250, 160, 266)), page=_page(0)) == ""


def test_bold_heading_occurrence_collision(tmp_path: Path) -> None:
    """Promote only the standalone body-bold heading, never the bold run-in occurrence."""
    path = tmp_path / "bold-collision.pdf"
    doc = pymupdf.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 100), "Important Notes", fontsize=10, fontname="hebo")
        page.insert_text((72, 140), "Important ", fontsize=10, fontname="hebo")
        offset = pymupdf.get_text_length("Important ", fontname="hebo", fontsize=10)
        page.insert_text((72 + offset, 140), "remarks follow in regular text.", fontsize=10, fontname="helv")
        for x, y, text, size, font in _body(200, 30):
            page.insert_text((x, y), text, fontsize=size, fontname=font)
        doc.save(str(path))
    finally:
        doc.close()

    profile = analyze_layout(str(path))
    assert len(profile.bold_lines[1]) == 1
    chunks = pymupdf4llm.to_markdown(str(path), page_chunks=True, hdr_info=LayoutHeaders(profile))
    heading_lines = [line for line in chunks[0]["text"].splitlines() if line.startswith("#")]
    assert len(heading_lines) == 1
    assert "Important Notes" in heading_lines[0]
    assert not any("remarks" in line for line in heading_lines)


def test_running_lines_never_headings(tmp_path: Path) -> None:
    """Keep repeated headers and footers in text without promoting them to headings."""
    pages = []
    for number in range(1, 5):
        pages.append(
            [
                (72, 40, "ACME Manual", 16, "hebo"),
                (280, 815, f"Page {number}", 10, "helv"),
                (72, 100, f"{number} Chapter {number}", 16, "helv"),
                (72, 130, f"{number}.1 Section {number}", 12, "helv"),
                *_body(160, 30),
            ]
        )
    path = _write_pdf(tmp_path / "running-headings.pdf", pages)
    chunks = pymupdf4llm.to_markdown(str(path), page_chunks=True, hdr_info=LayoutHeaders(analyze_layout(str(path))))
    text_by_page = [chunk["text"] for chunk in chunks]
    heading_lines = [line for text in text_by_page for line in text.splitlines() if line.startswith("#")]

    assert not any("ACME Manual" in line or "Page " in line for line in heading_lines)
    assert all("ACME Manual" in text for text in text_by_page)
    assert any(line.startswith("# ") and "Chapter" in line for line in heading_lines)
