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
    _keep_page_order,
    _read_bookmarks,
    _visual_rows,
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
    bookmarks, rejection, dropped = _read_bookmarks(
        [[1, "A", 1], [3, "B", 2], [1, "C", 9], [1, "  ", 2], [2, "D", 3]], 4
    )
    assert [bookmark.title for bookmark in bookmarks] == ["A", "B", "D"]
    assert [bookmark.level for bookmark in bookmarks] == [1, 2, 2]
    assert [bookmark.page for bookmark in bookmarks] == [1, 2, 3]
    assert rejection is None
    assert dropped == 0


def test_keep_page_order_longest_subsequence() -> None:
    """The kept indices form one longest non-decreasing page subsequence."""
    assert _keep_page_order([1, 5, 2, 3, 4]) == [0, 2, 3, 4]
    assert _keep_page_order([]) == []
    assert _keep_page_order([1, 1, 2, 3]) == [0, 1, 2, 3]
    assert _keep_page_order([3, 1, 2]) == [1, 2]


def test_bookmarks_out_of_order_entry_dropped() -> None:
    """A single mis-filed entry in a long outline is dropped instead of rejecting the outline."""
    toc = [[1 if number % 5 == 1 else 2, f"Section {number}", number] for number in range(1, 41)]
    toc.insert(30, [2, "Stray", 3])
    bookmarks, rejection, dropped = _read_bookmarks(toc, 200)
    assert rejection is None
    assert dropped == 1
    assert len(bookmarks) == 40
    assert "Stray" not in [bookmark.title for bookmark in bookmarks]
    assert [bookmark.page for bookmark in bookmarks] == sorted(bookmark.page for bookmark in bookmarks)


def test_bookmarks_too_many_out_of_order_rejected() -> None:
    """More out-of-order entries than the tolerated share keep today's non-monotonic rejection."""
    toc = [[1, f"Section {number}", number] for number in range(1, 21)]
    toc.insert(10, [1, "Stray A", 2])
    toc.insert(15, [1, "Stray B", 3])
    bookmarks, rejection, dropped = _read_bookmarks(toc, 200)
    assert rejection is not None
    assert rejection.startswith("non-monotonic: page decreases at entry")
    assert dropped == 0
    assert len(bookmarks) == 22


def test_bookmarks_dropped_recorded_in_profile(tmp_path: Path) -> None:
    """The profile records how many out-of-order entries were dropped."""
    toc = [[1 if number % 5 == 1 else 2, f"Section {number}", number] for number in range(1, 21)]
    toc.insert(10, [2, "Stray", 2])
    pdf = _write_pdf(tmp_path / "stray.pdf", [_body(100, 3) for _ in range(30)], toc)
    profile = analyze_layout(str(pdf))
    assert profile.bookmark_rejection is None
    assert profile.bookmarks_dropped == 1
    assert len(profile.bookmarks) == 20


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


def _all_bold_texts(profile: LayoutProfile) -> list[str]:
    """Return every recorded bold-row text in page order."""
    return [line.text for page in sorted(profile.bold_lines) for line in profile.bold_lines[page]]


def test_visual_rows_groups_same_baseline_lines() -> None:
    """Lines on one baseline share a row; a line below starts the next row."""
    lines = [
        {"bbox": (72, 100, 100, 112), "spans": [], "text": "AC-2"},
        {"bbox": (108, 100, 250, 112), "spans": [], "text": "ACCOUNT MANAGEMENT"},
        {"bbox": (72, 120, 250, 132), "spans": [], "text": "Control:"},
    ]
    rows = _visual_rows(lines)
    assert [[line["text"] for line in row] for row in rows] == [["AC-2", "ACCOUNT MANAGEMENT"], ["Control:"]]
    assert _visual_rows([]) == []


