# Brainstorm: Fix Broken Chunking in Loaders

**Date**: 2026-04-09
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

Multiple loaders in ai-parrot-loaders (PDFLoader, TextLoader, MSWordLoader, Excel loaders, etc.)
produce unusable chunks when `split_documents=True` (the default). Chunks contain as few as
10-20 words, incomplete sentences, single titles, or even blank content. This breaks the entire
RAG retrieval pipeline because:

1. **Tiny chunks produce poor embeddings** — a 10-word vector carries almost no semantic signal,
   degrading retrieval precision and recall.
2. **Context is destroyed** — paragraphs are split mid-sentence, so retrieved chunks lack the
   context needed by LLMs to generate accurate answers.
3. **Modern LLMs are underutilized** — current models handle 128K+ token context windows; chunking
   at 800 characters (~150 words) is unnecessarily aggressive.

**Who is affected:** Every consumer of the RAG pipeline (chatbots, agents, knowledge bases) that
uses any file loader with the default chunking configuration.

## Constraints & Requirements

- Must remain backwards-compatible (existing `chunk_size` parameter still works)
- Must work across all loader types (PDF, TXT, DOCX, PPTX, Excel, Video)
- Chunk sizes must be configurable per-loader and per-call
- Default chunk size should target ~2048 tokens (configurable)
- Must never produce chunks below a configurable minimum (e.g., 50 tokens)
- No new heavy dependencies (no LangChain, no spaCy for sentence splitting)
- Must preserve existing `late_chunking` path (which already works better)
- Must handle multi-language text (sentence detection can't be English-only)
- Embedding quality must be validated — tiny chunks should not reach PgVector

---

## Root Cause Analysis

Five compounding issues produce the broken behavior:

### 1. MarkdownTextSplitter uses CHARACTER count, not tokens
`_merge_markdown_sections()` (md.py:153) uses `len(section_text)` (characters) while
`chunk_size=800` is passed as if it were tokens. 800 characters is only ~150 words / ~200 tokens.
But worse: `_count_tokens()` (md.py:44-48) uses `words * 1.3`, creating an internal inconsistency
where the merge logic and the token counting use completely different units.

### 2. Loaders produce per-page/per-slide Documents before chunking
PDFLoader (pdf.py:298-353) creates one Document per page. DOCX and PPTX loaders do similar
per-section splitting. A page with only a title, a caption, or a table header becomes a tiny
Document. Then the splitter fragments it further.

### 3. AbstractLoader defaults to chunk_size=800
(abstract.py:62) `self.chunk_size = kwargs.get('chunk_size', 800)` — even if this were in tokens,
800 tokens (~600 words) is too small for modern LLM context windows.

### 4. No minimum chunk size enforcement
The standard chunking path (`_chunk_with_text_splitter`) has no floor. Any non-empty string
becomes a chunk. Only `LateChunkingProcessor` has `min_chunk_size=100`.

### 5. Markdown detection is over-eager
`_detect_content_type()` (abstract.py:363-366) uses simple heuristics (`#`, `|`, `---`, etc.)
that match almost any structured text, routing most content through MarkdownTextSplitter
even when it's plain text or tabular data.

---

## Options Explored

### Option A: Patch-in-Place (Fix MarkdownTextSplitter + Defaults)

Fix the existing MarkdownTextSplitter to use consistent token counting, raise defaults, and add
minimum chunk enforcement in BaseTextSplitter.

**Changes:**
- Replace all `len()` calls in `_merge_markdown_sections()` and `_split_large_section()` with
  `_count_tokens()` for consistent sizing.
- Change AbstractLoader default `chunk_size` from 800 to 2048.
- Add `min_chunk_size` parameter to BaseTextSplitter with default 50 tokens.
- Modify `create_chunks()` to merge undersized trailing chunks with the previous chunk.
- Fix PDFLoader to offer a `full_document` mode that concatenates all pages before chunking.

Pros:
- Minimal code changes — fixes the bugs where they live.
- No new abstractions or classes.
- Quick to ship.

Cons:
- MarkdownTextSplitter's fundamental approach (split by headers, then merge) still produces
  structure-dependent chunks that may not align with semantic boundaries.
- Token counting via `words * 1.3` is a rough approximation — unreliable for code, CJK text,
  or mixed-language content.
- Doesn't address the core user need: paragraph-aware, semantic chunking.

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tiktoken` | Accurate token counting | Already a dependency via TokenTextSplitter |

**Existing Code to Reuse:**
- `packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py` — direct patch target
- `packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py` — add min_chunk_size
- `packages/ai-parrot/src/parrot/loaders/abstract.py` — raise defaults

---

### Option B: Semantic Paragraph Splitter + Loader Full-Document Mode

Create a new `SemanticTextSplitter` that splits on paragraph and sentence boundaries using
token-based sizing. Modify loaders to produce full-document content by default, letting the
splitter handle all structural decomposition.

**Changes:**

**New: `SemanticTextSplitter`** in `parrot_loaders/splitters/semantic.py`
- Splits text into paragraphs first (double newline `\n\n`).
- Measures each paragraph in tokens (via tiktoken or configurable tokenizer).
- Merges consecutive small paragraphs until reaching `chunk_size` tokens.
- If a single paragraph exceeds `chunk_size`, splits at sentence boundaries.
- Never produces chunks below `min_chunk_size` tokens.
- Falls back to token-based splitting for content with no paragraph structure.

**Modified: AbstractLoader**
- Default `chunk_size` raised to 2048 tokens.
- New `min_chunk_size` parameter (default: 50 tokens).
- `SemanticTextSplitter` becomes the default splitter (replacing MarkdownTextSplitter).
- MarkdownTextSplitter remains available for explicitly markdown-structured content.

**Modified: PDFLoader, MSWordLoader, etc.**
- New `full_document: bool = True` parameter (default True).
- When True, concatenate all pages/slides into a single content string, then return one Document.
- Page boundaries preserved in metadata (page ranges per chunk).
- Existing per-page behavior available via `full_document=False`.

**Modified: BaseTextSplitter**
- Add `min_chunk_size` parameter.
- `create_chunks()` merges undersized final chunks with previous.
- `_count_tokens()` made non-abstract with a default implementation using tiktoken.

**Embedding guard:**
- Add optional `min_embed_tokens` check in `PgVectorStore.add_documents()` to skip/warn on
  chunks below threshold.

Pros:
- Produces complete, semantically coherent paragraphs — ideal for RAG with modern LLMs.
- Token-based sizing is accurate and model-aware.
- Full-document mode preserves cross-page context (critical for PDFs).
- Backwards-compatible — old parameters still work, new defaults are better.
- Clean separation: loaders extract content, splitters handle chunking.

Cons:
- More code than Option A (new splitter class + loader modifications).
- Paragraph detection (`\n\n`) may not work perfectly for all document types.
- tiktoken dependency becomes required (currently optional for MarkdownTextSplitter path).

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tiktoken` | Accurate token counting | Already present, would become required for default splitter |
| `pymupdf4llm` | PDF-to-markdown conversion | Already used, enables full-document extraction |

**Existing Code to Reuse:**
- `packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py` — extend BaseTextSplitter
- `packages/ai-parrot-loaders/src/parrot_loaders/splitters/token.py` — reuse tiktoken setup
- `packages/ai-parrot/src/parrot/stores/utils/chunking.py` — `_sentence_aware_chunking()` pattern
- `packages/ai-parrot/src/parrot/loaders/abstract.py` — modify defaults and splitter selection

---

### Option C: Adopt `semantic-text-splitter` Rust Library

Use the `semantic-text-splitter` Rust-based library (Python bindings via PyO3) which handles
paragraph/sentence/token splitting with proper Unicode support.

**Changes:**
- Add `semantic-text-splitter` as a dependency.
- Create a thin `RustSemanticSplitter` adapter inheriting `BaseTextSplitter`.
- Wire it as the default splitter in AbstractLoader.
- Still need to fix loaders for full-document mode.

Pros:
- Battle-tested, fast (Rust), handles Unicode/CJK well.
- Supports tiktoken and HuggingFace tokenizers.
- Less custom code to maintain for the splitting logic itself.

Cons:
- Adds an external Rust binary dependency — may complicate deployment (Alpine, ARM, etc.).
- Less control over splitting heuristics; harder to debug/customize.
- Still need all the loader-side changes (full-document mode, min size enforcement).
- Overkill for the problem — our paragraph + sentence splitting is straightforward.
- `semantic-text-splitter` v0.x — API may change.

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `semantic-text-splitter` | Paragraph/sentence/token splitting | v0.17+, Rust via PyO3, ~5MB binary |
| `tiktoken` | Token counting for the adapter | Already present |

**Existing Code to Reuse:**
- `packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py` — adapter base class
- `packages/ai-parrot/src/parrot/loaders/abstract.py` — same loader changes as Option B

---

### Option D: Late Chunking as Default Strategy

Make `LateChunkingProcessor` (which already has sentence-aware chunking and min_chunk_size)
the default chunking strategy for all loaders.

**Changes:**
- Make `late_chunking=True` the default in `AbstractLoader.load()`.
- Require vector_store to be passed at load time (or defer chunking).
- Use `_sentence_aware_chunking()` from LateChunkingProcessor as the standard path.

Pros:
- Already implemented and has contextual embedding (surrounding context in prompts).
- Has `min_chunk_size=100` enforcement.
- Produces better embeddings through contextual windowing.

Cons:
- **Couples loading to embedding** — requires `vector_store` at load time, breaking the clean
  separation between loading and storing.
- `_sentence_aware_chunking()` uses character-based sizing (`current_end - current_start`),
  so it has the same character-vs-token unit problem.
- Not all use cases need embeddings at load time (some just want chunked text).
- Would require significant refactoring of the load → chunk → embed pipeline.

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | Uses existing code | |

**Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/stores/utils/chunking.py` — entire LateChunkingProcessor

---

## Recommendation

**Option B** is recommended because:

1. **Addresses the core need**: Semantic paragraph splitting produces the coherent,
   complete-paragraph chunks that modern LLMs can work with effectively.
2. **Fixes both sides of the problem**: Loaders produce full documents (fixing per-page
   fragmentation) AND the splitter uses proper token-based paragraph boundaries (fixing
   the character-based sizing bug).
3. **Clean architecture**: Maintains the separation between loading (content extraction)
   and splitting (chunking). No coupling to vector stores.
4. **Backwards-compatible**: Existing code that passes `chunk_size=800` still works; only
   the defaults change. The `MarkdownTextSplitter` and `TokenTextSplitter` remain available.
5. **Right level of effort**: More thorough than a patch (Option A) but doesn't introduce
   external binary dependencies (Option C) or architectural coupling (Option D).

**Tradeoffs accepted:**
- Medium effort vs. Low (Option A) — worth it because Option A doesn't solve the
  paragraph-boundary problem the user explicitly prioritized.
- tiktoken becomes a harder dependency — acceptable since it's already used in
  TokenTextSplitter and is lightweight.

---

## Feature Description

### User-Facing Behavior

Developers using any loader will see dramatically better chunking out of the box:

```python
# Before: produces 50+ tiny chunks of 10-20 words each
loader = PDFLoader(source="report.pdf")
docs = await loader.load()  # chunk_size=800 chars, per-page, broken

# After: produces ~10-15 complete-paragraph chunks of ~2048 tokens each
loader = PDFLoader(source="report.pdf")
docs = await loader.load()  # chunk_size=2048 tokens, full document, semantic

# Explicit configuration still works
loader = PDFLoader(source="report.pdf", chunk_size=4096, min_chunk_size=100)
docs = await loader.load()

# Opt into old per-page behavior
loader = PDFLoader(source="report.pdf", full_document=False)
docs = await loader.load()

# No chunking still works
docs = await loader.load(split_documents=False)
```

### Internal Behavior

The load pipeline becomes:

1. **Loader._load()** extracts full-document content (all pages concatenated).
   - Page/section boundaries stored in metadata, not as separate Documents.
   - Returns 1 Document per file (not per page).

2. **AbstractLoader.chunk_documents()** routes to the configured splitter.
   - Default: `SemanticTextSplitter` (paragraph + sentence aware, token-based).
   - Alternative: `MarkdownTextSplitter`, `TokenTextSplitter` (explicit opt-in).

3. **SemanticTextSplitter.split_text()**:
   - Split text on `\n\n` (paragraph boundaries).
   - For each paragraph, count tokens via tiktoken.
   - Merge consecutive small paragraphs until `chunk_size` tokens is approached.
   - If a single paragraph exceeds `chunk_size`, split at sentence boundaries
     (`.!?` followed by whitespace).
   - If a single sentence exceeds `chunk_size`, fall back to token-based splitting.
   - Never produce a chunk below `min_chunk_size` tokens — merge with adjacent.

4. **PgVectorStore.add_documents()** embeds and stores chunks.
   - Optional: warn/skip chunks below `min_embed_tokens`.

### Edge Cases & Error Handling

- **Empty document**: Return empty list (no chunks), log warning.
- **Single short paragraph below min_chunk_size**: Return it as-is (one chunk) — don't discard
  legitimate short content.
- **No paragraph boundaries** (e.g., a wall of text): Fall back to sentence splitting, then
  to token-based splitting.
- **Code blocks**: Preserve code blocks as atomic units — never split mid-code-block.
- **Tables**: Preserve tables as atomic units where possible.
- **CJK text**: tiktoken handles CJK tokenization correctly; sentence detection uses
  CJK-aware punctuation (`.!?` + `。！？`).
- **Mixed content** (markdown + plain text): SemanticTextSplitter handles both since paragraphs
  are a universal structural element.

---

## Capabilities

### New Capabilities
- `semantic-text-splitter`: New paragraph-aware, token-based text splitter
- `loader-full-document-mode`: Loaders produce full-document content by default
- `min-chunk-size-enforcement`: Minimum chunk size validation in BaseTextSplitter

### Modified Capabilities
- `abstract-loader-defaults`: chunk_size raised from 800 to 2048, default splitter changed
- `pdf-loader`: full_document mode, full markdown concatenation
- `docx-loader`: full_document mode
- `base-text-splitter`: min_chunk_size parameter, default _count_tokens implementation

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_loaders/splitters/` | extends | New `SemanticTextSplitter` class |
| `parrot_loaders/splitters/base.py` | modifies | Add min_chunk_size, default _count_tokens |
| `parrot_loaders/splitters/__init__.py` | modifies | Export new splitter |
| `parrot/loaders/abstract.py` | modifies | New defaults, splitter selection logic |
| `parrot_loaders/pdf.py` | modifies | full_document mode |
| `parrot_loaders/docx.py` | modifies | full_document mode |
| `parrot_loaders/txt.py` | minimal | Benefits from new defaults automatically |
| `parrot/stores/postgres.py` | extends | Optional min_embed_tokens guard |
| `parrot/stores/utils/chunking.py` | untouched | Late chunking path unchanged |

**Breaking changes:** None. All changes are additive with better defaults. Passing explicit
`chunk_size=800` still works (though it now means 800 tokens, not characters, for the
SemanticTextSplitter — this is the correct interpretation).

---

## Code Context

### User-Provided Code

No code snippets provided by user.

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py:19
class BaseTextSplitter(ABC):
    def __init__(self, chunk_size: int = 4000, chunk_overlap: int = 200,
                 keep_separator: bool = True, add_start_index: bool = True)  # line 22
    def split_text(self, text: str) -> List[str]  # line 34 (abstract)
    def create_chunks(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[TextChunk]  # line 39
    def _count_tokens(self, text: str) -> int  # line 82 (abstract)
    def _merge_splits(self, splits: List[str], separator: str) -> List[str]  # line 87

# From packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py:6
class MarkdownTextSplitter(BaseTextSplitter):
    def __init__(self, chunk_size: int = 4000, chunk_overlap: int = 200,
                 strip_headers: bool = False, return_each_line: bool = False)  # line 17
    def _count_tokens(self, text: str) -> int  # line 44 — uses words * 1.3 (BUG: inconsistent with merge logic)
    def split_text(self, text: str) -> List[str]  # line 50
    def _merge_markdown_sections(self, sections) -> List[str]  # line 142 — uses len() not _count_tokens() (BUG)
    def _split_large_section(self, text: str) -> List[str]  # line 187 — uses len() not _count_tokens() (BUG)

# From packages/ai-parrot-loaders/src/parrot_loaders/splitters/token.py:5
class TokenTextSplitter(BaseTextSplitter):
    def __init__(self, chunk_size: int = 4000, chunk_overlap: int = 200,
                 model_name: str = "gpt-3.5-turbo", ...)  # line 15
    def _count_tokens(self, text: str) -> int  # line 106 — uses tiktoken (correct)
    def split_text(self, text: str) -> List[str]  # line 110

# From packages/ai-parrot/src/parrot/loaders/abstract.py:35
class AbstractLoader(ABC):
    chunk_size: int  # line 62, default 800
    chunk_overlap: int  # line 63, default 100
    token_size: int  # line 64, default 20 (purpose unclear, possibly legacy)
    _use_markdown_splitter: bool  # line 77, default True
    _auto_detect_content_type: bool  # line 79, default True
    def _setup_text_splitters(self, tokenizer, text_splitter, kwargs)  # line 168
    def _detect_content_type(self, document: Document) -> str  # line 331
    def _select_splitter_for_content(self, content_type: str)  # line 372
    async def chunk_documents(self, documents, ...) -> List[Document]  # line 978
    def _chunk_with_text_splitter(self, documents, ...) -> List[Document]  # line 1008

# From packages/ai-parrot-loaders/src/parrot_loaders/pdf.py:10
class PDFLoader(AbstractLoader):
    def __init__(self, ..., as_markdown: bool = False, use_chapters: bool = False,
                 use_pages: bool = False)  # line 22
    async def _load(self, path: PurePath, **kwargs) -> List[Document]  # line 213

# From packages/ai-parrot/src/parrot/stores/utils/chunking.py:20
class LateChunkingProcessor:
    def __init__(self, vector_store, chunk_size: int = 8192, chunk_overlap: int = 200,
                 preserve_sentences: bool = True, min_chunk_size: int = 100)  # line 28
    def _sentence_aware_chunking(self, text: str) -> List[Tuple[str, int, int]]  # line 121
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot_loaders.splitters.base import BaseTextSplitter  # splitters/__init__.py:1
from parrot_loaders.splitters.md import MarkdownTextSplitter  # splitters/__init__.py:2
from parrot_loaders.splitters.token import TokenTextSplitter  # splitters/__init__.py:3
from parrot.loaders.abstract import AbstractLoader  # pdf.py:8
from parrot.stores.models import Document  # pdf.py:7
```

#### Key Attributes & Constants
- `AbstractLoader.chunk_size` -> `int` (abstract.py:62, default 800)
- `AbstractLoader.chunk_overlap` -> `int` (abstract.py:63, default 100)
- `AbstractLoader.token_size` -> `int` (abstract.py:64, default 20, likely legacy)
- `AbstractLoader._use_markdown_splitter` -> `bool` (abstract.py:77, default True)
- `AbstractLoader._auto_detect_content_type` -> `bool` (abstract.py:79, default True)
- `BaseTextSplitter.chunk_size` -> `int` (base.py:29)
- `LateChunkingProcessor.min_chunk_size` -> `int` (chunking.py:34, default 100)

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_loaders.splitters.semantic`~~ — does not exist yet (to be created)
- ~~`BaseTextSplitter.min_chunk_size`~~ — not a parameter yet (to be added)
- ~~`AbstractLoader.full_document`~~ — not a parameter yet (to be added)
- ~~`PDFLoader.full_document`~~ — not a parameter yet (to be added)
- ~~`PgVectorStore.min_embed_tokens`~~ — not a parameter yet (optional addition)
- ~~`parrot_loaders.splitters.sentence`~~ — no sentence splitter exists
- ~~`BaseTextSplitter._count_tokens()` default implementation~~ — it is abstract, no default

---

## Parallelism Assessment

- **Internal parallelism**: Mixed. The SemanticTextSplitter is fully independent and can be
  developed in parallel with the loader full-document changes. The BaseTextSplitter min_chunk_size
  change must land first since both depend on it.
- **Cross-feature independence**: No known conflicts with in-flight specs. The splitters package
  is not being modified by other features.
- **Recommended isolation**: `per-spec` — tasks are tightly coupled (splitter changes affect
  loader behavior, integration testing needs both).
- **Rationale**: While the new splitter class could theoretically be developed in isolation,
  meaningful testing requires the loader changes too. Sequential execution in one worktree is
  more practical.

---

## Open Questions

- [ ] Should `token_size=20` (abstract.py:64) be removed or repurposed? It appears to be legacy code with no clear usage path. — *Owner: Jesus*
- [ ] Should we backfill a `_count_tokens()` default implementation in BaseTextSplitter using a simple `len(text.split()) * 1.3` estimate, or require all splitters to implement it with a real tokenizer? — *Owner: Jesus*
- [ ] For PDFLoader full_document mode: should page boundary metadata include page numbers as a list in chunk metadata (e.g., `"pages": [3, 4, 5]`)? — *Owner: Jesus*
- [ ] Should the embedding guard in PgVectorStore be a hard skip (discard tiny chunks) or a soft warning (log but still embed)? — *Owner: Jesus*
- [ ] Do Excel loaders (XLSXLoader) need special handling for full_document mode, since spreadsheets have a fundamentally different structure (sheets, rows) vs. linear text? — *Owner: Jesus*
