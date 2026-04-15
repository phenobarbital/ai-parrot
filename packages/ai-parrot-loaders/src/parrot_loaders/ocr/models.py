"""
OCR data models for the ImageLoader feature.

These dataclasses are internal data transfer objects used across all OCR
backends and layout analyzers. They are intentionally plain dataclasses
(not Pydantic models) for maximum performance and minimal overhead.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class OCRBlock:
    """A single text region detected by OCR.

    Attributes:
        text: The extracted text content.
        bbox: Bounding box as (x1, y1, x2, y2) pixel coordinates (top-left to bottom-right).
        confidence: OCR confidence score, ranging from 0.0 to 1.0.
        font_size_estimate: Estimated relative font size (in pixels), used for
            header detection. Derived from bbox height. None if not available.
    """

    text: str
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float  # 0.0 - 1.0
    font_size_estimate: Optional[float] = None


@dataclass
class LayoutLine:
    """A horizontal line of text blocks at approximately the same y-coordinate.

    Attributes:
        blocks: OCR blocks belonging to this line, sorted left-to-right.
        y_center: The vertical center position of this line (in pixels).
        is_header: True if this line was detected as a header (large text or ALL CAPS).
    """

    blocks: List[OCRBlock]
    y_center: float
    is_header: bool = False


@dataclass
class LayoutResult:
    """Complete layout analysis result for a single image.

    Attributes:
        lines: All detected text lines, sorted top-to-bottom.
        tables: Detected tables, each represented as a list of rows,
            where each row is a list of cell strings.
        table_line_ranges: For each table, the (start, end) line indices
            (inclusive start, exclusive end) mapping it back to ``lines``.
        columns_detected: Number of visual columns detected (1 = single column).
        avg_confidence: Average OCR confidence across all blocks.
    """

    lines: List[LayoutLine]
    tables: List[List[List[str]]] = field(default_factory=list)
    table_line_ranges: List[Tuple[int, int]] = field(default_factory=list)
    columns_detected: int = 1
    avg_confidence: float = 0.0
