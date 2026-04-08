# Feature Specification: Fix Broken Chunking in Loaders

**Feature ID**: FEAT-092
**Date**: 2026-04-09
**Author**: Jesus Lara
**Status**: draft
**Target version**: next
**Brainstorm**: sdd/proposals/loader-failed-chunking.brainstorm.md

---

## 1. Motivation & Business Requirements

### Problem Statement

Multiple loaders in ai-parrot-loaders produce unusable chunks when `split_documents=True`
(the default). Chunks contain as few as 10-20 words, incomplete sentences, single titles,
or even blank content. This breaks the entire RAG retrieval pipeline:

- **Tiny chunks produce poor embeddings** — a 10-word vector has almost no semantic signal.
- **Context is destroyed** — paragraphs are split mid-sentence.
- **Modern LLMs are underutilized** — models handle 128K+ tokens; chunking at 800 characters
  (~150 words) is unnecessarily aggressive.

**Root causes** (from brainstorm analysis):

| # | Bug | Location | Effect |
|---|-----|----------|--------|
| 1 | MarkdownTextSplitter uses `len()` (chars) not `_count_tokens()` | md.py:142-210 | chunk_size=800 means 800 *chars* (~150 words) |
| 2 | Loaders create per-page/per-slide Documents before chunking | pdf.py:298+, ppt.py:344+, docx.py:104 | Small pages become standalone tiny Documents |
| 3 | MSWordLoader does **double chunking** — splits inside `_load()` then again in `chunk_documents()` | docx.py:104 | Already-small chunks get fragmented again |
| 4 | AbstractLoader defaults chunk_size=800 | abstract.py:62 | Too aggressive for modern LLMs |
| 5 | No minimum chunk size enforcement | base.py `create_chunks()` | 10-word fragments pass to embedding |
| 6 | Markdown detection over-eager | abstract.py:363-366 | Most content routes through broken MarkdownTextSplitter |

### Goals
- Produce complete, semantically coherent paragraph-level chunks by default.
- Raise default chunk_size to 2048 tokens (configurable).
- Never produce chunks below a configurable minimum (default: 50 tokens).
- Fix loaders to produce full-document content, not per-page fragments.
- Maintain backwards compatibility with existing API.

### Non-Goals (explicitly out of scope)
- Rewriting the `LateChunkingProcessor` — it already works reasonably well.
- Adding LangChain or spaCy dependencies.
- Changing the embedding model or PgVector schema.
- Rewriting loaders from scratch — targeted fixes to `_load()` methods only.
- Fixing ExcelLoader chunking — per-row documents are logical units for spreadsheets.

---

## 2. Architectural Design

### Overview

Two-sided fix: (1) new `SemanticTextSplitter` that chunks by paragraph/sentence boundaries
using token-based sizing, and (2) loader modifications to produce full-document content instead
of per-page fragments.

### Component Diagram
```
                              ┌─────────────────────────┐
                              │    AbstractLoader        │
                              │  chunk_size=2048 (new)   │
                              │  min_chunk_size=50 (new) │
                              └───────────┬─────────────┘
                                          │
              ┌───────────────────────────┼────────────────────────────┐
              ▼                           ▼                            ▼
   ┌──────────────────┐     ┌──────────────────────┐    ┌──────────────────────┐
   │   PDFLoader      │     │   MSWordLoader       │    │  PowerPointLoader    │
   │  full_document   │     │  fix double-chunk    │    │  full_document       │
   │  =True (default) │     │  return 1 Document   │    │  =True (default)     │
   └────────┬─────────┘     └──────────┬───────────┘    └──────────┬───────────┘
            │                          │                            │
            └──────────────────────────┼────────────────────────────┘
                                       ▼
                        ┌──────────────────────────────┐
                        │  _chunk_with_text_splitter()  │
                        │  (existing orchestration)     │
                        └──────────────┬───────────────┘
                                       ▼
                ┌──────────────────────────────────────────┐
                │         SemanticTextSplitter (NEW)       │
                │  1. Split on \n\n (paragraphs)           │
                │  2. Measure tokens via tiktoken           │
                │  3. Merge small paragraphs to chunk_size  │
                │  4. Split oversized paragraphs at         │
                │     sentence boundaries                   │
                │  5. Enforce min_chunk_size                 │
                └──────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BaseTextSplitter` | extends | New `SemanticTextSplitter` inherits from it |
