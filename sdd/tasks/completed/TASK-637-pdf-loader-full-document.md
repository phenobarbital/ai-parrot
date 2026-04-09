# TASK-637: PDFLoader Full-Document Mode

**Feature**: loader-failed-chunking
**Spec**: `sdd/specs/loader-failed-chunking.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-636
**Assigned-to**: unassigned

---

## Context

Module 5 from the spec. PDFLoader currently creates one Document per page (without
`as_markdown`), producing tiny Documents for title pages, image captions, and short
content pages. These get fragmented further by chunking.

When `full_document=True` (new default from TASK-636), PDFLoader should extract the
entire PDF as a single markdown string using `pymupdf4llm.to_markdown()` and return
1 Document. Per resolved open question: chunk metadata must include **per-chunk page
ranges** (e.g., `"pages": [3, 4, 5]`).

---

## Scope

- When `self.full_document=True` (default): use `pymupdf4llm.to_markdown(path)` to
  extract the entire PDF as a single markdown string. Return 1 Document.
- Include `total_pages` in the Document metadata.
- When `self.full_document=False`: preserve existing per-page behavior unchanged.
- `use_chapters=True` or `use_pages=True` override `full_document` (they imply
  their own splitting logic).
- Ensure the summarization step still works with full_document mode.
- Write tests.

**NOT in scope**: SemanticTextSplitter (TASK-635), MSWordLoader (TASK-638),
PowerPointLoader (TASK-639), per-chunk page ranges in the splitter (the splitter
doesn't know about pages — page metadata enrichment can be a follow-up).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/pdf.py` | MODIFY | Add full_document mode |
| `tests/loaders/test_pdf_loader_chunking.py` | CREATE | Tests for full_document mode |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader   # pdf.py:8
from parrot.stores.models import Document            # pdf.py:7
import fitz                                          # pdf.py:5
import pymupdf4llm                                   # pdf.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/pdf.py
class PDFLoader(AbstractLoader):                                     # line 10
    extensions: List[str] = {'.pdf'}                                 # line 20

    def __init__(self, source=None, *, tokenizer=None, text_splitter=None,
                 source_type='file', as_markdown=False,
                 use_chapters=False, use_pages=False, **kwargs):     # line 22-40
        # After TASK-636: self.full_document is set by AbstractLoader.__init__()

    async def _load(self, path: PurePath, **kwargs) -> List[Document]:  # line 213
        # as_markdown=True path (line 218-297):
        #   line 219: md_text = pymupdf4llm.to_markdown(path)
        #   line 220-246: use_chapters → per-chapter Documents
        #   line 247-277: use_pages → per-page Documents
        #   line 278-297: else → single Document (THIS is the behavior we want as default)
        # Default path (line 298-353):
        #   Per-page iteration: for i, page in enumerate(doc)
        #   Creates one Document per page
        # Summarization (line 354-372):
        #   full_text = "\n\n".join(all_text)
        #   summary = await self.summary_from_text(full_text)

    def create_document(self, content, path, metadata=None, **kwargs):  # inherited from AbstractLoader
    def create_metadata(self, path, doctype, source_type, doc_metadata):  # inherited from AbstractLoader
```

### Does NOT Exist
- ~~`PDFLoader.full_document`~~ — not a parameter on PDFLoader itself (inherited from AbstractLoader after TASK-636)
- ~~`PDFLoader._load_full_document()`~~ — no such method
- ~~`pymupdf4llm.to_markdown(path, pages=...)`~~ — verify actual API; may not support page selection

---

## Implementation Notes

### Changes to `_load()` (line 213):

The key insight: the `as_markdown=True` path already has the exact behavior we want
when neither `use_chapters` nor `use_pages` is set (lines 278-297 — returns single Document).

**Strategy**: When `self.full_document=True`, use the markdown path regardless of `as_markdown`:

```python
async def _load(self, path: PurePath, **kwargs) -> List[Document]:
    self.logger.info(f"Loading PDF file: {path}")
    docs = []
    doc = fitz.open(str(path))
    total_pages = len(doc)

    # Full-document mode: use pymupdf4llm for single-document extraction
    if self.full_document and not self.use_chapters and not self.use_pages:
        md_text = pymupdf4llm.to_markdown(path)
        document_meta = {
            "filename": path.name,
            "file_path": str(path),
            "total_pages": total_pages,
            "content_type": "full_document"
        }
        meta = self.create_metadata(
            path=path, doctype="pdf",
            source_type="pdf_markdown",
            doc_metadata=document_meta,
        )
        docs.append(self.create_document(content=md_text, path=path, metadata=meta))
        # Summarization
        summary = await self.summary_from_text(md_text)
        if summary:
            # ... same pattern as existing summarization code (lines 358-372)
        doc.close()
        return docs

    # Existing paths (as_markdown with chapters/pages, or per-page)
    if self.as_markdown:
        # ... existing code unchanged ...
    else:
        # ... existing per-page code unchanged ...
```

### Key Constraints
- `pymupdf4llm` must be available. If not, fall back to per-page mode with a warning.
- `use_chapters=True` or `use_pages=True` always override `full_document`.
- `self.as_markdown=True` with `full_document=True` should work the same as just
  `full_document=True` (both produce markdown via pymupdf4llm).
- `full_document=False` preserves the exact current behavior.

---

## Acceptance Criteria

- [ ] `full_document=True` (default): PDFLoader returns 1 Document per file
- [ ] Document metadata includes `total_pages`
- [ ] `full_document=False`: preserves existing per-page behavior
- [ ] `use_chapters=True` overrides `full_document`
- [ ] `use_pages=True` overrides `full_document`
- [ ] Summarization still works in full_document mode
- [ ] All tests pass: `pytest tests/loaders/test_pdf_loader_chunking.py -v`

---

## Test Specification

```python
# tests/loaders/test_pdf_loader_chunking.py
import pytest
from pathlib import Path
from parrot_loaders.pdf import PDFLoader


class TestPDFLoaderFullDocument:
    @pytest.mark.asyncio
    async def test_full_document_returns_single_doc(self, tmp_path):
        """full_document=True returns 1 Document per PDF file."""
        # This test requires a sample PDF — use a fixture or create minimal one
        pass

    @pytest.mark.asyncio
    async def test_full_document_false_returns_per_page(self, tmp_path):
        """full_document=False preserves per-page behavior."""
        pass

    @pytest.mark.asyncio
    async def test_metadata_includes_total_pages(self, tmp_path):
        """Document metadata includes total_pages field."""
        pass

    @pytest.mark.asyncio
    async def test_use_chapters_overrides_full_document(self, tmp_path):
        """use_chapters=True takes precedence over full_document=True."""
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/loader-failed-chunking.spec.md` for full context
2. **Check dependencies** — TASK-636 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — read `pdf.py` lines 213-373 carefully
4. **Verify pymupdf4llm API** — check that `pymupdf4llm.to_markdown(path)` works as expected
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** the changes
7. **Run tests**: `pytest tests/loaders/test_pdf_loader_chunking.py -v`
8. **Move this file** to `tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
