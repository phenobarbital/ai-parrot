# Feature Specification: ImageLoader — OCR with Layout-Aware Extraction

**Feature ID**: FEAT-100
**Date**: 2026-04-15
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The current `ImageUnderstandingLoader` requires an LLM (Google GenAI) to extract
text from images. This is effective for complex visual understanding but:

- **Cost**: Every image incurs an API call to Google GenAI.
- **Latency**: Network round-trip + model inference per image.
- **Unnecessary for text-heavy images**: Documents like order guides, forms,
  tables, and scanned pages are primarily text — OCR is faster, cheaper, and
  sufficient.
- **Offline/air-gapped**: Some deployments cannot reach external LLM APIs.

The legacy `documents/loaders/pdf.py` already has PaddleOCR + LayoutLMv3 code,
but it's tightly coupled to the old PDF pipeline and not usable as a standalone
image loader.

### Goals

- **G1**: Create `ImageLoader` — an OCR-based image-to-text loader that runs
  entirely locally (no LLM API calls).
- **G2**: Support layout-aware extraction so tables, columns, and spatial
  structure are preserved as markdown.
- **G3**: Support multiple OCR backends: PaddleOCR (default, best quality),
  Tesseract (ubiquitous fallback), and EasyOCR (GPU-friendly alternative).
- **G4**: Produce `Document` objects compatible with the existing chunking
  pipeline (`SemanticTextSplitter`).
- **G5**: Register in `LOADER_REGISTRY` and `LOADER_MAPPING` so the factory
  can dispatch to it.

### Non-Goals (explicitly out of scope)

- Replacing `ImageUnderstandingLoader` — both loaders coexist. Users choose
  based on their needs (OCR for text-heavy images, LLM for visual understanding).
- Training or fine-tuning OCR models.
- Handwriting recognition (out of scope for v1).
- Video frame extraction (handled by `VideoLoader`).

---

## 2. Architectural Design

### Overview

`ImageLoader` follows the standard `AbstractLoader` pattern. It loads image
files, runs OCR with optional layout analysis, reconstructs spatial structure
into markdown, and returns `Document` objects.

The layout reconstruction pipeline:

1. **Load image** via Pillow.
2. **Run OCR** to get text + bounding boxes.
3. **Layout analysis** — group bounding boxes into lines, paragraphs, columns,
   and tables using spatial heuristics (vertical/horizontal clustering).
4. **Markdown rendering** — convert structured layout into markdown with
   headers (large/bold text), tables, and paragraph breaks.
5. **Return Document(s)** with metadata including OCR confidence, dimensions,
   and detected structure counts.

### Component Diagram

```
ImageLoader (parrot_loaders/image.py)
     │
     ├── _load(path) → List[Document]
     │       │
     │       ├── _load_image(path) → PIL.Image
     │       │
     │       ├── _run_ocr(image) → List[OCRBlock]
     │       │       ├── PaddleOCR backend
     │       │       ├── Tesseract backend
     │       │       └── EasyOCR backend
     │       │
     │       ├── _analyze_layout(blocks) → LayoutResult
     │       │       ├── line grouping (y-axis clustering)
     │       │       ├── column detection (x-axis gaps)
     │       │       ├── table detection (grid alignment)
     │       │       └── header detection (font size / bold)
     │       │
     │       └── _render_markdown(layout) → str
     │
     └── AbstractLoader (chunking via SemanticTextSplitter)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractLoader` | extends | Base class for all loaders |
| `SemanticTextSplitter` | uses (via AbstractLoader) | Chunks the markdown output |
| `LOADER_REGISTRY` | registered in | `"ImageLoader": "parrot_loaders.image.ImageLoader"` |
| `LOADER_MAPPING` | registered in | Maps `.png`, `.jpg`, etc. (as secondary option) |
| `Document` | produces | Standard document model |

### Data Models

```python
from dataclasses import dataclass
from typing import List, Optional, Tuple

@dataclass
class OCRBlock:
    """A single text region detected by OCR."""
    text: str
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float  # 0.0 - 1.0
    font_size_estimate: Optional[float] = None  # relative, for header detection

@dataclass
class LayoutLine:
    """A horizontal line of text blocks."""
    blocks: List[OCRBlock]
    y_center: float
    is_header: bool = False

@dataclass
class LayoutResult:
    """Complete layout analysis of an image."""
    lines: List[LayoutLine]
    tables: List[List[List[str]]]  # list of tables, each table = list of rows
    columns_detected: int
    avg_confidence: float
```

### New Public Interfaces

```python
class ImageLoader(AbstractLoader):
    """OCR-based image loader with layout-aware text extraction.

    Unlike ImageUnderstandingLoader (LLM-based), this loader uses local
    OCR engines to extract text. Best for text-heavy images: scanned
    documents, forms, order guides, tables.
    """

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'image_ocr',
        ocr_backend: str = "auto",  # "paddleocr", "tesseract", "easyocr", "auto"
        language: str = "en",
        detect_tables: bool = True,
        detect_headers: bool = True,
        min_confidence: float = 0.5,
        dpi: int = 300,
        **kwargs
    ): ...

    async def _load(
        self, path: Union[str, PurePath], **kwargs
    ) -> List[Document]: ...
```

