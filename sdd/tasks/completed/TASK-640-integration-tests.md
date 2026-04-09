# TASK-640: Integration Tests for Loader Chunking

**Feature**: loader-failed-chunking
**Spec**: `sdd/specs/loader-failed-chunking.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-633, TASK-634, TASK-635, TASK-636, TASK-637, TASK-638, TASK-639
**Assigned-to**: unassigned

---

## Context

Module 8 from the spec. End-to-end integration tests that verify the full pipeline:
loader → splitter → chunks. Ensures no chunks below `min_chunk_size`, all loaders
produce semantically coherent chunks, and backwards compatibility is preserved.

This task runs AFTER all other tasks are complete.

---

## Scope

- Create integration tests that load real-ish test documents through the full pipeline.
- Verify chunk size ranges (between min_chunk_size and ~chunk_size tokens).
- Verify no double-chunking occurs.
- Verify backwards compatibility with explicit `chunk_size=800`.
- Verify `full_document=False` preserves old behavior.
- Verify `split_documents=False` still returns unchunked documents.
- Create minimal test fixture files (small PDF, DOCX, PPTX, TXT).

**NOT in scope**: Unit tests for individual components (those are in TASK-633 through TASK-639).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/loaders/test_loader_chunking_integration.py` | CREATE | Integration tests |
| `tests/loaders/fixtures/` | CREATE | Minimal test fixture files |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_loaders.pdf import PDFLoader             # pdf.py:10
from parrot_loaders.docx import MSWordLoader         # docx.py:11
from parrot_loaders.ppt import PowerPointLoader      # ppt.py:26
from parrot_loaders.txt import TextLoader            # txt.py:7
from parrot_loaders.splitters.semantic import SemanticTextSplitter  # (after TASK-635)
from parrot.loaders.abstract import AbstractLoader   # abstract.py:35
from parrot.stores.models import Document            # (used by all loaders)
```

### Existing Signatures to Use
```python
# AbstractLoader.load() — the main entry point
async def load(
    self,
    source=None,
    split_documents: bool = True,
    late_chunking: bool = False,
    vector_store=None,
    store_full_document: bool = True,
    auto_detect_content_type=None,
    **kwargs
) -> List[Document]:                                  # abstract.py:560

# After all tasks complete:
# AbstractLoader.__init__ defaults:
#   chunk_size=2048, chunk_overlap=200, min_chunk_size=50, full_document=True
```

### Does NOT Exist
- ~~`AbstractLoader.load_and_chunk()`~~ — no such method (use `load()` with `split_documents=True`)
- ~~`Document.token_count`~~ — not a direct attribute of Document (it's in chunk metadata)

---

## Implementation Notes

### Test Strategy

Use `python-docx`, `fitz` (PyMuPDF), and `python-pptx` to create minimal test files
programmatically in fixtures. This avoids committing binary files to the repo.

```python
@pytest.fixture
def sample_pdf(tmp_path):
    """Create a minimal PDF with multiple pages."""
    import fitz
    doc = fitz.open()
    for i, text in enumerate([
        "Title Page: Annual Report 2025",
        "Chapter 1: Introduction\n\nThis is the first chapter with enough content...",
        "Chapter 2: Analysis\n\nDetailed analysis of the market conditions...",
    ]):
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
    path = tmp_path / "test.pdf"
    doc.save(str(path))
    doc.close()
    return path
```

### Key Test Cases

1. **No tiny chunks**: Load a multi-page PDF with `split_documents=True`.
   Assert every chunk has >= `min_chunk_size` tokens (except possibly the last one
   if the total content is very small).

2. **No double-chunking for DOCX**: Load a DOCX, count Documents from `_load()` —
   should be 1 (not N chunks).

3. **Backwards compatibility**: `PDFLoader(source=..., chunk_size=800)` still works,
   produces chunks of ~800 tokens.

4. **No chunking**: `loader.load(split_documents=False)` returns unchunked docs.

5. **Full-document=False**: `PDFLoader(source=..., full_document=False)` produces
   per-page documents (old behavior).

### Key Constraints
- Tests must be fast (< 10 seconds total).
- Use programmatically created fixtures, not committed binary files.
- Tests should not require tiktoken model downloads at test time (tiktoken
  caches encodings, but CI may not have them).

---

## Acceptance Criteria

- [ ] Integration test for PDF full pipeline: load → chunk → verify size range
- [ ] Integration test for DOCX: verify no double-chunking
- [ ] Integration test for TXT: verify paragraph-level chunks
- [ ] Test for backwards compatibility with explicit `chunk_size=800`
- [ ] Test for `split_documents=False` returning unchunked documents
- [ ] Test for `full_document=False` preserving old behavior
- [ ] All tests pass: `pytest tests/loaders/test_loader_chunking_integration.py -v`
- [ ] Tests complete in < 10 seconds

---

## Test Specification

```python
# tests/loaders/test_loader_chunking_integration.py
import pytest
from parrot_loaders.pdf import PDFLoader
from parrot_loaders.txt import TextLoader
from parrot_loaders.docx import MSWordLoader


class TestChunkingSizeRange:
    @pytest.mark.asyncio
    async def test_pdf_chunks_above_min_size(self, sample_pdf):
        """All chunks from PDF have >= min_chunk_size tokens."""
        loader = PDFLoader(source=sample_pdf)
        docs = await loader.load(split_documents=True)
        for doc in docs:
            if doc.metadata.get('is_chunk'):
                assert doc.metadata.get('token_count', 0) >= 50

    @pytest.mark.asyncio
    async def test_txt_chunks_are_paragraphs(self, sample_txt):
        """TXT chunks are paragraph-level, not character-level."""
        loader = TextLoader(source=sample_txt)
        docs = await loader.load(split_documents=True)
        for doc in docs:
            # Each chunk should contain at least one complete sentence
            assert '. ' in doc.page_content or doc.page_content.endswith('.')


class TestBackwardsCompatibility:
    @pytest.mark.asyncio
    async def test_explicit_chunk_size_800(self, sample_txt):
        """Passing chunk_size=800 explicitly still works."""
        loader = TextLoader(source=sample_txt, chunk_size=800)
        docs = await loader.load(split_documents=True)
        assert len(docs) >= 1

    @pytest.mark.asyncio
    async def test_no_chunking(self, sample_txt):
        """split_documents=False returns unchunked documents."""
        loader = TextLoader(source=sample_txt)
        docs = await loader.load(split_documents=False)
        for doc in docs:
            assert not doc.metadata.get('is_chunk', False)


class TestFullDocumentMode:
    @pytest.mark.asyncio
    async def test_full_document_false_per_page(self, sample_pdf):
        """full_document=False returns per-page documents."""
        loader = PDFLoader(source=sample_pdf, full_document=False)
        docs = await loader.load(split_documents=False)
        assert len(docs) > 1  # Multiple pages = multiple docs
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/loader-failed-chunking.spec.md` for full context
2. **Check dependencies** — ALL tasks TASK-633 through TASK-639 must be in `tasks/completed/`
3. **Create test fixtures** programmatically (no binary files)
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** integration tests
6. **Run tests**: `pytest tests/loaders/test_loader_chunking_integration.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
