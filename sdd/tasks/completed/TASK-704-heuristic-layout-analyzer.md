# TASK-704: Heuristic Layout Analyzer

**Feature**: ImageLoader — OCR with Layout-Aware Extraction
**Spec**: `sdd/specs/image-loader.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-700
**Assigned-to**: unassigned

---

## Context

Default layout analysis engine. Takes raw OCR blocks (text + bboxes) and
reconstructs spatial structure: lines, paragraphs, columns, tables, and
headers. Renders the result as clean markdown. This is the "no-model"
path — pure geometry-based heuristics.

Implements Spec Module 5.

---

## Scope

- Implement `HeuristicLayoutAnalyzer` in `parrot_loaders/ocr/layout.py`
- **Line grouping**: cluster blocks by y-coordinate (blocks within ~10px
  vertical distance are on the same line)
- **Column detection**: detect large horizontal gaps within lines that
  indicate multi-column layout
- **Table detection**: find grid-aligned blocks (consistent x-positions
  across 3+ consecutive lines → likely a table)
- **Header detection**: blocks whose bbox height is significantly larger
  than average, or text is ALL CAPS
- **Markdown rendering**: `render_markdown(layout: LayoutResult) -> str`
  that outputs headers as `##`, tables as markdown tables, paragraphs
  separated by `\n\n`
- Write comprehensive unit tests using mock OCRBlock fixtures

**NOT in scope**: LayoutLMv3, OCR backends, ImageLoader class.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/ocr/layout.py` | CREATE | HeuristicLayoutAnalyzer + render_markdown |
| `tests/loaders/test_ocr_layout.py` | CREATE | Unit tests with mock OCRBlock fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_loaders.ocr.models import OCRBlock, LayoutLine, LayoutResult  # from TASK-700
from typing import List, Tuple
```

### Existing Signatures to Use
```python
# From TASK-700 (parrot_loaders/ocr/models.py):
@dataclass
class OCRBlock:
    text: str
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float
    font_size_estimate: Optional[float] = None

@dataclass
class LayoutLine:
    blocks: List[OCRBlock]
    y_center: float
    is_header: bool = False

@dataclass
class LayoutResult:
    lines: List[LayoutLine]
    tables: List[List[List[str]]]  # list of tables
    columns_detected: int
    avg_confidence: float
```

### Does NOT Exist
- ~~`parrot_loaders.ocr.layout`~~ — does not exist yet; this task creates it
- ~~`OCRBlock.is_header`~~ — not on OCRBlock; header detection is in LayoutLine
- ~~`LayoutResult.markdown`~~ — not a field; use `render_markdown()` function

---

## Implementation Notes

### Pattern to Follow
```python
class HeuristicLayoutAnalyzer:
    def __init__(self, line_threshold: float = 10.0, table_min_rows: int = 3):
        self.line_threshold = line_threshold  # y-distance to group into same line
        self.table_min_rows = table_min_rows

    def analyze(self, blocks: List[OCRBlock]) -> LayoutResult:
        """Group blocks into structured layout."""
        lines = self._group_into_lines(blocks)
        lines = self._detect_headers(lines, blocks)
        tables = self._detect_tables(lines)
        columns = self._detect_columns(lines)
        avg_conf = sum(b.confidence for b in blocks) / max(len(blocks), 1)
        return LayoutResult(lines=lines, tables=tables,
                           columns_detected=columns, avg_confidence=avg_conf)

def render_markdown(layout: LayoutResult) -> str:
    """Convert LayoutResult to markdown string."""
    ...
```

### Key Constraints
- Line grouping: sort blocks by y_center, then cluster with threshold
- Within each line, sort blocks by x1 (left-to-right reading order)
- Table detection heuristic: if 3+ consecutive lines have blocks with
  x1 positions within ~20px of each other across columns → table
- Header detection: bbox height > 1.5x median height, or text matches
  `^[A-Z][A-Z0-9\s:,/&-]+$` (all caps)
- Tables rendered as markdown: `| col1 | col2 |` with separator row

---

## Acceptance Criteria

- [ ] `HeuristicLayoutAnalyzer.analyze()` returns a `LayoutResult`
- [ ] Lines correctly grouped from scattered OCRBlocks
- [ ] Tables detected from grid-aligned blocks
- [ ] Headers detected from large text / ALL CAPS
- [ ] `render_markdown()` produces valid markdown with headers, tables, paragraphs
- [ ] All tests pass: `pytest tests/loaders/test_ocr_layout.py -v`

---

## Test Specification

```python
import pytest
from parrot_loaders.ocr.models import OCRBlock
from parrot_loaders.ocr.layout import HeuristicLayoutAnalyzer, render_markdown


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
    """OCR block that should be detected as a header (large text)."""
    return [
        OCRBlock(text="PART ORDER GUIDE", bbox=(100, 20, 500, 70),
                 confidence=0.98, font_size_estimate=50.0),
        OCRBlock(text="This is regular body text.", bbox=(100, 100, 500, 120),
                 confidence=0.95, font_size_estimate=20.0),
    ]


class TestLineGrouping:
    def test_same_line(self, table_blocks):
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        assert len(result.lines) == 3  # 3 rows

    def test_reading_order(self, table_blocks):
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        first_line_texts = [b.text for b in result.lines[0].blocks]
        assert first_line_texts == ["Item", "Qty", "Price"]


class TestTableDetection:
    def test_table_detected(self, table_blocks):
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        assert len(result.tables) >= 1

class TestHeaderDetection:
    def test_large_text_is_header(self, header_blocks):
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(header_blocks)
        header_lines = [l for l in result.lines if l.is_header]
        assert len(header_lines) >= 1


class TestMarkdownRendering:
    def test_table_rendered(self, table_blocks):
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(table_blocks)
        md = render_markdown(result)
        assert "|" in md  # markdown table syntax

    def test_header_rendered(self, header_blocks):
        analyzer = HeuristicLayoutAnalyzer()
        result = analyzer.analyze(header_blocks)
        md = render_markdown(result)
        assert md.startswith("#")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/image-loader.spec.md`
2. **Check dependencies** — verify TASK-700 is completed
3. **Verify** `parrot_loaders/ocr/models.py` dataclasses exist
4. **Implement**, **verify**, **move**, **update index**

---

## Completion Note

Implemented `HeuristicLayoutAnalyzer` and `render_markdown` in `parrot_loaders/ocr/layout.py`.
- `_group_into_lines`: sorts by y-center, clusters within `line_threshold`, sorts each line left-to-right.
- `_detect_headers`: uses `header_font_ratio` (1.5x median) and ALL_CAPS regex pattern.
- `_detect_tables`: finds 3+ consecutive lines with aligned x1 positions (within 20px tolerance).
- `_detect_columns`: uses median block count per line.
- `render_markdown`: renders headers as `## text`, tables as pipe tables with separator, paragraphs separated by `\n\n`.
- 17 unit tests all pass covering all fixtures from the task specification.
