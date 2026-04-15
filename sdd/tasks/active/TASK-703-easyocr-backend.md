# TASK-703: EasyOCR Backend

**Feature**: ImageLoader — OCR with Layout-Aware Extraction
**Spec**: `sdd/specs/image-loader.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-700
**Assigned-to**: unassigned

---

## Context

GPU-friendly OCR alternative. EasyOCR natively supports CUDA and 80+ languages.
Returns bounding boxes as 4-corner polygons (similar to PaddleOCR).

Implements Spec Module 4.

---

## Scope

- Implement `EasyOCRBackend` class in `parrot_loaders/ocr/easyocr_backend.py`
- Wrap `easyocr.Reader` with configurable language and GPU detection
- Convert EasyOCR output `[(bbox_points, text, confidence), ...]` to `List[OCRBlock]`
- Font size estimate = bbox height (EasyOCR provides no font metadata)
- Guard import with try/except
- Write unit tests

**NOT in scope**: PaddleOCR, Tesseract, layout analysis, ImageLoader class.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/ocr/easyocr_backend.py` | CREATE | EasyOCRBackend |
| `tests/loaders/test_ocr_easyocr.py` | CREATE | Unit tests |

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
# easyocr API (external library):
import easyocr
reader = easyocr.Reader(['en'], gpu=True)  # gpu auto-detected via torch.cuda
result = reader.readtext(numpy_array)
# result: list of (bbox_points, text, confidence)
# bbox_points = [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
```

### Does NOT Exist
- ~~`easyocr.Reader.extract()`~~ — method is `.readtext()`, not `.extract()`
- ~~`parrot_loaders.ocr.easyocr_backend`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Key Constraints
- Name the file `easyocr_backend.py` (not `easyocr.py`) to avoid shadowing the `easyocr` package
- GPU detection: `easyocr.Reader(['en'], gpu=torch.cuda.is_available())`
- EasyOCR `Reader` is heavy to initialize — keep a cached instance per language
- Convert 4-corner polygons to `(x1, y1, x2, y2)` same as PaddleOCR (TASK-701)

---

## Acceptance Criteria

- [ ] `EasyOCRBackend` implements the `OCRBackend` protocol
- [ ] Properly detects GPU availability
- [ ] Converts polygon bboxes to `(x1, y1, x2, y2)`
- [ ] Raises `ImportError` if easyocr not installed
- [ ] All tests pass: `pytest tests/loaders/test_ocr_easyocr.py -v`

---

## Test Specification

```python
import pytest


class TestEasyOCRBackend:
    def test_import_guard(self):
        """Clear ImportError when easyocr not available."""
        ...

    def test_bbox_conversion(self):
        """4-point polygon to (x1, y1, x2, y2)."""
        ...

    def test_gpu_detection(self):
        """GPU flag set based on torch.cuda.is_available()."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/image-loader.spec.md`
2. **Check dependencies** — verify TASK-700 is completed
3. **Implement**, **verify**, **move**, **update index**

---

## Completion Note

*(Agent fills this in when done)*
