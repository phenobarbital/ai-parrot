# TASK-706: ImageLoader Class and Registry Integration

**Feature**: ImageLoader — OCR with Layout-Aware Extraction
**Spec**: `sdd/specs/image-loader.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-700, TASK-701, TASK-704, TASK-705
**Assigned-to**: unassigned

---

## Context

Main loader class that orchestrates the full pipeline: load image → OCR → layout
analysis → markdown → Document. This is the public-facing class that users
instantiate. Also registers in `LOADER_REGISTRY`.

Implements Spec Module 7.

---

## Scope

- Implement `ImageLoader` class in `parrot_loaders/image.py`
- Extend `AbstractLoader` with same pattern as `ImageUnderstandingLoader`
- Parameters: `ocr_backend`, `layout_model`, `language`, `detect_tables`,
  `detect_headers`, `min_confidence`, `dpi`
- `_load()` pipeline:
  1. Open image with Pillow (handle DPI conversion)
  2. Run OCR via selected backend → `List[OCRBlock]`
  3. Filter blocks below `min_confidence`
  4. Run layout analysis (heuristic or LayoutLMv3 based on `layout_model`)
  5. Render markdown via `render_markdown()`
  6. Create `Document` with comprehensive metadata
- Use `asyncio.to_thread()` for blocking OCR/model calls
- Register in `LOADER_REGISTRY` in `__init__.py`
- Write unit and integration tests

**NOT in scope**: Changing the factory default for `.png`/`.jpg` (stays as ImageUnderstandingLoader).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/image.py` | CREATE | ImageLoader class |
| `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` | MODIFY | Add `"ImageLoader"` to `LOADER_REGISTRY` |
| `tests/loaders/test_image_loader.py` | CREATE | Unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader       # verified: abstract.py:36
from parrot.stores.models import Document                 # verified: stores/models.py
from parrot_loaders.ocr import get_ocr_backend           # from TASK-700
from parrot_loaders.ocr.models import OCRBlock            # from TASK-700
from parrot_loaders.ocr.layout import HeuristicLayoutAnalyzer, render_markdown  # from TASK-704
from PIL import Image
import asyncio
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/loaders/abstract.py
class AbstractLoader(ABC):                                                      # line 36
    chunk_size: int       # = kwargs.get('chunk_size', 512)                     # line 63
    chunk_overlap: int    # = kwargs.get('chunk_overlap', 50)                   # line 64
    min_chunk_size: int   # = kwargs.get('min_chunk_size', 30)                  # line 65

    def __init__(self, source=None, *, tokenizer=None, text_splitter=None,
                 source_type='file', **kwargs)                                  # line 44

    @abstractmethod
    async def _load(self, source: Union[str, PurePath], **kwargs) -> List[Document]  # line 460

    def create_metadata(self, path, doctype='document', source_type='source',
                        doc_metadata=None, **kwargs) -> dict                    # line 717

    def create_document(self, content, path, metadata=None, **kwargs) -> Document  # line 750

# packages/ai-parrot-loaders/src/parrot_loaders/__init__.py
LOADER_REGISTRY: dict[str, str] = {                                             # line 9
    "ImageUnderstandingLoader": "parrot_loaders.imageunderstanding.ImageUnderstandingLoader",  # line 33
    # ImageLoader will be added here
}

# Reference: ImageUnderstandingLoader pattern
# packages/ai-parrot-loaders/src/parrot_loaders/imageunderstanding.py
class ImageUnderstandingLoader(AbstractLoader):                                 # line 81
    extensions: List[str] = ['.png', '.jpg', '.jpeg', '.gif', '.bmp',
                             '.webp', '.tiff', '.tif']                          # line 82
```

### Does NOT Exist
- ~~`parrot_loaders.image`~~ — does not exist yet; this task creates it
- ~~`AbstractLoader.ocr_extract()`~~ — no OCR method on AbstractLoader
- ~~`AbstractLoader.analyze_layout()`~~ — no layout method on AbstractLoader
- ~~`LOADER_MAPPING` auto-dispatch to ImageLoader~~ — factory stays pointing to ImageUnderstandingLoader

---

## Implementation Notes

### Pattern to Follow
```python
class ImageLoader(AbstractLoader):
    """OCR-based image loader with layout-aware text extraction."""

    extensions: List[str] = ['.png', '.jpg', '.jpeg', '.gif', '.bmp',
                             '.webp', '.tiff', '.tif']

    def __init__(self, source=None, *, ocr_backend="auto",
                 layout_model=None, language="en",
                 detect_tables=True, detect_headers=True,
                 min_confidence=0.5, dpi=300, **kwargs):
        super().__init__(source, source_type='image_ocr', **kwargs)
        self._backend = get_ocr_backend(ocr_backend)
        self._layout_model = layout_model
        self._language = language
        self._min_confidence = min_confidence
        # Initialize layout analyzer
        if layout_model == "layoutlmv3":
            from parrot_loaders.ocr.layoutlm import LayoutLMv3Analyzer
            self._analyzer = LayoutLMv3Analyzer()
        else:
            self._analyzer = HeuristicLayoutAnalyzer()

    async def _load(self, path, **kwargs) -> List[Document]:
        image = Image.open(str(path))
        # Run OCR in thread pool (CPU-bound)
        blocks = await asyncio.to_thread(self._backend.extract, image, self._language)
        # Filter low confidence
        blocks = [b for b in blocks if b.confidence >= self._min_confidence]
        # Layout analysis
        if self._layout_model == "layoutlmv3":
            layout = await asyncio.to_thread(self._analyzer.analyze, blocks, image)
        else:
            layout = self._analyzer.analyze(blocks)
        # Render markdown
        md_text = render_markdown(layout)
        # Create document
        meta = self.create_metadata(path=path, doctype='image', source_type='image_ocr',
            doc_metadata={
                'ocr_backend': self._backend.__class__.__name__,
                'layout_model': self._layout_model or 'heuristic',
                'avg_confidence': layout.avg_confidence,
                'image_dimensions': (image.width, image.height),
                'table_count': len(layout.tables),
                'language': self._language,
            })
        return [self.create_document(content=md_text, path=path, metadata=meta)]
