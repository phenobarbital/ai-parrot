# TASK-700: OCR Backend Abstraction Layer

**Feature**: ImageLoader — OCR with Layout-Aware Extraction
**Spec**: `sdd/specs/image-loader.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation module for the ImageLoader feature. Defines the protocol (interface)
that all OCR backends must implement, the shared data models (`OCRBlock`,
`LayoutLine`, `LayoutResult`), and a factory function to select the best
available backend at runtime.

Implements Spec Module 1.

---

## Scope

- Create `parrot_loaders/ocr/` package with `__init__.py`
- Define `OCRBlock` dataclass (text, bbox, confidence, font_size_estimate)
- Define `LayoutLine` and `LayoutResult` dataclasses
- Define `OCRBackend` Protocol with `extract(image: Image.Image) -> List[OCRBlock]`
- Implement `get_ocr_backend(name: str) -> OCRBackend` factory function
  that auto-detects available backends in priority order: PaddleOCR > EasyOCR > Tesseract
- Write unit tests

**NOT in scope**: Implementing any actual OCR backend (Modules 2-4), layout analysis, or the ImageLoader class.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/ocr/__init__.py` | CREATE | Package init, exports, `get_ocr_backend()` factory |
| `packages/ai-parrot-loaders/src/parrot_loaders/ocr/models.py` | CREATE | `OCRBlock`, `LayoutLine`, `LayoutResult` dataclasses |
| `packages/ai-parrot-loaders/src/parrot_loaders/ocr/base.py` | CREATE | `OCRBackend` Protocol definition |
| `tests/loaders/test_ocr_models.py` | CREATE | Unit tests for dataclasses and factory |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from PIL import Image  # Pillow — already a project dependency
from typing import List, Optional, Tuple, Protocol
from dataclasses import dataclass
```

### Existing Signatures to Use
None — this is a leaf module with no dependencies on existing parrot code.

### Does NOT Exist
- ~~`parrot_loaders.ocr`~~ — does not exist yet; this task creates it
- ~~`parrot.ocr`~~ — no top-level OCR module
- ~~`AbstractLoader.ocr_extract()`~~ — no OCR method on AbstractLoader

---

## Implementation Notes

### Pattern to Follow
```python
# parrot_loaders/ocr/base.py
from typing import Protocol, List
from PIL import Image
from .models import OCRBlock

class OCRBackend(Protocol):
    """Protocol for OCR backends."""
    def extract(self, image: Image.Image, language: str = "en") -> List[OCRBlock]:
        """Run OCR on an image, return text blocks with bounding boxes."""
        ...
```

### Key Constraints
- Use `dataclass` (not Pydantic) for `OCRBlock` etc. — these are internal data transfer objects
- `get_ocr_backend("auto")` must NOT import backends eagerly — try each import in order and return the first available
- bbox format: `(x1, y1, x2, y2)` as integers (pixel coordinates)

---

## Acceptance Criteria

- [ ] `from parrot_loaders.ocr import OCRBlock, OCRBackend, get_ocr_backend` works
- [ ] `OCRBlock` has fields: text, bbox, confidence, font_size_estimate
- [ ] `LayoutResult` has fields: lines, tables, columns_detected, avg_confidence
- [ ] `get_ocr_backend("auto")` returns a backend or raises clear ImportError
- [ ] All tests pass: `pytest tests/loaders/test_ocr_models.py -v`

---

## Test Specification

```python
import pytest
from parrot_loaders.ocr.models import OCRBlock, LayoutLine, LayoutResult


class TestOCRBlock:
    def test_creation(self):
        block = OCRBlock(text="hello", bbox=(10, 20, 100, 40), confidence=0.95)
        assert block.text == "hello"
        assert block.confidence == 0.95
        assert block.font_size_estimate is None

    def test_bbox_tuple(self):
        block = OCRBlock(text="x", bbox=(0, 0, 50, 50), confidence=0.8)
        assert len(block.bbox) == 4


class TestGetOCRBackend:
    def test_auto_returns_backend(self):
        from parrot_loaders.ocr import get_ocr_backend
        # Should return whichever backend is available, or raise ImportError
        try:
            backend = get_ocr_backend("auto")
            assert hasattr(backend, 'extract')
        except ImportError:
            pytest.skip("No OCR backend available")

    def test_invalid_backend_raises(self):
        from parrot_loaders.ocr import get_ocr_backend
        with pytest.raises(ValueError, match="Unknown"):
            get_ocr_backend("nonexistent_backend")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/image-loader.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `parrot_loaders/ocr/` doesn't exist yet
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-700-ocr-backend-abstraction.md`
8. **Update index** → `"done"`

---

## Completion Note

## Completion Note

Implemented on 2026-04-15:
- Created parrot_loaders/ocr/models.py with OCRBlock, LayoutLine, LayoutResult dataclasses
- Created parrot_loaders/ocr/base.py with OCRBackend Protocol (runtime_checkable)
- Created parrot_loaders/ocr/__init__.py with get_ocr_backend() factory (lazy imports, auto-detection)
- Created tests/loaders/test_ocr_models.py — 11 passed, 1 skipped (no backend installed)
- All acceptance criteria met.
