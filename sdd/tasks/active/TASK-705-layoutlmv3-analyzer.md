# TASK-705: LayoutLMv3 Semantic Layout Analyzer

**Feature**: ImageLoader — OCR with Layout-Aware Extraction
**Spec**: `sdd/specs/image-loader.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-700
**Assigned-to**: unassigned

---

## Context

Optional semantic layout analyzer using Microsoft's LayoutLMv3 model. Unlike
the heuristic analyzer (TASK-704), this uses a transformer model to classify
each OCR token into semantic categories: title, paragraph, table, list, figure,
caption. This preserves document structure for complex layouts like explanation
diagrams, multi-column forms, and mixed content where pure geometry fails.

The legacy `documents/loaders/pdf.py` already has LayoutLMv3 code (lines 84-94)
which serves as a reference pattern.

Implements Spec Module 6.

---

## Scope

- Implement `LayoutLMv3Analyzer` in `parrot_loaders/ocr/layoutlm.py`
- Load `microsoft/layoutlmv3-base` with `apply_ocr=False` (we supply our own OCR)
- Take `List[OCRBlock]` + `PIL.Image` as input
- Rescale bounding boxes to 0-1000 range (LayoutLMv3 requirement)
- Run token classification → map predicted labels to semantic types
- Group labeled tokens into regions and produce `LayoutResult`
- Guard all imports (transformers, torch) with try/except
- Support CPU and GPU inference
- Write unit tests

**NOT in scope**: OCR backends, heuristic layout, ImageLoader class.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/ocr/layoutlm.py` | CREATE | LayoutLMv3Analyzer |
| `tests/loaders/test_ocr_layoutlm.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_loaders.ocr.models import OCRBlock, LayoutLine, LayoutResult  # from TASK-700
from PIL import Image
```

### Existing Signatures to Use (Legacy Reference)
```python
# documents/loaders/pdf.py — DO NOT import; use as pattern reference only

# Initialization (lines 84-94):
from transformers import (
    LayoutLMv3ForTokenClassification,  # line 21
    LayoutLMv3Processor                 # line 22
)
processor = LayoutLMv3Processor.from_pretrained(
    "microsoft/layoutlmv3-base", apply_ocr=False  # line 84-86
)
model = LayoutLMv3ForTokenClassification.from_pretrained(
    "microsoft/layoutlmv3-base"                    # line 89-91
)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)

# Bounding box rescaling (line 34-48):
# LayoutLMv3 expects bboxes in 0-1000 range
def rescale_bounding_boxes(bboxes, image_width, image_height, target_size=1000):
    rescaled_bboxes = []
    for bbox in bboxes:
        x1, y1 = bbox[0]  # Note: legacy uses polygon format
        x2, y2 = bbox[2]
        rescaled_bbox = [
            int(x1 / image_width * target_size),
            int(y1 / image_height * target_size),
            int(x2 / image_width * target_size),
            int(y2 / image_height * target_size)
        ]
        rescaled_bboxes.append(rescaled_bbox)
    return rescaled_bboxes
```

### Does NOT Exist
- ~~`parrot_loaders.ocr.layoutlm`~~ — does not exist yet; this task creates it
- ~~`LayoutLMv3Processor.extract_layout()`~~ — not a real method
- ~~`LayoutLMv3ForSequenceClassification`~~ — wrong class; use `ForTokenClassification`
- ~~`parrot.models.layoutlm`~~ — no such module

---

## Implementation Notes

### Pattern to Follow
```python
class LayoutLMv3Analyzer:
    """Semantic layout analyzer using LayoutLMv3 token classification."""

    # LayoutLMv3 base label mapping (token classification)
    LABEL_MAP = {
        0: "paragraph",
        1: "title",
        2: "list",
        3: "table",
        4: "figure",
        5: "caption",
    }

    def __init__(self, model_name: str = "microsoft/layoutlmv3-base"):
        from transformers import LayoutLMv3ForTokenClassification, LayoutLMv3Processor
        import torch

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._processor = LayoutLMv3Processor.from_pretrained(
            model_name, apply_ocr=False
        )
        self._model = LayoutLMv3ForTokenClassification.from_pretrained(model_name)
        self._model.to(self._device)
        self._model.eval()

    def analyze(
        self, blocks: List[OCRBlock], image: Image.Image
    ) -> LayoutResult:
        """Classify OCR blocks into semantic regions."""
        words = [b.text for b in blocks]
        bboxes = self._rescale_bboxes(blocks, image.width, image.height)

        encoding = self._processor(
            image, words, boxes=bboxes,
            return_tensors="pt", truncation=True, padding=True
        )
        encoding = {k: v.to(self._device) for k, v in encoding.items()}

        with torch.no_grad():
            outputs = self._model(**encoding)
            predictions = outputs.logits.argmax(-1).squeeze().tolist()

        # Map predictions to labels and group into LayoutResult
        ...
```

### Key Constraints
- LayoutLMv3 has a max sequence length of 512 tokens. For images with many
  OCR blocks, truncate or batch.
- Bounding boxes MUST be rescaled to 0-1000 integer range.
- The `apply_ocr=False` flag is critical — without it, LayoutLMv3 runs its
  own OCR which defeats the purpose.
- Model download (~500MB) happens on first use. Log a clear info message.
- The `LABEL_MAP` above is illustrative. The actual labels depend on the
  fine-tuning of the model. For the base model, use the default token
  classification head labels. Document the mapping clearly.

---

## Acceptance Criteria

- [ ] `LayoutLMv3Analyzer` loads model with `apply_ocr=False`
- [ ] Rescales bboxes to 0-1000 range correctly
- [ ] Classifies OCR tokens into semantic labels (title, paragraph, table, etc.)
- [ ] Groups labeled tokens into `LayoutResult` with `LayoutLine` entries
- [ ] Falls back gracefully when `transformers` or `torch` not installed
- [ ] Supports both CPU and GPU inference
- [ ] All tests pass: `pytest tests/loaders/test_ocr_layoutlm.py -v`

---

## Test Specification

```python
import pytest


class TestLayoutLMv3Analyzer:
    def test_import_guard(self):
        """Clear fallback when transformers not available."""
        ...

    def test_bbox_rescaling(self):
        """Bboxes rescaled to 0-1000 range."""
        from parrot_loaders.ocr.layoutlm import LayoutLMv3Analyzer
        analyzer = LayoutLMv3Analyzer.__new__(LayoutLMv3Analyzer)
        blocks = [
            OCRBlock(text="Title", bbox=(100, 50, 500, 100), confidence=0.95)
        ]
        rescaled = analyzer._rescale_bboxes(blocks, image_width=1000, image_height=800)
        assert all(0 <= v <= 1000 for bbox in rescaled for v in bbox)

    def test_analyze_returns_layout_result(self):
        """analyze() returns a LayoutResult with labeled lines."""
        # Requires model download — mark as integration test
        pytest.importorskip("transformers")
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/image-loader.spec.md` — especially Section 6 (Codebase Contract, LayoutLMv3 section)
2. **Check dependencies** — verify TASK-700 is completed
3. **Read** `documents/loaders/pdf.py` lines 84-94 for reference pattern
4. **Implement**, **verify**, **move**, **update index**

---

## Completion Note

*(Agent fills this in when done)*