| `BaseTextSplitter` | modifies | Add `min_chunk_size`, default `_count_tokens()` |
| `AbstractLoader` | modifies | New defaults, splitter selection, `min_chunk_size` param |
| `PDFLoader._load()` | modifies | Add `full_document` mode (default True) |
| `MSWordLoader._load()` | modifies | Remove internal chunking, return full document |
| `PowerPointLoader._load()` | modifies | Add `full_document` mode (default True) |
| `_select_splitter_for_content()` | modifies | Route default to SemanticTextSplitter |
| `splitters/__init__.py` | modifies | Export SemanticTextSplitter |

### Data Models

No new Pydantic models. The existing `TextChunk` dataclass and `Document` model remain unchanged.

### New Public Interfaces

```python
# packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py
class SemanticTextSplitter(BaseTextSplitter):
    """
    Paragraph-aware text splitter using token-based sizing.

    Splits on paragraph boundaries (\n\n), measures in tokens (tiktoken),
    merges small paragraphs, splits oversized ones at sentence boundaries.
    Never produces chunks below min_chunk_size tokens.
    """
    def __init__(
        self,
        chunk_size: int = 2048,
        chunk_overlap: int = 200,
        min_chunk_size: int = 50,
        model_name: str = "gpt-4",
        encoding_name: Optional[str] = None,
        sentence_endings: Optional[str] = None,  # regex pattern
        preserve_code_blocks: bool = True,
        preserve_tables: bool = True,
        **kwargs
    ): ...

    def split_text(self, text: str) -> List[str]: ...
    def _count_tokens(self, text: str) -> int: ...
```

---

## 3. Module Breakdown

### Module 1: BaseTextSplitter Enhancements
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py`
- **Responsibility**:
  - Add `min_chunk_size: int = 0` parameter to `__init__`.
  - Provide default `_count_tokens()` implementation (word-based estimate) so it's no longer
    abstract. Subclasses can still override with tiktoken.
  - Modify `create_chunks()` to merge undersized final chunks with the previous chunk.
- **Depends on**: none (foundation change)

### Module 2: SemanticTextSplitter
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py`
- **Responsibility**:
  - New class inheriting `BaseTextSplitter`.
  - `split_text()` implements: paragraph split → token measurement → merge small →
    split oversized at sentence boundaries → enforce min_chunk_size.
  - `_count_tokens()` uses tiktoken (same setup as `TokenTextSplitter`).
  - Preserves code blocks (``` ... ```) and tables as atomic units.
  - Sentence detection: regex-based, CJK-aware (`[.!?。！？]\s+`).
- **Depends on**: Module 1 (BaseTextSplitter.min_chunk_size)

