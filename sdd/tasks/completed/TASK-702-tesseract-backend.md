# TASK-702: Tesseract Backend

**Feature**: ImageLoader — OCR with Layout-Aware Extraction
**Spec**: `sdd/specs/image-loader.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-700
**Assigned-to**: unassigned

---

## Context

Ubiquitous OCR fallback. Tesseract is available on virtually every Linux system
via `apt install tesseract-ocr`. Uses `pytesseract.image_to_data()` which returns
bounding boxes, confidence, and text for each detected word.

Implements Spec Module 3.

---

## Scope

- Implement `TesseractBackend` class in `parrot_loaders/ocr/tesseract.py`
- Use `pytesseract.image_to_data(output_type=Output.DICT)` to get per-word
  bounding boxes (left, top, width, height) + confidence + text
- Merge words into text blocks by grouping on `block_num` and `par_num`
- Convert word-level bboxes into block-level `(x1, y1, x2, y2)` bboxes
- Estimate font size from average word height per block
- Guard import; detect `tesseract` binary availability at runtime
- Write unit tests

**NOT in scope**: PaddleOCR, EasyOCR, layout analysis, or ImageLoader class.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/ocr/tesseract.py` | CREATE | TesseractBackend implementation |
| `tests/loaders/test_ocr_tesseract.py` | CREATE | Unit tests |

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
# Legacy reference: documents/loaders/pdf.py:8-9, 392-393
import pytesseract
from pytesseract import Output
# pytesseract.image_to_data(image, lang=lang, output_type=Output.DICT)
# Returns dict with keys: 'level', 'page_num', 'block_num', 'par_num',
#   'line_num', 'word_num', 'left', 'top', 'width', 'height', 'conf', 'text'
# Each key maps to a list (one entry per detected word).
# conf is -1 for non-text entries.
```

### Does NOT Exist
- ~~`pytesseract.image_to_blocks()`~~ — not a real function; use `image_to_data()`
- ~~`pytesseract.extract()`~~ — not a real function
- ~~`parrot_loaders.ocr.tesseract`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
class TesseractBackend:
    def __init__(self, language: str = "en"):
        import pytesseract
        # Verify tesseract binary is available
        try:
            pytesseract.get_tesseract_version()
        except Exception:
            raise ImportError("tesseract binary not found. Install: apt install tesseract-ocr")
        self._lang = language

    def extract(self, image: Image.Image, language: str = "en") -> List[OCRBlock]:
        data = pytesseract.image_to_data(image, lang=language, output_type=Output.DICT)
        # Group words by (block_num, par_num) into blocks
        # Merge word bboxes: x1=min(left), y1=min(top), x2=max(left+width), y2=max(top+height)
        # Block confidence = mean of word confidences (excluding -1)
        ...
```

### Key Constraints
- `conf = -1` means non-text entry — skip those
- Word grouping key: `(block_num, par_num)` — this gives paragraph-level blocks
- Tesseract language codes differ from PaddleOCR: `"eng"` vs `"en"` — handle mapping

---

## Acceptance Criteria

- [ ] `TesseractBackend` implements the `OCRBackend` protocol
- [ ] Groups words into paragraph-level blocks with merged bboxes
- [ ] Confidence averaged per block (excluding -1 entries)
- [ ] Detects missing `tesseract` binary and raises clear `ImportError`
- [ ] All tests pass: `pytest tests/loaders/test_ocr_tesseract.py -v`

---

## Test Specification

```python
import pytest


class TestTesseractBackend:
    def test_word_grouping(self):
        """Words grouped by block_num+par_num into OCRBlocks."""
        ...

    def test_bbox_merging(self):
        """Word bboxes merged to block-level (x1,y1,x2,y2)."""
        ...

    def test_binary_detection(self):
        """Clear error when tesseract binary missing."""
        ...

    def test_language_mapping(self):
        """'en' mapped to 'eng' for tesseract."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/image-loader.spec.md`
2. **Check dependencies** — verify TASK-700 is completed
3. **Verify** `parrot_loaders/ocr/models.py` and `base.py` exist
4. **Implement**, **verify**, **move**, **update index**

---

## Completion Note

Implemented `TesseractBackend` in `parrot_loaders/ocr/tesseract.py`.
- Lazy imports pytesseract inside `__init__` and `extract`; raises `ImportError` if binary missing.
- `LANGUAGE_MAP` translates ISO 639-1 codes to Tesseract language data names.
- Groups per-word `image_to_data` output by `(block_num, par_num)` into `OCRBlock` instances.
- Merges word-level bboxes to block-level `(x1, y1, x2, y2)`.
- Skips entries with `conf == -1` (layout markers, not text).
- 10 unit tests all pass (mocking pytesseract via `sys.modules` injection).
