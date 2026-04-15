"""
Heuristic layout analyzer for parrot_loaders.

Converts a flat list of :class:`OCRBlock` objects into a structured
:class:`LayoutResult` using pure geometry-based heuristics.

Stages
------
1. **Line grouping** — cluster blocks whose y-centres are within
   ``line_threshold`` pixels of each other.
2. **Header detection** — mark a line as a header when its text is
   significantly larger than average, or it is written in ALL CAPS.
3. **Table detection** — identify 3+ consecutive lines whose column
   x-positions are vertically aligned.
4. **Column detection** — count how many visual columns are present.

The :func:`render_markdown` function converts a :class:`LayoutResult` into
a clean Markdown string.
"""
import re
import statistics
from typing import List, Optional, Tuple

from .models import LayoutLine, LayoutResult, OCRBlock


# ---------------------------------------------------------------------------
# HeuristicLayoutAnalyzer
# ---------------------------------------------------------------------------


class HeuristicLayoutAnalyzer:
    """Geometry-based layout analyzer that requires no ML model.

    Args:
        line_threshold: Maximum vertical pixel distance between the
            y-centres of two blocks for them to be placed on the same line.
        table_min_rows: Minimum number of consecutive lines needed to call a
            region a table.
        column_align_tolerance: Maximum horizontal pixel difference between
            the x1 positions of two blocks on different lines for them to be
            considered column-aligned.
        header_font_ratio: Ratio above the median font size that causes a
            block to be classified as a header (default 1.5×).
    """

    _ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9\s:,/&\-]+$")

    def __init__(
        self,
        line_threshold: float = 10.0,
        table_min_rows: int = 3,
        column_align_tolerance: float = 20.0,
        header_font_ratio: float = 1.5,
    ) -> None:
        self.line_threshold = line_threshold
        self.table_min_rows = table_min_rows
        self.column_align_tolerance = column_align_tolerance
        self.header_font_ratio = header_font_ratio

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, blocks: List[OCRBlock]) -> LayoutResult:
        """Analyse *blocks* and return a structured :class:`LayoutResult`.

        Args:
            blocks: Raw OCR blocks to analyse.

        Returns:
            A :class:`LayoutResult` containing grouped lines, detected tables,
            column count, and average confidence.
        """
        if not blocks:
            return LayoutResult(
                lines=[],
                tables=[],
                columns_detected=1,
                avg_confidence=0.0,
            )

        lines = self._group_into_lines(blocks)
        lines = self._detect_headers(lines, blocks)
        tables = self._detect_tables(lines)
        columns = self._detect_columns(lines)
        avg_conf = sum(b.confidence for b in blocks) / len(blocks)

        return LayoutResult(
            lines=lines,
            tables=tables,
            columns_detected=columns,
            avg_confidence=avg_conf,
        )

    # ------------------------------------------------------------------
    # Line grouping
    # ------------------------------------------------------------------

    def _group_into_lines(self, blocks: List[OCRBlock]) -> List[LayoutLine]:
        """Cluster *blocks* into horizontal lines by y-centre proximity.

        Blocks are sorted by y-centre and greedily assigned to the current
        line if their y-centre is within ``line_threshold`` of the running
        mean y-centre.  Each line's blocks are then sorted left-to-right by
        x1.

        Args:
            blocks: Unsorted OCR blocks.

        Returns:
            List of :class:`LayoutLine` objects, sorted top-to-bottom.
        """

        def _y_center(b: OCRBlock) -> float:
            return (b.bbox[1] + b.bbox[3]) / 2.0

        sorted_blocks = sorted(blocks, key=_y_center)

        lines: List[LayoutLine] = []
        current_group: List[OCRBlock] = []
        current_y: Optional[float] = None

        for block in sorted_blocks:
            yc = _y_center(block)
            if current_y is None or abs(yc - current_y) <= self.line_threshold:
                current_group.append(block)
                current_y = sum(_y_center(b) for b in current_group) / len(
                    current_group
                )
            else:
                # Flush current group
                sorted_group = sorted(current_group, key=lambda b: b.bbox[0])
                group_y = sum(_y_center(b) for b in sorted_group) / len(sorted_group)
                lines.append(LayoutLine(blocks=sorted_group, y_center=group_y))
                current_group = [block]
                current_y = yc

        if current_group:
            sorted_group = sorted(current_group, key=lambda b: b.bbox[0])
            group_y = sum(_y_center(b) for b in sorted_group) / len(sorted_group)
            lines.append(LayoutLine(blocks=sorted_group, y_center=group_y))

        return lines

    # ------------------------------------------------------------------
    # Header detection
    # ------------------------------------------------------------------

    def _detect_headers(
        self, lines: List[LayoutLine], all_blocks: List[OCRBlock]
    ) -> List[LayoutLine]:
        """Mark lines as headers if their text is large or ALL CAPS.

        A line is a header when at least one of its blocks has a
        ``font_size_estimate`` greater than ``header_font_ratio`` times the
        median font size of all blocks, OR when its concatenated text matches
        the ALL CAPS pattern.

        Args:
            lines: Lines to inspect.
            all_blocks: All OCR blocks (used to compute the global median).

        Returns:
            The same list with ``is_header`` set where appropriate.
        """
        sizes = [
            b.font_size_estimate
            for b in all_blocks
            if b.font_size_estimate is not None
        ]
        if not sizes:
            # Fall back to bbox height
            sizes = [b.bbox[3] - b.bbox[1] for b in all_blocks]

        median_size = statistics.median(sizes) if sizes else 0.0
        threshold = median_size * self.header_font_ratio

        for line in lines:
            full_text = " ".join(b.text for b in line.blocks)

            # Condition 1: large font
            is_large = any(
                (b.font_size_estimate or (b.bbox[3] - b.bbox[1])) > threshold
                for b in line.blocks
            )

            # Condition 2: ALL CAPS (at least 4 chars to avoid false positives)
            is_caps = len(full_text) >= 4 and bool(self._ALL_CAPS_RE.match(full_text))

            if is_large or is_caps:
                line.is_header = True

        return lines

    # ------------------------------------------------------------------
    # Table detection
    # ------------------------------------------------------------------

    def _detect_tables(
        self, lines: List[LayoutLine]
    ) -> List[List[List[str]]]:
        """Detect table regions from vertically aligned block columns.

        Three or more consecutive lines are treated as a table when the x1
        positions of their blocks are mutually aligned within
        ``column_align_tolerance`` pixels.

        Args:
            lines: Lines sorted top-to-bottom.

        Returns:
            A list of tables, each a list of rows, each row a list of cell
            strings.
        """
        if len(lines) < self.table_min_rows:
            return []

        def _col_positions(line: LayoutLine) -> List[int]:
            return [b.bbox[0] for b in line.blocks]

        def _lines_aligned(row_a: List[int], row_b: List[int]) -> bool:
            """Return True if both rows have the same number of columns and
            each corresponding x-position is within tolerance."""
            if len(row_a) != len(row_b):
                return False
            return all(
                abs(a - b) <= self.column_align_tolerance
                for a, b in zip(sorted(row_a), sorted(row_b))
            )

        tables: List[List[List[str]]] = []
        n = len(lines)
        i = 0
        while i < n:
            # Try to extend a table starting at line i
            run = [i]
            j = i + 1
            while j < n and _lines_aligned(
                _col_positions(lines[run[-1]]), _col_positions(lines[j])
            ):
                run.append(j)
                j += 1

            if len(run) >= self.table_min_rows:
                table = [
                    [b.text for b in lines[k].blocks] for k in run
                ]
                tables.append(table)
                i = j  # skip consumed lines
            else:
                i += 1

        return tables

    # ------------------------------------------------------------------
    # Column detection
    # ------------------------------------------------------------------

    def _detect_columns(self, lines: List[LayoutLine]) -> int:
        """Estimate the number of visual columns.

        Returns the median number of blocks per line (or 1 if no lines).

        Args:
            lines: Grouped layout lines.

        Returns:
            Integer column count (at least 1).
        """
        if not lines:
            return 1
        counts = [len(line.blocks) for line in lines]
        return max(1, round(statistics.median(counts)))


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