### Module 3: Splitter Package Exports
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/splitters/__init__.py`
- **Responsibility**: Export `SemanticTextSplitter`.
- **Depends on**: Module 2

### Module 4: AbstractLoader Defaults & Wiring
- **Path**: `packages/ai-parrot/src/parrot/loaders/abstract.py`
- **Responsibility**:
  - Change `chunk_size` default from 800 to 2048.
  - Add `min_chunk_size` parameter (default: 50).
  - Add `full_document` parameter (default: True).
  - Modify `_setup_text_splitters()` to use `SemanticTextSplitter` as default
    (when `_use_markdown_splitter=True` is NOT explicitly set).
  - Modify `_select_splitter_for_content()`: default content type routes to
    `SemanticTextSplitter`; markdown-detected content also uses `SemanticTextSplitter`
    (since paragraphs are universal); code content keeps `TokenTextSplitter`.
  - Pass `min_chunk_size` through to splitter constructors.
- **Depends on**: Module 2 (SemanticTextSplitter must exist)

### Module 5: PDFLoader Full-Document Mode
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/pdf.py`
- **Responsibility**:
  - When `full_document=True` (new default): use `pymupdf4llm.to_markdown(path)` to extract
    the entire PDF as a single markdown string, return 1 Document.
  - Page numbers stored in metadata as a range: `{"pages": total_pages}`.
  - When `full_document=False`: preserve existing per-page behavior.
  - The `as_markdown=True` path already returns a single document (line 278-297) —
    make this the default flow for `full_document=True`.
  - Keep `use_chapters` and `use_pages` flags working (they imply `full_document=False`
    semantics since they split within the markdown).
- **Depends on**: Module 4 (AbstractLoader.full_document parameter)

### Module 6: MSWordLoader Fix
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/docx.py`
- **Responsibility**:
  - **Remove the internal chunking loop** at line 104 that calls
    `self.markdown_splitter.split_text(md_text)` and creates per-chunk Documents.
    This causes double-chunking when `chunk_documents()` runs afterward.
  - Instead: return a single Document with the full markdown content.
  - Let `chunk_documents()` in the standard pipeline handle all splitting.
- **Depends on**: Module 4

### Module 7: PowerPointLoader Full-Document Mode
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/ppt.py`
- **Responsibility**:
  - When `full_document=True` (new default): concatenate all slide content into a single
    markdown string (slides separated by `\n\n---\n\n`), return 1 Document.
  - Slide numbers preserved in metadata.
  - When `full_document=False`: preserve existing per-slide behavior.
- **Depends on**: Module 4

### Module 8: Unit & Integration Tests
- **Path**: `tests/loaders/test_semantic_splitter.py`, `tests/loaders/test_loader_chunking.py`
- **Responsibility**:
  - Unit tests for SemanticTextSplitter: paragraph splitting, sentence splitting,
    min_chunk_size enforcement, code block preservation, CJK text, empty input.
  - Integration tests: PDFLoader, MSWordLoader, PowerPointLoader with full_document mode
    produce chunks of expected size range.
  - Regression tests: verify no chunks below min_chunk_size are produced.
  - Test that `full_document=False` preserves old behavior.