---

## 3. Module Breakdown

### Module 1: OCR Backend Abstraction
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/ocr/__init__.py`
- **Responsibility**: Define `OCRBackend` protocol and `OCRBlock` dataclass.
  Provide `get_ocr_backend(name)` factory function.
- **Depends on**: None (leaf module).

### Module 2: PaddleOCR Backend
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/ocr/paddle.py`
- **Responsibility**: Implement `PaddleOCRBackend` wrapping PaddleOCR.
  Extract text + bounding boxes + confidence from images.
- **Depends on**: Module 1, `paddleocr` package.

### Module 3: Tesseract Backend
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/ocr/tesseract.py`
- **Responsibility**: Implement `TesseractBackend` wrapping pytesseract.
  Uses `image_to_data(output_type=Output.DICT)` to get bounding boxes.
- **Depends on**: Module 1, `pytesseract` package.

### Module 4: EasyOCR Backend
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/ocr/easyocr.py`
- **Responsibility**: Implement `EasyOCRBackend` wrapping easyocr.
  GPU-friendly alternative with built-in language detection.
- **Depends on**: Module 1, `easyocr` package.

### Module 5: Layout Analyzer
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/ocr/layout.py`
- **Responsibility**: Group OCR blocks into lines (y-axis clustering),
  detect columns (x-axis gap analysis), detect tables (grid alignment),
  identify headers (relative font size / all-caps heuristics).
  Renders final layout as markdown.
- **Depends on**: Module 1 (OCRBlock, LayoutResult dataclasses).

### Module 6: ImageLoader
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/image.py`
- **Responsibility**: Main loader class. Extends `AbstractLoader`.
  Orchestrates: load image → OCR → layout analysis → markdown → Document.
  Register in `LOADER_REGISTRY`.
- **Depends on**: Modules 1, 5, and one of Modules 2-4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_ocr_block_dataclass` | Module 1 | OCRBlock creation and field access |
| `test_paddle_backend_extract` | Module 2 | PaddleOCR returns OCRBlocks from sample image |
| `test_tesseract_backend_extract` | Module 3 | Tesseract returns OCRBlocks from sample image |
| `test_easyocr_backend_extract` | Module 4 | EasyOCR returns OCRBlocks from sample image |
| `test_backend_auto_selection` | Module 1 | `get_ocr_backend("auto")` picks best available |
| `test_layout_line_grouping` | Module 5 | Blocks with similar y-coords grouped into lines |
| `test_layout_table_detection` | Module 5 | Grid-aligned blocks detected as table |
| `test_layout_header_detection` | Module 5 | Large/all-caps blocks marked as headers |
| `test_layout_markdown_render` | Module 5 | Layout rendered to valid markdown |
| `test_image_loader_init` | Module 6 | ImageLoader initializes with default params |
| `test_image_loader_load_png` | Module 6 | Load a PNG, verify Document produced |
| `test_image_loader_min_confidence` | Module 6 | Low-confidence blocks filtered out |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_png` | Load `docs/Part Order Guide.png`, verify text extraction + chunking |
| `test_loader_registry` | `ImageLoader` importable from `LOADER_REGISTRY` |
| `test_factory_dispatch` | Factory dispatches `.png` to `ImageLoader` when configured |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_image_path():
    """Path to a test image with text content."""
    return Path("docs/Part Order Guide.png")

@pytest.fixture
def sample_ocr_blocks():
    """Pre-built OCRBlock list for layout tests (no OCR engine needed)."""
    return [
        OCRBlock(text="PART ORDER GUIDE", bbox=(100, 50, 500, 90), confidence=0.98),
        OCRBlock(text="Item", bbox=(100, 150, 200, 170), confidence=0.95),
        OCRBlock(text="Quantity", bbox=(250, 150, 380, 170), confidence=0.95),
        OCRBlock(text="Price", bbox=(420, 150, 500, 170), confidence=0.96),
        OCRBlock(text="Widget A", bbox=(100, 180, 200, 200), confidence=0.93),
        OCRBlock(text="10", bbox=(250, 180, 280, 200), confidence=0.97),
        OCRBlock(text="$5.99", bbox=(420, 180, 500, 200), confidence=0.94),
    ]
```

---

## 5. Acceptance Criteria

- [ ] `ImageLoader` loads `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`, `.webp` files
- [ ] At least two OCR backends work (PaddleOCR + Tesseract)
- [ ] `ocr_backend="auto"` selects best available backend without error
- [ ] Layout analysis groups text into lines and paragraphs
- [ ] Tables detected and rendered as markdown tables
- [ ] Headers detected (all-caps or larger text) and rendered as `##`/`###`
- [ ] Output is valid markdown that `SemanticTextSplitter` can chunk
- [ ] `min_confidence` filters low-quality OCR results
- [ ] Metadata includes: `ocr_backend`, `avg_confidence`, `image_dimensions`,
      `table_count`, `language`
