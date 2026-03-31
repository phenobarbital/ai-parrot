# Feature Specification: PowerPointLoader Image Parsing via GoogleGenAIClient

**Feature ID**: FEAT-073
**Date**: 2026-03-31
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.x

---

## 1. Motivation & Business Requirements

> PowerPoint presentations frequently contain images (diagrams, charts, photos, infographics) that carry critical information. The current `PowerPointLoader` either skips image-only slides entirely (`skip_image_only_slides=True`) or includes them with no textual representation of the image content. This means valuable information embedded in images is lost during document ingestion for RAG pipelines.

### Problem Statement

When a PPTX slide contains images, the `PowerPointLoader` has no ability to extract or describe the visual content. Image-only slides are skipped by default, and slides with mixed text+images lose the image context entirely. This degrades retrieval quality in downstream RAG applications.

### Goals

- **G1**: Detect images within each slide during PPTX processing (both `pptx` and `markitdown` backends).
- **G2**: Extract images as bytes from slides using `python-pptx`.
- **G3**: Send extracted images to `GoogleGenAIClient.image_understanding()` to obtain:
  - A markdown-formatted text extraction with layout preservation (for images containing text, tables, diagrams).
  - A natural-language summary/explanation of the image content.
- **G4**: Integrate the image descriptions into the slide's Document output seamlessly (appended under an `## Images` section in markdown mode).
- **G5**: Make image parsing opt-in via a constructor parameter (`parse_images: bool = False`) so users without Google credentials are unaffected.

### Non-Goals (explicitly out of scope)

- Video extraction or processing from PPTX files.
- Image extraction from other loader types (PDF, DOCX) — those are separate features.
- Training or fine-tuning models on extracted image content.
- Supporting providers other than GoogleGenAIClient for image understanding (future extensibility is fine, but only Google is implemented now).

---

## 2. Architectural Design

### Overview

When `parse_images=True`, the `PowerPointLoader` will:

1. During slide processing (pptx backend), detect shapes of type `PICTURE` (shape_type 13).
2. Extract the image blob (bytes) from each picture shape.
3. Call `GoogleGenAIClient.image_understanding()` with a structured prompt requesting markdown text extraction + content summary.
4. Append the returned descriptions to the slide's content before creating the Document.

For the `markitdown` backend, since it doesn't expose shape-level access, the loader will fallback to `python-pptx` for image extraction on slides where images are detected, then merge the image descriptions with the markitdown text output.

### Component Diagram

```
PowerPointLoader (pptx backend)
    │
    ├─ shape_type == PICTURE ──→ extract image bytes
    │                                │
    │                                ▼
    │                      GoogleGenAIClient.image_understanding()
    │                                │
    │                                ▼
    │                      AIMessage (text + summary)
    │                                │
    ├─ slide text ◄──────── merge ◄──┘
    │
    ▼
  Document (enriched with image descriptions)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PowerPointLoader` | modifies | Add image extraction + AI description pipeline |
| `GoogleGenAIClient` | uses | Call `image_understanding()` for each detected image |
| `python-pptx` | uses | Extract image blobs from Picture shapes |
| `AbstractLoader` | inherits (no change) | No changes to base class |

### Data Models

```python
# No new Pydantic models needed — uses existing Document and AIMessage.
# Image bytes are passed directly to image_understanding() as bytes.
```

### New Public Interfaces

```python
class PowerPointLoader(AbstractLoader):
    def __init__(
        self,
        source=None,
        *,
        # ... existing params ...

        # New parameters for image parsing
        parse_images: bool = False,
        image_client: Optional["GoogleGenAIClient"] = None,
        image_model: Optional[str] = None,  # Override model for image_understanding
        image_prompt: Optional[str] = None,  # Custom prompt for image analysis
        max_images_per_slide: int = 5,       # Limit images processed per slide
        **kwargs
    ):
        ...

    async def _extract_images_from_slide(
        self, slide
    ) -> List[bytes]:
        """Extract image bytes from all PICTURE shapes in a slide."""
        ...

    async def _describe_images(
        self, images: List[bytes]
    ) -> List[str]:
        """Send images to GoogleGenAIClient.image_understanding() and return descriptions."""
        ...
```

---

## 3. Module Breakdown

### Module 1: Image Extraction from Slides

- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/ppt.py`
- **Responsibility**: Extract image bytes from `python-pptx` slide shapes (shape_type == 13 / PICTURE). Provide helper method `_extract_images_from_slide(slide) -> List[bytes]`.
- **Depends on**: `python-pptx` (already a dependency)

### Module 2: Image Description via GoogleGenAIClient

- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/ppt.py`
- **Responsibility**: Call `GoogleGenAIClient.image_understanding()` for each extracted image with a structured prompt that requests: (1) markdown text extraction with layout, (2) content summary/explanation. Return combined description strings.
- **Depends on**: Module 1, `GoogleGenAIClient` from `parrot.clients.google`

### Module 3: Integration into Slide Processing Pipeline

- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/ppt.py`
- **Responsibility**: Wire image extraction + description into both `_process_pptx_content()` and `_load()`. For markitdown backend, use pptx as a secondary pass for image extraction only. Merge image descriptions into slide content (markdown `## Images` section). Update constructor with new parameters.
- **Depends on**: Module 1, Module 2