```

### Key Constraints
- Use `asyncio.to_thread()` for all blocking OCR/model calls
- `extensions` should match `ImageUnderstandingLoader` for consistency
- Metadata must include all fields listed in acceptance criteria
- LayoutLMv3 import must be lazy (inside `__init__`, not module level)

---

## Acceptance Criteria

- [ ] `ImageLoader` extends `AbstractLoader` and implements `_load()`
- [ ] Supports `ocr_backend="auto"`, `"paddleocr"`, `"tesseract"`, `"easyocr"`
- [ ] Supports `layout_model=None` (heuristic) and `layout_model="layoutlmv3"`
- [ ] Filters blocks below `min_confidence`
- [ ] Metadata includes: ocr_backend, layout_model, avg_confidence, image_dimensions, table_count, language
- [ ] Registered in `LOADER_REGISTRY` as `"ImageLoader": "parrot_loaders.image.ImageLoader"`
- [ ] `from parrot_loaders.image import ImageLoader` works
- [ ] Integration test: `docs/Part Order Guide.png` produces meaningful markdown
- [ ] All tests pass: `pytest tests/loaders/test_image_loader.py -v`

---

## Test Specification

```python
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock


class TestImageLoaderInit:
    def test_default_init(self):
        """ImageLoader initializes with auto backend and heuristic layout."""
        from parrot_loaders.image import ImageLoader
        loader = ImageLoader()
        assert loader._layout_model is None

    def test_layoutlmv3_init(self):
        """layout_model='layoutlmv3' loads LayoutLMv3Analyzer."""
        pytest.importorskip("transformers")
        from parrot_loaders.image import ImageLoader
        loader = ImageLoader(layout_model="layoutlmv3")
        assert loader._layout_model == "layoutlmv3"


class TestImageLoaderLoad:
    @pytest.mark.asyncio
    async def test_load_png(self):
        """Load docs/Part Order Guide.png, verify Document returned."""
        from parrot_loaders.image import ImageLoader
        loader = ImageLoader(source="docs/Part Order Guide.png")
        docs = await loader.load()
        assert len(docs) >= 1
        assert docs[0].page_content  # non-empty
        assert docs[0].metadata.get('document_meta', {}).get('ocr_backend')

    @pytest.mark.asyncio
    async def test_min_confidence_filter(self):
        """Low-confidence blocks filtered out."""
        from parrot_loaders.image import ImageLoader
        loader = ImageLoader(min_confidence=0.99)
        # With very high threshold, most blocks filtered → less content
        ...


class TestImageLoaderRegistry:
    def test_in_registry(self):
        """ImageLoader is in LOADER_REGISTRY."""
        from parrot_loaders import LOADER_REGISTRY
        assert "ImageLoader" in LOADER_REGISTRY
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/image-loader.spec.md`
2. **Check dependencies** — verify TASK-700, TASK-701 (or TASK-702), TASK-704, TASK-705 are completed
3. **Verify** all OCR and layout modules exist
4. **Read** `ImageUnderstandingLoader` at `parrot_loaders/imageunderstanding.py` for pattern reference
5. **Implement**, **verify**, **move**, **update index**

---

## Completion Note

Implemented `ImageLoader` in `parrot_loaders/image.py`.
- Extends `AbstractLoader`; implements `_load()` with `asyncio.to_thread()` for blocking OCR/layout calls.
- Constructor accepts `ocr_backend`, `layout_model`, `language`, `min_confidence`, `dpi`, `detect_tables`, `detect_headers`.
- Pipeline: Pillow image open → OCR via `get_ocr_backend()` → confidence filter → `HeuristicLayoutAnalyzer` or `LayoutLMv3Analyzer` → `render_markdown()` → `create_document()`.
- Metadata includes: `ocr_backend`, `layout_model`, `avg_confidence`, `image_dimensions`, `table_count`, `language`.
- Registered in `LOADER_REGISTRY` as `"ImageLoader": "parrot_loaders.image.ImageLoader"`.
- 12 unit tests pass; 2 integration tests skipped (model download / docs image not in worktree).