- **Depends on**: Modules 1-7

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_semantic_split_paragraphs` | Module 2 | Text with `\n\n` produces paragraph-level chunks |
| `test_semantic_merge_small_paragraphs` | Module 2 | Consecutive small paragraphs merged to reach chunk_size |
| `test_semantic_split_oversized_paragraph` | Module 2 | Single large paragraph split at sentence boundaries |
| `test_semantic_min_chunk_size` | Module 2 | No chunk below min_chunk_size is produced |
| `test_semantic_code_block_preserved` | Module 2 | Code blocks never split mid-block |
| `test_semantic_table_preserved` | Module 2 | Markdown tables kept as atomic units |
| `test_semantic_cjk_sentences` | Module 2 | CJK punctuation recognized for sentence splitting |
| `test_semantic_empty_input` | Module 2 | Empty string returns empty list |
| `test_semantic_single_short_text` | Module 2 | Text below min_chunk_size returned as single chunk |
| `test_semantic_token_counting` | Module 2 | Token count uses tiktoken, not character length |
| `test_base_min_chunk_merge` | Module 1 | create_chunks() merges undersized final chunk |
| `test_base_default_count_tokens` | Module 1 | Default _count_tokens() provides reasonable estimate |
| `test_docx_no_double_chunking` | Module 6 | MSWordLoader._load() returns 1 Document, not pre-chunked |
| `test_pdf_full_document_mode` | Module 5 | PDFLoader with full_document=True returns 1 Document per file |
| `test_pdf_legacy_per_page` | Module 5 | PDFLoader with full_document=False returns per-page Documents |
| `test_ppt_full_document_mode` | Module 7 | PowerPointLoader concatenates all slides into 1 Document |
| `test_abstract_loader_new_defaults` | Module 4 | Default chunk_size=2048, min_chunk_size=50 |

### Integration Tests

| Test | Description |
|---|---|
| `test_pdf_end_to_end_chunking` | Load a real PDF with split_documents=True, verify all chunks have 50+ tokens |
| `test_docx_end_to_end_chunking` | Load a real DOCX, verify no double-chunking, chunks are paragraph-level |
| `test_chunk_size_range` | Verify all chunks are between min_chunk_size and ~chunk_size tokens |
| `test_backwards_compat_explicit_chunk_size` | Passing chunk_size=800 explicitly still works |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_paragraphed_text():
    """Text with clear paragraph boundaries for semantic splitting."""
    return (
        "This is the first paragraph. It contains multiple sentences. "
        "Each sentence adds context to the topic being discussed.\n\n"
        "This is the second paragraph. It covers a different subtopic. "
        "The semantic splitter should keep each paragraph together.\n\n"
        "Short paragraph.\n\n"
        "This is a longer paragraph that goes into much more detail about "
        "the subject matter. It contains many sentences that build upon "
        "each other to form a coherent argument. The reader should be able "
        "to understand the full context without needing to read adjacent chunks."
    )

@pytest.fixture
def sample_code_block_text():
    """Text with embedded code blocks that should not be split."""
    return (
        "Here is an explanation of the code:\n\n"
        "```python\n"
        "def example_function(x: int, y: int) -> int:\n"
        "    result = x + y\n"
        "    return result\n"
        "```\n\n"
        "The function above adds two integers."
    )
```

---

## 5. Acceptance Criteria

- [ ] All unit tests pass: `pytest tests/loaders/test_semantic_splitter.py -v`
- [ ] All integration tests pass: `pytest tests/loaders/test_loader_chunking.py -v`
- [ ] No chunk produced by default configuration has fewer than 50 tokens
- [ ] PDFLoader with `full_document=True` returns 1 Document per file (not per page)
- [ ] MSWordLoader no longer double-chunks (returns 1 Document from `_load()`)
- [ ] PowerPointLoader with `full_document=True` returns 1 Document per file
- [ ] Default chunk_size is 2048 tokens
- [ ] Passing explicit `chunk_size=800` still works (backwards compatibility)
- [ ] `split_documents=False` still returns unchunked documents
- [ ] `full_document=False` preserves old per-page/per-slide behavior
- [ ] SemanticTextSplitter preserves code blocks and tables as atomic units
- [ ] No breaking changes to existing public API
- [ ] ExcelLoader behavior unchanged (per-row is correct for spreadsheets)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Carried forward from brainstorm and re-verified 2026-04-09.

### Verified Imports
```python
# These imports have been confirmed to work:
from parrot_loaders.splitters.base import BaseTextSplitter    # splitters/__init__.py:1
from parrot_loaders.splitters.md import MarkdownTextSplitter  # splitters/__init__.py:2
from parrot_loaders.splitters.token import TokenTextSplitter  # splitters/__init__.py:3
from parrot.loaders.abstract import AbstractLoader            # pdf.py:8
from parrot.stores.models import Document                     # pdf.py:7
```

### Existing Class Signatures

```python
# packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py
class BaseTextSplitter(ABC):                                         # line 19
    def __init__(self, chunk_size: int = 4000, chunk_overlap: int = 200,
                 keep_separator: bool = True, add_start_index: bool = True)  # line 22
    @abstractmethod
    def split_text(self, text: str) -> List[str]                     # line 34
    def create_chunks(self, text: str,
                      metadata: Optional[Dict[str, Any]] = None) -> List[TextChunk]  # line 39
    @abstractmethod
    def _count_tokens(self, text: str) -> int                        # line 82
    def _merge_splits(self, splits: List[str], separator: str) -> List[str]  # line 87
    def _get_overlap_splits(self, splits: List[str], separator: str) -> List[str]  # line 121

