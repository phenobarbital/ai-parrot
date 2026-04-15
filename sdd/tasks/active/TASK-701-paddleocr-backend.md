# TASK-701: PaddleOCR Backend

**Feature**: ImageLoader — OCR with Layout-Aware Extraction
**Spec**: `sdd/specs/image-loader.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-700
**Assigned-to**: unassigned

---

## Context

Primary OCR backend providing the best quality text extraction with bounding boxes.
PaddleOCR includes detection + recognition + angle classification. Already used in
legacy `documents/loaders/pdf.py` — this task wraps it behind the `OCRBackend` protocol.

Implements Spec Module 2.

---

## Scope

- Implement `PaddleOCRBackend` class in `parrot_loaders/ocr/paddle.py`
- Wrap `PaddleOCR` with `use_angle_cls=True`, `lang` from parameter
- Convert PaddleOCR output format `[[[bbox_points], (text, confidence)], ...]`
  into `List[OCRBlock]` with normalized `(x1, y1, x2, y2)` bboxes
- Estimate font size from bbox height
- Guard import with try/except; raise clear `ImportError` if paddleocr unavailable
- Suppress PaddleOCR's verbose logging (`ppocr` logger → WARNING)
- Write unit tests

**NOT in scope**: Tesseract, EasyOCR, layout analysis, or ImageLoader class.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/ocr/paddle.py` | CREATE | PaddleOCRBackend implementation |
| `tests/loaders/test_ocr_paddle.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_loaders.ocr.models import OCRBlock  # created by TASK-700
from parrot_loaders.ocr.base import OCRBackend   # created by TASK-700
from PIL import Image
```

### Existing Signatures to Use
```python
# Legacy reference: documents/loaders/pdf.py:498-510
# PaddleOCR initialization pattern:
ocr_model = PaddleOCR(lang='en', use_angle_cls=True)
result = ocr_model.ocr(img_path, cls=True)
# result format: list of pages, each page = list of [bbox_points, (text, confidence)]
# bbox_points = [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] (4-corner polygon)
```

### Does NOT Exist
- ~~`paddleocr.PaddleOCR.extract_text()`~~ — method is `.ocr()`, not `.extract_text()`
- ~~`parrot_loaders.ocr.paddle`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
class PaddleOCRBackend:
    def __init__(self, language: str = "en"):
        from paddleocr import PaddleOCR
        logging.getLogger('ppocr').setLevel(logging.WARNING)
        self._ocr = PaddleOCR(lang=language, use_angle_cls=True, show_log=False)

    def extract(self, image: Image.Image, language: str = "en") -> List[OCRBlock]:
        # Convert PIL Image to numpy array for PaddleOCR
        import numpy as np
        img_array = np.array(image)
        result = self._ocr.ocr(img_array, cls=True)
        # Convert 4-point polygon to (x1, y1, x2, y2) bounding box
        ...
```

### Key Constraints
- PaddleOCR returns 4-corner polygons; convert to axis-aligned `(x1, y1, x2, y2)`
  by taking `min(xs), min(ys), max(xs), max(ys)`
- Font size estimate = `y2 - y1` (bbox height in pixels)
- Filter blocks where confidence < 0.1 (noise)

---

## Acceptance Criteria

- [ ] `PaddleOCRBackend` implements the `OCRBackend` protocol
- [ ] Converts PaddleOCR polygon bboxes to `(x1, y1, x2, y2)` tuples
- [ ] Populates `font_size_estimate` from bbox height
- [ ] Raises `ImportError` with clear message if paddleocr not installed
- [ ] Suppresses ppocr DEBUG/INFO logging
- [ ] All tests pass: `pytest tests/loaders/test_ocr_paddle.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import patch, MagicMock


class TestPaddleOCRBackend:
    def test_import_guard(self):
        """Clear ImportError when paddleocr not available."""
        with patch.dict('sys.modules', {'paddleocr': None}):
            with pytest.raises(ImportError):
                from parrot_loaders.ocr.paddle import PaddleOCRBackend
                PaddleOCRBackend()

    def test_bbox_conversion(self):
        """4-point polygon converted to (x1, y1, x2, y2)."""
        from parrot_loaders.ocr.paddle import PaddleOCRBackend
        # Test the conversion logic with mock data
        ...

    def test_confidence_filter(self):
        """Blocks with very low confidence are filtered."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/image-loader.spec.md` for full context
2. **Check dependencies** — verify TASK-700 is completed
3. **Verify** `parrot_loaders/ocr/models.py` and `base.py` exist from TASK-700
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
