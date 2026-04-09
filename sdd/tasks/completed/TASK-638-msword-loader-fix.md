# TASK-638: MSWordLoader Fix Double-Chunking Bug

**Feature**: loader-failed-chunking
**Spec**: `sdd/specs/loader-failed-chunking.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-636
**Assigned-to**: unassigned

---

## Context

Module 6 from the spec. MSWordLoader has a critical **double-chunking** bug: `_load()`
at line 104 calls `self.markdown_splitter.split_text(md_text)` and creates one Document
per chunk. Then when `load()` calls `chunk_documents()`, these already-small chunks get
fragmented **again**, producing the 10-20 word fragments reported by users.

The fix is simple: remove the internal chunking in `_load()` and return a single Document
with the full markdown content. Let the standard `chunk_documents()` pipeline handle all splitting.

---

## Scope

- Remove the for-loop at docx.py:104 that calls `self.markdown_splitter.split_text(md_text)`.
- Instead, return a single Document containing the full markdown content.
- Preserve document metadata (author, version, title).
- Preserve the document context header.
- Write tests verifying no double-chunking occurs.

**NOT in scope**: PDFLoader (TASK-637), PowerPointLoader (TASK-639), splitter changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` | MODIFY | Remove internal chunking, return single Document |
| `tests/loaders/test_docx_loader_fix.py` | CREATE | Tests for the fix |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader   # docx.py:8
from parrot.stores.models import Document            # docx.py:7
import docx                                          # docx.py:4
from markdownify import markdownify as md            # docx.py:6
import mammoth                                       # docx.py:4
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/docx.py
class MSWordLoader(AbstractLoader):                                  # line 11
    extensions: List[str] = ['.doc', '.docx']                        # line 15

    def docx_to_markdown(self, docx_path) -> str:                    # line 17
        # Converts DOCX to markdown preserving structure
        # Returns markdown_text string

    async def _load(self, path: PurePath, **kwargs) -> List[Document]:  # line 70
        # line 83: doc = docx.Document(str(path))
        # line 84: properties = doc.core_properties
        # line 85: md_text = self.docx_to_markdown(path)
        # line 86-96: metadata creation (author, version, title)
        # line 98-101: document_context header string
        # >>> BUG starts at line 104: <<<
        # line 104: for chunk in self.markdown_splitter.split_text(md_text):
        # line 105-115: creates one Document per chunk
        # This loop must be replaced with a single create_document() call.

    def create_document(self, content, path, metadata=None, **kwargs):  # inherited from AbstractLoader
    def create_metadata(self, path, doctype, source_type, doc_metadata):  # inherited from AbstractLoader
```

### Does NOT Exist
- ~~`MSWordLoader.full_document`~~ — no such parameter (the fix is removing internal chunking entirely)
- ~~`MSWordLoader._split_content()`~~ — no such method

---

## Implementation Notes

### The Fix

Replace the for-loop at line 104-115 with a single Document creation:

```python
# BEFORE (lines 104-115):
for chunk in self.markdown_splitter.split_text(md_text):
    _idx = {
        **metadata
    }
    doc = self.create_document(
        content=document_context + chunk,
        path=path,
        metadata=_idx
    )
    docs.append(doc)

# AFTER:
docs.append(
    self.create_document(
        content=document_context + md_text,
        path=path,
        metadata=metadata
    )
)
```

That's it. The standard `chunk_documents()` pipeline (called by `load()`) handles
all splitting with the new SemanticTextSplitter.

### Key Constraints
- Keep the `document_context` header prepended to content.
- Keep all metadata fields (author, version, title).
- Do NOT remove `docx_to_markdown()` — it's still used to extract the content.
- The `markdown_splitter` attribute still exists on the loader — just don't call it in `_load()`.

---

## Acceptance Criteria

- [ ] `MSWordLoader._load()` returns exactly 1 Document per file (not per-chunk)
- [ ] Document contains full markdown content from `docx_to_markdown()`
- [ ] Metadata includes author, version, title
- [ ] Document context header is preserved
- [ ] No reference to `self.markdown_splitter.split_text()` in `_load()`
- [ ] All tests pass: `pytest tests/loaders/test_docx_loader_fix.py -v`

---

## Test Specification

```python
# tests/loaders/test_docx_loader_fix.py
import pytest
from parrot_loaders.docx import MSWordLoader


class TestMSWordLoaderFix:
    @pytest.mark.asyncio
    async def test_load_returns_single_document(self, tmp_path):
        """_load() returns 1 Document, not pre-chunked Documents."""
        # Create a minimal .docx test file
        pass

    @pytest.mark.asyncio
    async def test_no_double_chunking(self, tmp_path):
        """Content is not split inside _load() — chunking happens only in chunk_documents()."""
        pass

    @pytest.mark.asyncio
    async def test_metadata_preserved(self, tmp_path):
        """Document metadata includes author, version, title."""
        pass

    @pytest.mark.asyncio
    async def test_document_context_header(self, tmp_path):
        """Document content starts with context header."""
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/loader-failed-chunking.spec.md` for full context
2. **Check dependencies** — TASK-636 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — read `docx.py` lines 70-116 carefully
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the fix (remove the for-loop, add single create_document call)
6. **Run tests**: `pytest tests/loaders/test_docx_loader_fix.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