- [ ] Registered in `LOADER_REGISTRY` and importable
- [ ] All unit tests pass
- [ ] `docs/Part Order Guide.png` produces meaningful text extraction
- [ ] No LLM API calls — runs entirely locally

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.loaders.abstract import AbstractLoader  # verified: packages/ai-parrot/src/parrot/loaders/abstract.py:36
from parrot.stores.models import Document            # verified: packages/ai-parrot/src/parrot/stores/models.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/loaders/abstract.py
class AbstractLoader(ABC):                                                      # line 36
    extensions: List[str] = ['.*']                                              # class attr
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

    async def load(self, source=None, split_documents=True, ...) -> List[Document]  # line 600

# packages/ai-parrot-loaders/src/parrot_loaders/imageunderstanding.py
class ImageUnderstandingLoader(AbstractLoader):                                 # line 81
    extensions: List[str] = ['.png', '.jpg', '.jpeg', '.gif', '.bmp',
                             '.webp', '.tiff', '.tif']                          # line 82
    async def _load(self, path, **kwargs) -> List[Document]                     # line 189
    async def _analyze_image_with_ai(self, image_path: Path) -> str             # line 162
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ImageLoader` | `AbstractLoader` | extends | `abstract.py:36` |
| `ImageLoader._load()` | `self.create_document()` | method call | `abstract.py:750` |
| `ImageLoader._load()` | `self.create_metadata()` | method call | `abstract.py:717` |
| `LOADER_REGISTRY["ImageLoader"]` | `parrot_loaders/__init__.py` | dict entry | `__init__.py:9` |
| `LOADER_MAPPING[".png"]` | `parrot_loaders/factory.py` | dict entry | `factory.py:40` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.loaders.image`~~ — no `image.py` in `parrot/loaders/` (only in `parrot_loaders/`)
- ~~`parrot_loaders.ocr`~~ — the `ocr/` subpackage does not exist yet; must be created
- ~~`AbstractLoader.ocr_extract()`~~ — no OCR method on AbstractLoader
- ~~`parrot.ocr`~~ — no top-level OCR module
- ~~`ImageLoader`~~ — does not exist yet; this spec defines it
- ~~`parrot_loaders.image`~~ — does not exist yet; this spec creates it
- ~~`documents/loaders/pdf.PDFLoader`~~ — legacy loader, NOT in `parrot_loaders`; do not import from `documents/`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Follow `ImageUnderstandingLoader` structure for `__init__` signature and metadata patterns
- Use `AbstractLoader.create_metadata()` / `create_document()` for Document creation
- Guard OCR imports with try/except and provide clear error messages
- Use `self.logger` for all logging (never `print`)
- All OCR calls should be sync (wrapped if needed); the `_load` method is async
  but OCR engines are CPU-bound — use `asyncio.to_thread()` for blocking calls

### Known Risks / Gotchas

- **PaddleOCR** requires `paddlepaddle` which is ~200MB. Make it an optional
  dependency: `uv pip install ai-parrot-loaders[ocr]`.
- **Tesseract** requires system-level installation (`apt install tesseract-ocr`).
  Detect availability at runtime, not import time.
- **Table detection** from bounding boxes alone is heuristic. Start simple
  (grid-aligned boxes) and iterate.
- **Image preprocessing**: Some images need deskewing, contrast adjustment,
  or binarization for good OCR. Consider optional preprocessing via Pillow.
- **Font size estimation**: PaddleOCR provides box dimensions which can proxy
  font size. Tesseract provides explicit font info. EasyOCR does not — use
  box height as proxy.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `Pillow` | `>=10.0` | Image loading and preprocessing |
| `paddleocr` | `>=2.7` | Primary OCR backend (optional) |
| `paddlepaddle` | `>=2.5` | PaddleOCR runtime (optional) |
| `pytesseract` | `>=0.3.10` | Tesseract OCR wrapper (optional) |
| `easyocr` | `>=1.7` | GPU-friendly OCR (optional) |
| `numpy` | `>=1.24` | Bounding box math |

---

## 8. Open Questions

- [ ] Should the factory default for `.png`/`.jpg` change from `ImageUnderstandingLoader`
      to `ImageLoader`, or should users opt in explicitly? — *Owner: Jesus Lara*
- [ ] Should we integrate LayoutLMv3 (already imported in legacy code) for
      more accurate layout classification in a future version? — *Owner: TBD*
- [ ] Should `ImageLoader` support PDF pages rendered as images (for scanned
      PDFs), or keep that in `PDFLoader`? — *Owner: Jesus Lara*

---

## Worktree Strategy

- **Isolation**: `per-spec` — all 6 modules are sequential (each depends on prior).
- **Parallelizable**: Modules 2, 3, 4 (OCR backends) are independent of each
  other and can be parallelized after Module 1 is complete.
- **Cross-feature dependencies**: None — this is a standalone new loader.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-15 | Jesus Lara | Initial draft |