@dataclass
class TextChunk:                                                     # line 8
    text: str
    start_position: int
    end_position: int
    token_count: int
    metadata: Dict[str, Any]
    chunk_id: Optional[str] = None

# packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py
class MarkdownTextSplitter(BaseTextSplitter):                        # line 6
    def __init__(self, chunk_size: int = 4000, chunk_overlap: int = 200,
                 strip_headers: bool = False, return_each_line: bool = False)  # line 17
    def _count_tokens(self, text: str) -> int                        # line 44 — BUG: words * 1.3
    def split_text(self, text: str) -> List[str]                     # line 50
    def _parse_markdown_sections(self, text: str) -> List[Dict[str, Any]]  # line 66
    def _merge_markdown_sections(self, sections: List[Dict]) -> List[str]  # line 142 — BUG: uses len()
    def _split_large_section(self, text: str) -> List[str]           # line 187 — BUG: uses len()
    def _get_overlap_content(self, parts: List[str]) -> List[str]    # line 212 — BUG: uses len()

# packages/ai-parrot-loaders/src/parrot_loaders/splitters/token.py
class TokenTextSplitter(BaseTextSplitter):                           # line 5
    def __init__(self, chunk_size: int = 4000, chunk_overlap: int = 200,
                 model_name: str = "gpt-3.5-turbo",
                 encoding_name: Optional[str] = None,
                 tokenizer: Optional[Any] = None,
                 tokenizer_function: Optional[Callable] = None, ...)  # line 15
    def _count_tokens(self, text: str) -> int                        # line 106 — correct (tiktoken)
    def split_text(self, text: str) -> List[str]                     # line 110
    # Internal tiktoken setup:
    self._enc = tiktoken.encoding_for_model(model_name)              # line 65

# packages/ai-parrot/src/parrot/loaders/abstract.py
class AbstractLoader(ABC):                                           # line 35
    self.chunk_size: int = kwargs.get('chunk_size', 800)             # line 62
    self.chunk_overlap: int = kwargs.get('chunk_overlap', 100)       # line 63
    self.token_size: int = kwargs.get('token_size', 20)              # line 64 (legacy, purpose unclear)
    self._use_markdown_splitter: bool = kwargs.get('use_markdown_splitter', True)  # line 77
    self._use_huggingface_splitter: bool = kwargs.get('use_huggingface_splitter', False)  # line 78
    self._auto_detect_content_type: bool = kwargs.get('auto_detect_content_type', True)  # line 79
    def _get_markdown_splitter(self, chunk_size, chunk_overlap, strip_headers) -> MarkdownTextSplitter  # line 138
    def _setup_text_splitters(self, tokenizer, text_splitter, kwargs)  # line 168
    def _detect_content_type(self, document: Document) -> str        # line 331
    def _select_splitter_for_content(self, content_type: str)        # line 372
    async def load(self, source, split_documents=True, late_chunking=False, ...)  # line 560
    async def chunk_documents(self, documents, ...) -> List[Document]  # line 978
    def _chunk_with_text_splitter(self, documents, ...) -> List[Document]  # line 1008

# packages/ai-parrot-loaders/src/parrot_loaders/pdf.py
class PDFLoader(AbstractLoader):                                     # line 10
    def __init__(self, ..., as_markdown: bool = False,
                 use_chapters: bool = False, use_pages: bool = False)  # line 22
    async def _load(self, path: PurePath, **kwargs) -> List[Document]  # line 213
    # as_markdown=True path: line 218-297 (single doc when no chapters/pages)
    # Default path (per-page): line 298-353
    # Uses: pymupdf4llm.to_markdown(path) at line 219, fitz.open() at line 217

