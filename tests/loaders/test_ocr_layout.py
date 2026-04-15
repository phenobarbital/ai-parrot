"""
Unit tests for HeuristicLayoutAnalyzer and render_markdown.

Fixtures and test classes exactly as specified in TASK-704.
"""
import pytest

from parrot_loaders.ocr.layout import HeuristicLayoutAnalyzer, render_markdown
from parrot_loaders.ocr.models import OCRBlock


# ---------------------------------------------------------------------------
# Fixtures (from TASK-704 specification)
# ---------------------------------------------------------------------------


@pytest.fixture
def table_blocks():
    """OCR blocks forming a 3-column, 3-row table."""
    return [
        # Header row (y=100)
        OCRBlock(text="Item", bbox=(50, 95, 150, 115), confidence=0.95),
        OCRBlock(text="Qty", bbox=(200, 95, 280, 115), confidence=0.95),
        OCRBlock(text="Price", bbox=(350, 95, 450, 115), confidence=0.95),
        # Row 1 (y=130)
        OCRBlock(text="Widget", bbox=(50, 125, 150, 145), confidence=0.93),
        OCRBlock(text="10", bbox=(200, 125, 240, 145), confidence=0.97),
        OCRBlock(text="$5.99", bbox=(350, 125, 450, 145), confidence=0.94),
        # Row 2 (y=160)
        OCRBlock(text="Gadget", bbox=(50, 155, 150, 175), confidence=0.92),
        OCRBlock(text="5", bbox=(200, 155, 220, 175), confidence=0.96),
        OCRBlock(text="$12.50", bbox=(350, 155, 450, 175), confidence=0.94),
    ]


@pytest.fixture
def header_blocks():
    """OCR blocks that should be detected as header (large text)."""
    return [
        OCRBlock(
            text="PART ORDER GUIDE",
            bbox=(100, 20, 500, 70),
            confidence=0.98,
            font_size_estimate=50.0,
        ),
        OCRBlock(
            text="This is regular body text.",
            bbox=(100, 100, 500, 120),
            confidence=0.95,
            font_size_estimate=20.0,
        ),
    ]


# ---------------------------------------------------------------------------
# TestLineGrouping
# ---------------------------------------------------------------------------


class TestLineGrouping:
    def test_same_line(self, table_blocks):
        """3 rows of 3 blocks each → 3 lines."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        assert len(result.lines) == 3

    def test_reading_order(self, table_blocks):
        """First line's blocks are in left-to-right reading order."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        first_line_texts = [b.text for b in result.lines[0].blocks]
        assert first_line_texts == ["Item", "Qty", "Price"]

    def test_blocks_sorted_top_to_bottom(self, table_blocks):
        """Lines are sorted top-to-bottom by y_center."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        y_centers = [line.y_center for line in result.lines]
        assert y_centers == sorted(y_centers)

    def test_single_block_one_line(self):
        """A single block produces exactly one line."""
        block = OCRBlock(text="Hello", bbox=(10, 10, 100, 30), confidence=0.9)
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze([block])
        assert len(result.lines) == 1
        assert result.lines[0].blocks[0].text == "Hello"

    def test_empty_blocks_empty_result(self):
        """No blocks produces a LayoutResult with no lines."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze([])
        assert result.lines == []
        assert result.tables == []
        assert result.avg_confidence == 0.0


# ---------------------------------------------------------------------------
# TestTableDetection
# ---------------------------------------------------------------------------


class TestTableDetection:
    def test_table_detected(self, table_blocks):
        """3 aligned rows of 3 columns → at least 1 table detected."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        assert len(result.tables) >= 1

    def test_table_has_correct_rows(self, table_blocks):
        """Detected table has 3 rows."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        assert len(result.tables[0]) == 3

    def test_table_header_row_content(self, table_blocks):
        """First row of detected table contains 'Item', 'Qty', 'Price'."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        assert result.tables[0][0] == ["Item", "Qty", "Price"]

    def test_no_table_from_misaligned_blocks(self):
        """Blocks with varying x positions are not detected as a table."""
        blocks = [
            OCRBlock(text="A", bbox=(10, 10, 50, 30), confidence=0.9),
            OCRBlock(text="B", bbox=(200, 50, 240, 70), confidence=0.9),
            OCRBlock(text="C", bbox=(100, 90, 140, 110), confidence=0.9),
        ]
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(blocks)
        assert result.tables == []


# ---------------------------------------------------------------------------
# TestHeaderDetection
# ---------------------------------------------------------------------------


class TestHeaderDetection:
    def test_large_text_is_header(self, header_blocks):
        """Block with font_size_estimate >> median is marked as header."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(header_blocks)
        header_lines = [l for l in result.lines if l.is_header]
        assert len(header_lines) >= 1

    def test_regular_text_not_header(self, header_blocks):
        """Body text line is not marked as header."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(header_blocks)
        body_lines = [l for l in result.lines if not l.is_header]
        assert any("body text" in l.blocks[0].text for l in body_lines)

    def test_all_caps_is_header(self):
        """ALL CAPS text is detected as a header even at normal size."""
        blocks = [
            OCRBlock(
                text="SECTION TITLE",
                bbox=(10, 10, 200, 30),
                confidence=0.9,
                font_size_estimate=20.0,
            ),
            OCRBlock(
                text="body text here",
                bbox=(10, 50, 200, 70),
                confidence=0.9,
                font_size_estimate=20.0,
            ),
        ]
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(blocks)
        header_lines = [l for l in result.lines if l.is_header]
        assert any("SECTION TITLE" in l.blocks[0].text for l in header_lines)


# ---------------------------------------------------------------------------
# TestMarkdownRendering
# ---------------------------------------------------------------------------


class TestMarkdownRendering:
    def test_table_rendered(self, table_blocks):
        """Detected table is rendered as Markdown table (pipes present)."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        md = render_markdown(result)
        assert "|" in md

    def test_table_has_separator_row(self, table_blocks):
        """Markdown table includes the separator row of dashes."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        md = render_markdown(result)
        assert "---" in md

    def test_header_rendered(self, header_blocks):
        """Header line is rendered with ## prefix."""
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(header_blocks)
        md = render_markdown(result)
        assert md.startswith("#")

    def test_empty_layout_renders_empty_string(self):
        """Empty LayoutResult renders to empty string."""
        from parrot_loaders.ocr.models import LayoutResult

        layout = LayoutResult(lines=[], tables=[], columns_detected=1, avg_confidence=0.0)
        assert render_markdown(layout) == ""

    def test_regular_text_in_output(self):
        """Non-header, non-table text appears in rendered output."""
        blocks = [
            OCRBlock(text="Hello world", bbox=(10, 10, 200, 30), confidence=0.9),
        ]
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(blocks)
        md = render_markdown(result)
        assert "Hello world" in md
