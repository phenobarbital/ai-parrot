# TASK-639: PowerPointLoader Full-Document Mode

**Feature**: loader-failed-chunking
**Spec**: `sdd/specs/loader-failed-chunking.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-636
**Assigned-to**: unassigned

---

## Context

Module 7 from the spec. PowerPointLoader currently creates one Document per slide,
producing tiny Documents for slides with only a title, a bullet list, or an image.
When `full_document=True` (new default from TASK-636), concatenate all slide content
into a single markdown string and return 1 Document.

---

## Scope

- When `self.full_document=True` (default): concatenate all slide content into a single
  markdown string (slides separated by `\n\n---\n\n`), return 1 Document.
- Include `total_slides` in metadata.
- When `self.full_document=False`: preserve existing per-slide behavior unchanged.
- Write tests.

**NOT in scope**: PDFLoader (TASK-637), MSWordLoader (TASK-638), splitter changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/ppt.py` | MODIFY | Add full_document mode |
| `tests/loaders/test_ppt_loader_chunking.py` | CREATE | Tests for full_document mode |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader   # ppt.py:7
from parrot.stores.models import Document            # ppt.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/ppt.py
class PowerPointLoader(AbstractLoader):                              # line 26
    extensions: List[str] = ['.pptx', '.ppt']                       # line 43

    def __init__(self, source=None, *, tokenizer=None, text_splitter=None,
                 source_type='file', backend="auto",
                 output_format="markdown", skip_image_only_slides=True,
                 skip_empty_slides=True, extract_slide_notes=True,
                 preserve_slide_structure=True,
                 min_slide_content_length=10, ...):                  # line 45-73
        # After TASK-636: self.full_document inherited from AbstractLoader

    async def _load(self, path, **kwargs) -> List[Document]:         # line 344
        # line 358-366: try primary backend (markitdown or pptx)
        # line 372-451: for slide_data in slides_data:
        #   Creates one Document per slide
        #   Content formatted via _format_slide_as_markdown() or plain text
        #   Metadata includes slide_number, slide_title, etc.

    def _process_markitdown_content(self, path) -> List[dict]:       # line 195
        # Returns list of slide dicts with: slide_number, title, content, full_content

    def _process_pptx_content(self, path) -> List[dict]:             # line 296
        # Returns list of slide dicts with: slide_number, slide_id, title, content, notes

    def _format_slide_as_markdown(self, slide_data, slide_text, slide_notes="") -> str:  # line 259
    def _clean_content(self, content: str) -> str:                   # line 129

    def create_document(self, content, path, metadata=None, **kwargs):  # inherited
    def create_metadata(self, path, doctype, source_type, doc_metadata):  # inherited
```

### Does NOT Exist
- ~~`PowerPointLoader.full_document`~~ — not a parameter on PowerPointLoader itself (inherited from AbstractLoader after TASK-636)
- ~~`PowerPointLoader._load_full_document()`~~ — no such method
- ~~`PowerPointLoader.concatenate_slides()`~~ — no such method

---

## Implementation Notes

### Changes to `_load()` (line 344):

Add a `full_document` path before the per-slide loop:

```python
async def _load(self, path, **kwargs) -> List[Document]:
    self.logger.info(f"Loading PowerPoint file: {path}")
    docs = []

    # Extract slides using backend
    if self.backend == "markitdown":
        slides_data = self._process_markitdown_content(path)
        if not slides_data and PPTX_AVAILABLE:
            slides_data = self._process_pptx_content(path)
    else:
        slides_data = self._process_pptx_content(path)

    if not slides_data:
        self.logger.warning(f"No slides extracted from {path}")
        return docs

    # Full-document mode: concatenate all slides into one Document
    if self.full_document:
        all_content_parts = []
        for slide_data in slides_data:
            # Format each slide as markdown
            if self.output_format == "markdown":
                content = self._format_slide_as_markdown(
                    slide_data,
                    slide_data.get("content", ""),
                    slide_data.get("notes", "")
                )
            else:
                parts = []
                if slide_data.get("title"):
                    parts.append(f"Title: {slide_data['title']}")
                if slide_data.get("content"):
                    parts.append(slide_data["content"])
                content = "\n\n".join(parts)

            content = self._clean_content(content)
            if content:
                all_content_parts.append(content)

        full_content = "\n\n---\n\n".join(all_content_parts)

        metadata = self.create_metadata(
            path=path,
            doctype="pptx",
            source_type="powerpoint",
            doc_metadata={
                "total_slides": len(slides_data),
                "extraction_backend": self.backend,
                "output_format": self.output_format,
                "content_type": "full_document",
            },
        )
        docs.append(self.create_document(content=full_content, path=path, metadata=metadata))
        return docs

    # Existing per-slide behavior (unchanged)
    for slide_data in slides_data:
        # ... existing code ...
```

### Key Constraints
- Reuse `_format_slide_as_markdown()` for each slide's content in full-doc mode.
- Use `\n\n---\n\n` as slide separator (horizontal rule in markdown).
- `_clean_content()` should be applied per-slide before concatenation.
- Skip the `preserve_slide_structure` context header in full-doc mode (it would
  add per-slide file/type headers that clutter the full document).

---

## Acceptance Criteria

- [ ] `full_document=True` (default): returns 1 Document per file
- [ ] Metadata includes `total_slides`
- [ ] Slides separated by `\n\n---\n\n` in the concatenated content
- [ ] `full_document=False`: preserves existing per-slide behavior
- [ ] Both markitdown and pptx backends work in full_document mode
- [ ] All tests pass: `pytest tests/loaders/test_ppt_loader_chunking.py -v`

---

## Test Specification

```python
# tests/loaders/test_ppt_loader_chunking.py
import pytest
from parrot_loaders.ppt import PowerPointLoader


class TestPowerPointLoaderFullDocument:
    @pytest.mark.asyncio
    async def test_full_document_returns_single_doc(self):
        """full_document=True returns 1 Document per PPTX file."""
        pass

    @pytest.mark.asyncio
    async def test_full_document_false_returns_per_slide(self):
        """full_document=False preserves per-slide behavior."""
        pass

    @pytest.mark.asyncio
    async def test_metadata_includes_total_slides(self):
        """Document metadata includes total_slides field."""
        pass

    @pytest.mark.asyncio
    async def test_slides_separated_by_hr(self):
        """Slides in full document are separated by horizontal rules."""
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/loader-failed-chunking.spec.md` for full context
2. **Check dependencies** — TASK-636 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — read `ppt.py` lines 344-454 carefully
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the changes
6. **Run tests**: `pytest tests/loaders/test_ppt_loader_chunking.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