# packages/ai-parrot-loaders/src/parrot_loaders/docx.py
class MSWordLoader(AbstractLoader):                                  # line 11
    def docx_to_markdown(self, docx_path) -> str                     # line 17
    async def _load(self, path: PurePath, **kwargs) -> List[Document]  # line 70
    # BUG at line 104: self.markdown_splitter.split_text(md_text) — pre-chunks in _load()
    # Creates per-chunk Documents, then chunk_documents() may chunk AGAIN

# packages/ai-parrot-loaders/src/parrot_loaders/ppt.py
class PowerPointLoader(AbstractLoader):                              # line 26
    async def _load(self, path, **kwargs) -> List[Document]          # line 344
    # Creates per-slide Documents (line 372-451)

# packages/ai-parrot-loaders/src/parrot_loaders/excel.py
class ExcelLoader(AbstractLoader):                                   # line 11
    async def _load(self, source, **kwargs) -> List[Document]        # line 85
    # Creates per-row Documents — this is CORRECT and should NOT change

# packages/ai-parrot/src/parrot/stores/utils/chunking.py
class LateChunkingProcessor:                                         # line 20
    def __init__(self, vector_store, chunk_size: int = 8192,
                 chunk_overlap: int = 200, preserve_sentences: bool = True,
                 min_chunk_size: int = 100)                          # line 28
    def _sentence_aware_chunking(self, text: str) -> List[Tuple[str, int, int]]  # line 121
    # Sentence regex: r'[.!?]+\s+' at line 124
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SemanticTextSplitter` | `BaseTextSplitter` | inheritance | `splitters/base.py:19` |
| `SemanticTextSplitter` | tiktoken | `tiktoken.encoding_for_model()` | `splitters/token.py:65` (same pattern) |
| `AbstractLoader._setup_text_splitters()` | `SemanticTextSplitter` | constructor call | `abstract.py:168` |
| `AbstractLoader._select_splitter_for_content()` | `SemanticTextSplitter` | return instance | `abstract.py:372` |
| `PDFLoader._load()` | `pymupdf4llm.to_markdown()` | function call | `pdf.py:219` |
| `MSWordLoader._load()` | `self.docx_to_markdown()` | method call | `docx.py:85` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_loaders.splitters.semantic`~~ — module does not exist yet (to be created in Module 2)
- ~~`SemanticTextSplitter`~~ — class does not exist yet (to be created in Module 2)
- ~~`BaseTextSplitter.min_chunk_size`~~ — not a parameter yet (to be added in Module 1)
- ~~`BaseTextSplitter._count_tokens()` default implementation~~ — currently abstract, no default
- ~~`AbstractLoader.full_document`~~ — not a parameter yet (to be added in Module 4)
- ~~`AbstractLoader.min_chunk_size`~~ — not a parameter yet (to be added in Module 4)
- ~~`PDFLoader.full_document`~~ — not a parameter yet (to be added in Module 5)
- ~~`PowerPointLoader.full_document`~~ — not a parameter yet (to be added in Module 7)
- ~~`PgVectorStore.min_embed_tokens`~~ — not a parameter (not in scope for this feature)
- ~~`parrot_loaders.splitters.sentence`~~ — no sentence splitter module exists
- ~~`AbstractLoader._use_semantic_splitter`~~ — no such flag exists

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `TokenTextSplitter` (token.py) as reference for tiktoken integration in SemanticTextSplitter.
- `LateChunkingProcessor._sentence_aware_chunking()` (chunking.py:121) as reference for
  sentence boundary detection — but fix the character-based sizing.
- `BaseTextSplitter.create_chunks()` (base.py:39) for chunk metadata creation pattern.
- Async-first: `_load()` methods are async, but `split_text()` is sync (consistent with
  existing splitters).

### SemanticTextSplitter Algorithm Detail