def test_secondary_text_size_bold_rows(tmp_path: Path) -> None:
    """A standalone bold line at a larger body-text size is a bold row with its own size."""
    prose_12 = [(72, 630 + index * 16, FILLER, 12, "helv") for index in range(8)]
    pages = [[(72, 100, "Revisions In This Version", 12, "hebo"), *_body(200, 30), *prose_12]]
    path = _write_pdf(tmp_path / "secondary.pdf", pages)

    profile = analyze_layout(str(path))

    assert profile.body_size == 10
    assert 12 not in profile.heading_sizes
    assert profile.bold_sizes == [12, 10]
    rows = profile.bold_lines[1]
    assert [(line.text, line.size) for line in rows] == [("revisions in this version", 12)]
    chunks = pymupdf4llm.to_markdown(str(path), page_chunks=True, hdr_info=LayoutHeaders(profile))
    heading_lines = [line for line in chunks[0]["text"].splitlines() if line.startswith("#")]
    assert len(heading_lines) == 1
    assert "Revisions In This Version" in heading_lines[0]


def test_split_row_heading(tmp_path: Path) -> None:
    """A code cell and a title cell printed on one baseline form one bold row and one heading line."""
    code_width = pymupdf.get_text_length("AC-2", fontname="hebo", fontsize=10)
    pages = [[(72, 100, "AC-2", 10, "hebo"), (72 + code_width + 14, 100, "ACCOUNT MANAGEMENT", 10, "hebo"), *_body(150, 30)]]
    path = _write_pdf(tmp_path / "split.pdf", pages)

    profile = analyze_layout(str(path))

    assert _all_bold_texts(profile) == ["ac-2 account management"]
    chunks = pymupdf4llm.to_markdown(str(path), page_chunks=True, hdr_info=LayoutHeaders(profile))
    heading_lines = [line for line in chunks[0]["text"].splitlines() if line.startswith("#")]
    assert len(heading_lines) == 1
    assert "AC-2" in heading_lines[0] and "ACCOUNT MANAGEMENT" in heading_lines[0]


def test_bold_row_guards(tmp_path: Path) -> None:
    """List items, lowercase-start rows and rows repeated on three pages are not bold rows."""
    first_page = [
        (72, 100, "(a) Have expired;", 10, "hebo"),
        (72, 140, "Monitor changes to roles; and", 10, "hebo"),
        (72, 180, "adequate security", 10, "hebo"),
        (72, 220, "Important Notes", 10, "hebo"),
        (72, 260, "Release information only if:", 10, "hebo"),
    ]
    pages = [
        [*(first_page if number == 0 else []), (72, 320, "DATE TYPE REVISION", 10, "hebo"), *_body(360, 20)]
        for number in range(3)
    ]
    profile = analyze_layout(str(_write_pdf(tmp_path / "guards.pdf", pages)))

    assert _all_bold_texts(profile) == ["important notes"]


def test_header_prefix_levels_with_secondary_size() -> None:
    """Each bold size gets its own level below every size-ranked heading, larger size first."""
    profile = LayoutProfile(
        page_count=1,
        body_size=10,
        heading_sizes=[16, 14],
        bold_sizes=[12, 10],
        bold_lines={
            1: [
                BoldLine(text="revisions", bbox=(72.0, 90.0, 200.0, 104.0), size=12),
                BoldLine(text="important notes", bbox=(72.0, 190.0, 200.0, 204.0), size=10),
            ]
        },
    )
    headers = LayoutHeaders(profile)

    assert headers.get_header_id(_span("Revisions", 12, (72.0, 92.0, 150.0, 103.0), bold=True), page=_page(0)) == "### "
    assert headers.get_header_id(_span("Important", 10, (72.0, 192.0, 150.0, 203.0), bold=True), page=_page(0)) == "#### "
    assert headers.get_header_id(_span("Revisions", 12, (72.0, 300.0, 150.0, 311.0), bold=True), page=_page(0)) == ""
    assert headers.get_header_id(_span("Chapter", 16, (72.0, 400.0, 150.0, 416.0)), page=_page(0)) == "# "