### Module 4: Tests

- **Path**: `tests/test_powerpoint_image_parsing.py`
- **Responsibility**: Unit and integration tests for image extraction, mocked image_understanding calls, and end-to-end loading with images.
- **Depends on**: Module 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_extract_images_from_slide` | Module 1 | Extracts image bytes from a slide with PICTURE shapes |
| `test_extract_images_empty_slide` | Module 1 | Returns empty list for slides without images |
| `test_describe_images_returns_markdown` | Module 2 | Mocked GoogleGenAIClient returns markdown description |
| `test_describe_images_handles_error` | Module 2 | Gracefully handles API errors without breaking slide processing |
| `test_max_images_per_slide_limit` | Module 2 | Respects `max_images_per_slide` parameter |
| `test_parse_images_false_skips_extraction` | Module 3 | When `parse_images=False`, no image processing occurs |
| `test_parse_images_true_enriches_content` | Module 3 | When `parse_images=True`, slide documents include image descriptions |
| `test_image_description_in_metadata` | Module 3 | Image count and processing metadata included in document metadata |

### Integration Tests

| Test | Description |
|---|---|
| `test_load_pptx_with_images_pptx_backend` | Full pipeline with pptx backend, parse_images=True |
| `test_load_pptx_with_images_markitdown_backend` | Full pipeline with markitdown backend, image extraction fallback to pptx |
| `test_image_only_slides_with_parse_images` | Previously skipped image-only slides now produce documents with descriptions |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_pptx_with_images(tmp_path):
    """Create a minimal PPTX file with text and image slides."""
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    # Slide 1: text only
    slide1 = prs.slides.add_slide(prs.slide_layouts[1])
    slide1.shapes.title.text = "Text Slide"
    # Slide 2: text + image
    slide2 = prs.slides.add_slide(prs.slide_layouts[5])
    # Add a small test image
    ...
    path = tmp_path / "test.pptx"
    prs.save(str(path))
    return path

@pytest.fixture
def mock_google_client():
    """Mocked GoogleGenAIClient with image_understanding returning test descriptions."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `PowerPointLoader(parse_images=True, image_client=client)` extracts images from slides
- [ ] Each extracted image is sent to `GoogleGenAIClient.image_understanding()`
- [ ] Image descriptions (markdown text + summary) are appended to slide Document content
- [ ] Image-only slides (previously skipped) produce Documents when `parse_images=True`
- [ ] `parse_images=False` (default) preserves existing behavior exactly
- [ ] `max_images_per_slide` limits the number of images processed per slide
- [ ] Errors from `image_understanding()` are logged and do not break slide processing
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] No breaking changes to existing `PowerPointLoader` public API

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use async throughout — `_describe_images()` must be async since `image_understanding()` is async.
- The `_load()` method is already async, so integration is natural.
- Pass image bytes directly to `image_understanding()` (it accepts `bytes` via PIL conversion).
- Use `self.logger` for all logging.
- Follow the existing fallback pattern: if image processing fails, log warning and continue with text-only content.

### Image Extraction from python-pptx

```python
# python-pptx provides image blobs via:
shape.image.blob  # bytes of the image file
shape.image.content_type  # e.g., "image/png"
```

### Prompt Strategy for image_understanding

```python
IMAGE_ANALYSIS_PROMPT = (
    "Analyze this image from a PowerPoint slide. Provide:\n"
    "1. **Text Extraction**: Extract all visible text preserving layout in markdown format "
    "(tables as markdown tables, lists as markdown lists, headings as markdown headings).\n"
    "2. **Content Summary**: A concise explanation of what the image shows "
    "(diagram description, chart data interpretation, photo description, etc.)."
)
```

### Known Risks / Gotchas

- **API Cost**: Each image triggers a Google GenAI API call. Users should be aware of cost implications when processing large presentations. The `max_images_per_slide` parameter provides a safety valve.
- **Latency**: Image understanding adds significant latency per slide. Consider processing images concurrently within a slide using `asyncio.gather()`.
- **Image Size**: Some PPTX images can be very large. The `image_understanding()` method already handles large files (>5MB) via upload API.
- **MarkItDown Backend**: MarkItDown doesn't expose shape-level info, so image extraction always requires `python-pptx` as a secondary dependency when `parse_images=True`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `python-pptx` | `>=0.6.21` | Image extraction from PICTURE shapes (required when `parse_images=True`) |
| `google-genai` | existing | GoogleGenAIClient dependency (already in project) |
| `Pillow` | existing | Image byte conversion (already in project) |

---

## 7. Open Questions

- [ ] Should we cache image descriptions to avoid re-processing the same presentation? — *Owner: Jesus Lara*
- [ ] Should we support passing a custom prompt per-image or per-slide for domain-specific extraction? — *Owner: Jesus Lara*
- [ ] Should the `markitdown` backend require `python-pptx` as a hard dependency when `parse_images=True`, or should we raise a clear error? — *Owner: Jesus Lara*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All modules modify a single file (`ppt.py`) plus one test file — no parallelization benefit.
- **Cross-feature dependencies**: None. This feature is self-contained within `PowerPointLoader`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-31 | Jesus Lara | Initial draft |