```
Input: text, chunk_size=2048, min_chunk_size=50, chunk_overlap=200

1. EXTRACT ATOMIC BLOCKS
   - Identify code blocks (```...```) and tables (|...|) → mark as unsplittable
   - Split remaining text on \n\n → paragraph list
   - Interleave atomic blocks at their original positions

2. MEASURE & MERGE
   For each paragraph:
   - Count tokens via tiktoken
   - If current_chunk + paragraph <= chunk_size: append to current chunk
   - Else: flush current chunk, start new chunk with paragraph
   - If a single paragraph > chunk_size: split at sentence boundaries

3. SENTENCE SPLITTING (for oversized paragraphs)
   - Regex: r'(?<=[.!?。！？])\s+'
   - Accumulate sentences until chunk_size, then flush
   - If a single sentence > chunk_size: fall back to token-level splitting
     (reuse TokenTextSplitter logic)

4. MIN SIZE ENFORCEMENT
   - After all chunks created: if last chunk < min_chunk_size, merge with previous
   - If first chunk < min_chunk_size (unlikely but possible), merge with next

5. OVERLAP
   - For each chunk boundary, include chunk_overlap tokens from end of previous chunk
     at start of next chunk
```

### PDFLoader Full-Document Strategy

When `full_document=True`:
- Use `pymupdf4llm.to_markdown(path)` which already produces a single markdown string
  for the entire PDF (this is the `as_markdown=True` path, line 219).
- This approach is superior to concatenating per-page text because pymupdf4llm handles
  cross-page elements (headers, footers, tables spanning pages) correctly.
- Return 1 Document with metadata including total page count.
- If `use_chapters=True` or `use_pages=True`, those override `full_document` and use
  their existing splitting logic.

### MSWordLoader Fix Strategy

The fix is simple: replace the for-loop at line 104 that calls
`self.markdown_splitter.split_text(md_text)` with a single `create_document()` call
returning the full markdown. The standard `chunk_documents()` pipeline handles splitting.

### Known Risks / Gotchas
- **tiktoken as required dependency**: SemanticTextSplitter needs tiktoken. It's already
  present in the environment but should be added to `[dependencies]` if not already.
  Fallback: if tiktoken import fails, use `len(text.split()) * 1.3` estimate (same as
  current MarkdownTextSplitter).
- **pymupdf4llm for PDFLoader**: The `full_document=True` path relies on pymupdf4llm.
  If not installed, fall back to the existing per-page path with a warning.
- **Backwards compatibility**: Users who pass `chunk_size=800` explicitly will now get
  800-token chunks (previously 800-character chunks with MarkdownTextSplitter). This is
  actually *better* (800 tokens ≈ 3200 chars), but worth noting.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `tiktoken` | `>=0.5.0` | Token counting in SemanticTextSplitter |
| `pymupdf4llm` | (existing) | Full-document PDF extraction |

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Modules are tightly coupled. The splitter changes (Modules 1-3) must be
  complete before loader changes (Modules 4-7) can be tested. Integration tests (Module 8)
  need all modules.
- **Cross-feature dependencies**: None. The splitters package is not modified by other
  in-flight features.
- **Suggested worktree**:
  ```bash
  git worktree add -b feat-092-loader-failed-chunking \
    .claude/worktrees/feat-092-loader-failed-chunking HEAD
  ```

---

## 8. Open Questions

- [ ] Should `token_size=20` (abstract.py:64) be removed or repurposed? Appears to be legacy. — *Owner: Jesus*
- [ ] For PDFLoader full_document mode: should page boundary metadata include the total page
      count (`"total_pages": N`) or per-chunk page ranges (`"pages": [3, 4, 5]`)? — *Owner: Jesus*
- [ ] Should the MarkdownTextSplitter bugs (len() vs _count_tokens()) also be fixed as a
      side-effect, or left as-is since SemanticTextSplitter replaces it as default? — *Owner: Jesus*
- [ ] Do we need a migration guide for users who explicitly relied on chunk_size=800
      meaning 800 characters? — *Owner: Jesus*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-09 | Jesus Lara | Initial draft from brainstorm |