def render_markdown(layout: LayoutResult) -> str:
    """Convert a :class:`LayoutResult` into a Markdown string.

    Rendering rules:

    * **Headers** → ``## <text>``
    * **Table lines** → rendered as a Markdown table with a separator row
      after the first row.
    * **Regular lines** → plain text; consecutive non-table, non-header lines
      are joined within a paragraph (separated by spaces), and paragraphs are
      separated by ``\\n\\n``.

    Args:
        layout: The layout result to render.

    Returns:
        A Markdown-formatted string.
    """
    if not layout.lines:
        return ""

    # Build a set of line indices that belong to a detected table
    table_line_map: dict[int, int] = {}  # line_index → table_index
    _table_start_tracker: dict[int, int] = {}  # table_index → first y_center

    # Re-detect table membership by matching layout.tables against lines
    # We use the text content for matching (order-stable).
    _matched: List[bool] = [False] * len(layout.lines)
    for table in layout.tables:
        table_texts = [[cell for cell in row] for row in table]
        # Find the first line index that matches the first table row
        for start_idx in range(len(layout.lines)):
            if _matched[start_idx]:
                continue
            first_row_texts = [b.text for b in layout.lines[start_idx].blocks]
            if first_row_texts == table_texts[0]:
                # Check consecutive rows
                ok = True
                for r, row in enumerate(table_texts):
                    idx = start_idx + r
                    if idx >= len(layout.lines):
                        ok = False
                        break
                    if [b.text for b in layout.lines[idx].blocks] != row:
                        ok = False
                        break
                if ok:
                    for r in range(len(table_texts)):
                        _matched[start_idx + r] = True
                    break

    # Now render
    parts: List[str] = []
    paragraph_buf: List[str] = []

    def _flush_paragraph() -> None:
        if paragraph_buf:
            parts.append(" ".join(paragraph_buf))
            paragraph_buf.clear()

    i = 0
    n = len(layout.lines)
    while i < n:
        line = layout.lines[i]
        line_text = " ".join(b.text for b in line.blocks)

        if _matched[i]:
            # Find this table in layout.tables
            _flush_paragraph()
            # Locate the table starting at i
            matched_table: Optional[List[List[str]]] = None
            for table in layout.tables:
                first_row_texts = [b.text for b in layout.lines[i].blocks]
                if first_row_texts == table[0]:
                    matched_table = table
                    break
            if matched_table:
                col_count = max(len(row) for row in matched_table)
                rows_md: List[str] = []
                for r_idx, row in enumerate(matched_table):
                    # Pad row to col_count
                    padded = row + [""] * (col_count - len(row))
                    rows_md.append("| " + " | ".join(padded) + " |")
                    if r_idx == 0:
                        rows_md.append("| " + " | ".join(["---"] * col_count) + " |")
                parts.append("\n".join(rows_md))
                i += len(matched_table)
            else:
                # Fallback: treat as normal line
                paragraph_buf.append(line_text)
                i += 1
        elif line.is_header:
            _flush_paragraph()
            parts.append(f"## {line_text}")
            i += 1
        else:
            paragraph_buf.append(line_text)
            i += 1

    _flush_paragraph()

    return "\n\n".join(parts)
