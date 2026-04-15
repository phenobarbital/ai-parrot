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
        tables, table_ranges = self._detect_tables(lines)
        columns = self._detect_columns(lines)
        avg_conf = sum(b.confidence for b in blocks) / len(blocks)

        return LayoutResult(
            lines=lines,
            tables=tables,
            table_line_ranges=table_ranges,
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

            # Condition 1: large font — require ALL blocks in the line to
            # be large.  A single oversized block among normal-sized ones
            # is a Tesseract artefact, not a real heading.
            block_sizes = [
                (b.font_size_estimate or (b.bbox[3] - b.bbox[1]))
                for b in line.blocks
            ]
            is_large = len(block_sizes) > 0 and all(
                s > threshold for s in block_sizes
            )

            # Condition 2: ALL CAPS (at least 4 chars to avoid false
            # positives).  Skip lines with many blocks — those are
            # likely table rows, not headings.
            is_caps = (
                len(full_text) >= 4
                and len(line.blocks) <= 2
                and bool(self._ALL_CAPS_RE.match(full_text))
            )

            if is_large or is_caps:
                line.is_header = True

        return lines

    # ------------------------------------------------------------------
    # Table detection
    # ------------------------------------------------------------------

    def _detect_tables(
        self, lines: List[LayoutLine]
    ) -> Tuple[List[List[List[str]]], List[Tuple[int, int]]]:
        """Detect table regions from vertically aligned block columns.

        Three or more consecutive lines are treated as a table when the x1
        positions of their blocks are mutually aligned within
        ``column_align_tolerance`` pixels.

        Args:
            lines: Lines sorted top-to-bottom.

        Returns:
            A tuple of (tables, ranges) where *tables* is a list of
            tables (each a list of rows of cell strings) and *ranges*
            is a list of ``(start, end)`` line-index pairs for each
            table (start inclusive, end exclusive).
        """
        if len(lines) < self.table_min_rows:
            return [], []

        def _col_positions(line: LayoutLine) -> List[int]:
            return [b.bbox[0] for b in line.blocks]

        def _lines_aligned(row_a: List[int], row_b: List[int]) -> bool:
            """Return True if the rows share enough aligned columns.

            OCR often drops a cell, so we allow rows with different
            column counts as long as the shorter row's x-positions all
            match a position in the longer row within tolerance.
            """
            if not row_a or not row_b:
                return False
            shorter, longer = sorted(
                [sorted(row_a), sorted(row_b)], key=len
            )
            # At least 2 columns in the shorter row
            if len(shorter) < 2:
                return False
            matched = 0
            for s_pos in shorter:
                if any(
                    abs(s_pos - l_pos) <= self.column_align_tolerance
                    for l_pos in longer
                ):
                    matched += 1
            return matched >= len(shorter)

        tables: List[List[List[str]]] = []
        ranges: List[Tuple[int, int]] = []
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
                # Determine the canonical column count (max across rows)
                col_count = max(len(lines[k].blocks) for k in run)

                # Build column x-positions from the row with the most
                # columns, then slot each row's cells into the nearest
                # column to handle missing cells.
                ref_idx = max(run, key=lambda k: len(lines[k].blocks))
                ref_positions = sorted(b.bbox[0] for b in lines[ref_idx].blocks)

                table: List[List[str]] = []
                for k in run:
                    row_blocks = lines[k].blocks
                    if len(row_blocks) == col_count:
                        table.append([b.text for b in row_blocks])
                    else:
                        # Slot cells into nearest reference column
                        cells = [""] * col_count
                        for b in row_blocks:
                            best_col = min(
                                range(col_count),
                                key=lambda c: abs(b.bbox[0] - ref_positions[c]),
                            )
                            if cells[best_col]:
                                cells[best_col] += " " + b.text
                            else:
                                cells[best_col] = b.text
                        table.append(cells)

                tables.append(table)
                ranges.append((run[0], run[-1] + 1))
                i = j  # skip consumed lines
            else:
                i += 1

        return tables, ranges

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

    # Map line index → (table_index, row_within_table) using the
    # pre-computed ranges so we don't need fragile text matching.
    table_start_map: dict[int, int] = {}  # start_line → table_index
    table_lines: set[int] = set()
    for t_idx, (start, end) in enumerate(layout.table_line_ranges):
        table_start_map[start] = t_idx
        for li in range(start, end):
            table_lines.add(li)

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

        if i in table_start_map:
            _flush_paragraph()
            table = layout.tables[table_start_map[i]]
            col_count = max(len(row) for row in table)
            rows_md: List[str] = []
            for r_idx, row in enumerate(table):
                padded = row + [""] * (col_count - len(row))
                rows_md.append("| " + " | ".join(padded) + " |")
                if r_idx == 0:
                    rows_md.append(
                        "| " + " | ".join(["---"] * col_count) + " |"
                    )
            parts.append("\n".join(rows_md))
            i += len(table)
        elif i in table_lines:
            # Already rendered as part of a table — skip
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
