# TASK-635: Create SemanticTextSplitter

**Feature**: loader-failed-chunking
**Spec**: `sdd/specs/loader-failed-chunking.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-633
**Assigned-to**: unassigned

---

## Context

Core deliverable of FEAT-092 (Module 2 + Module 3 from spec). Creates the new
`SemanticTextSplitter` that splits on paragraph and sentence boundaries using
token-based sizing via tiktoken. This replaces `MarkdownTextSplitter` as the
default splitter in the loader pipeline.

---

## Scope

- Create `packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py` with
  `SemanticTextSplitter` class inheriting `BaseTextSplitter`.
- Implement `split_text()` with the algorithm:
  1. Extract atomic blocks (code blocks, tables) — mark as unsplittable.
  2. Split remaining text on `\n\n` (paragraph boundaries).
  3. Measure each paragraph in tokens via tiktoken.
  4. Merge consecutive small paragraphs until `chunk_size` tokens is approached.
  5. Split oversized paragraphs at sentence boundaries (`[.!?。！？]\s+`).
  6. If a single sentence exceeds `chunk_size`, fall back to token-level splitting.
  7. Enforce `min_chunk_size` — merge undersized final chunks with previous.
- Implement `_count_tokens()` using tiktoken (same pattern as `TokenTextSplitter`).
- Handle overlap via `chunk_overlap` parameter.
- Export from `splitters/__init__.py`.
- Write comprehensive unit tests.

**NOT in scope**: Wiring into AbstractLoader (TASK-636), loader changes (TASK-637-639).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py` | CREATE | SemanticTextSplitter implementation |
| `packages/ai-parrot-loaders/src/parrot_loaders/splitters/__init__.py` | MODIFY | Export SemanticTextSplitter |
| `tests/loaders/test_semantic_splitter.py` | CREATE | Comprehensive unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_loaders.splitters.base import BaseTextSplitter, TextChunk  # splitters/__init__.py:1, base.py:8
from parrot_loaders.splitters.token import TokenTextSplitter           # splitters/__init__.py:3
# After TASK-633, BaseTextSplitter will have min_chunk_size param and default _count_tokens()
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py:19
class BaseTextSplitter(ABC):
    def __init__(self, chunk_size: int = 4000, chunk_overlap: int = 200,
                 keep_separator: bool = True, add_start_index: bool = True):  # line 22
        # After TASK-633: also accepts min_chunk_size: int = 0
    def split_text(self, text: str) -> List[str]:                     # line 34 (abstract)
    def create_chunks(self, text: str, metadata=None) -> List[TextChunk]:  # line 39
    def _count_tokens(self, text: str) -> int:                        # line 82 (after TASK-633: has default impl)
    def _merge_splits(self, splits: List[str], separator: str) -> List[str]:  # line 87

# packages/ai-parrot-loaders/src/parrot_loaders/splitters/token.py:5
# REFERENCE PATTERN for tiktoken integration:
class TokenTextSplitter(BaseTextSplitter):
    def __init__(self, chunk_size=4000, chunk_overlap=200,
                 model_name="gpt-3.5-turbo", encoding_name=None,
                 tokenizer=None, tokenizer_function=None, ...):       # line 15
    # tiktoken setup at lines 58-71:
    #   import tiktoken
    #   self._enc = tiktoken.encoding_for_model(model_name)  OR
    #   self._enc = tiktoken.get_encoding(encoding_name)
    def _count_tokens(self, text: str) -> int:                        # line 106
        return len(self._encode(text))
    def split_text(self, text: str) -> List[str]:                     # line 110

# packages/ai-parrot-loaders/src/parrot_loaders/splitters/__init__.py
# Current exports (lines 1-10):
from .base import BaseTextSplitter
from .md import MarkdownTextSplitter
from .token import TokenTextSplitter
__all__ = ('BaseTextSplitter', 'MarkdownTextSplitter', 'TokenTextSplitter')
```

### Does NOT Exist
- ~~`parrot_loaders.splitters.semantic`~~ — does not exist (YOU are creating it)
- ~~`SemanticTextSplitter`~~ — does not exist (YOU are creating it)
- ~~`BaseTextSplitter.split_paragraphs()`~~ — no such method
- ~~`BaseTextSplitter.split_sentences()`~~ — no such method
- ~~`parrot_loaders.splitters.sentence`~~ — no sentence splitter module

---

## Implementation Notes

### Algorithm Detail (from spec Section 7)

```
Input: text, chunk_size=2048, min_chunk_size=50, chunk_overlap=200

1. EXTRACT ATOMIC BLOCKS
   - Identify code blocks (```...```) → mark as unsplittable
   - Identify markdown tables (lines starting with |) → mark as unsplittable
   - Split remaining text on \n\n → paragraph list
   - Interleave atomic blocks at their original positions

2. MEASURE & MERGE
   For each paragraph/block:
   - Count tokens via tiktoken
   - If current_chunk_tokens + paragraph_tokens <= chunk_size: append
   - Else: flush current chunk to results, start new with this paragraph
   - If a single paragraph > chunk_size: split at sentence boundaries

3. SENTENCE SPLITTING (for oversized paragraphs)
   - Regex: r'(?<=[.!?。！？])\s+'
   - Accumulate sentences until chunk_size, then flush
   - If a single sentence > chunk_size: use token-level splitting
     (encode to tokens, split at chunk_size boundaries, decode back)

4. MIN SIZE ENFORCEMENT
   - After all chunks: if last chunk < min_chunk_size, merge with previous
   - (TASK-633 adds this to create_chunks(), but split_text() should also
     try to avoid producing tiny splits in the first place)

5. OVERLAP
   - For each chunk boundary, prepend chunk_overlap tokens from previous chunk
```

### Class Structure

```python
class SemanticTextSplitter(BaseTextSplitter):
    def __init__(
        self,
        chunk_size: int = 2048,
        chunk_overlap: int = 200,
        min_chunk_size: int = 50,
        model_name: str = "gpt-4",
        encoding_name: Optional[str] = None,
        sentence_endings: Optional[str] = None,
        preserve_code_blocks: bool = True,
        preserve_tables: bool = True,
        **kwargs
    ):
        super().__init__(chunk_size, chunk_overlap, min_chunk_size=min_chunk_size, **kwargs)
        # Initialize tiktoken (follow TokenTextSplitter pattern)
        # Set sentence_endings regex

    def split_text(self, text: str) -> List[str]: ...
    def _count_tokens(self, text: str) -> int: ...
    def _extract_atomic_blocks(self, text: str) -> List[Tuple[str, bool]]: ...
    def _split_paragraphs(self, text: str) -> List[str]: ...
    def _split_at_sentences(self, text: str) -> List[str]: ...
    def _apply_overlap(self, chunks: List[str]) -> List[str]: ...
```

### tiktoken Fallback
If tiktoken is not available (ImportError), fall back to the word-based estimate
from BaseTextSplitter's default `_count_tokens()`. Log a warning.

### Key Constraints
- Sentence regex must handle CJK: `r'(?<=[.!?。！？])\s+'`
- Code blocks (``` ... ```) must never be split mid-block
- Tables (consecutive lines starting with `|`) must stay together
- Empty input → return `[]`
- Single text below min_chunk_size → return `[text]` (don't discard)

---

## Acceptance Criteria

- [ ] `SemanticTextSplitter` class exists in `splitters/semantic.py`
- [ ] Exported from `splitters/__init__.py`
- [ ] `split_text()` splits on paragraph boundaries
- [ ] Token counting uses tiktoken
- [ ] Small paragraphs merged until chunk_size reached
- [ ] Oversized paragraphs split at sentence boundaries
- [ ] Code blocks preserved as atomic units
- [ ] Tables preserved as atomic units
- [ ] CJK sentence endings recognized
- [ ] Empty input returns `[]`
- [ ] Single short text returns `[text]` (not discarded)
- [ ] All tests pass: `pytest tests/loaders/test_semantic_splitter.py -v`

---

## Test Specification

```python
# tests/loaders/test_semantic_splitter.py
import pytest
from parrot_loaders.splitters.semantic import SemanticTextSplitter


@pytest.fixture
def splitter():
    return SemanticTextSplitter(chunk_size=100, chunk_overlap=0, min_chunk_size=5)


class TestSemanticTextSplitter:
    def test_split_paragraphs(self, splitter):
        """Text with \\n\\n produces paragraph-level chunks."""
        text = "First paragraph with enough words.\n\nSecond paragraph with enough words."
        chunks = splitter.split_text(text)
        assert len(chunks) >= 1
        assert all(len(c.strip()) > 0 for c in chunks)

    def test_merge_small_paragraphs(self):
        """Consecutive small paragraphs merged to reach chunk_size."""
        splitter = SemanticTextSplitter(chunk_size=200, chunk_overlap=0, min_chunk_size=5)
        text = "Short one.\n\nShort two.\n\nShort three.\n\nShort four."
        chunks = splitter.split_text(text)
        # All short paragraphs should merge into 1 chunk
        assert len(chunks) == 1

    def test_split_oversized_paragraph(self):
        """Single large paragraph split at sentence boundaries."""
        splitter = SemanticTextSplitter(chunk_size=30, chunk_overlap=0, min_chunk_size=5)
        text = "First sentence here. Second sentence here. Third sentence here. Fourth sentence here."
        chunks = splitter.split_text(text)
        assert len(chunks) >= 2

    def test_code_block_preserved(self):
        """Code blocks are never split mid-block."""
        splitter = SemanticTextSplitter(chunk_size=30, chunk_overlap=0, min_chunk_size=5)
        text = "Before.\n\n```python\ndef foo():\n    return 42\n```\n\nAfter."
        chunks = splitter.split_text(text)
        # Find the chunk containing the code block
        code_chunks = [c for c in chunks if "```python" in c]
        assert len(code_chunks) >= 1
        assert "return 42" in code_chunks[0]

    def test_empty_input(self):
        """Empty string returns empty list."""
        splitter = SemanticTextSplitter()
        assert splitter.split_text("") == []

    def test_single_short_text(self):
        """Text below min_chunk_size returned as single chunk."""
        splitter = SemanticTextSplitter(chunk_size=100, min_chunk_size=50)
        chunks = splitter.split_text("Hello world.")
        assert len(chunks) == 1
        assert chunks[0] == "Hello world."

    def test_token_counting(self):
        """Token count uses tiktoken, not character length."""
        splitter = SemanticTextSplitter()
        count = splitter._count_tokens("Hello world, this is a test.")
        assert isinstance(count, int)
        assert count > 0
        assert count != len("Hello world, this is a test.")  # Not char count

    def test_cjk_sentence_splitting(self):
        """CJK punctuation recognized for sentence splitting."""
        splitter = SemanticTextSplitter(chunk_size=20, chunk_overlap=0, min_chunk_size=3)
        text = "First sentence here. Second sentence here."
        chunks = splitter.split_text(text)
        assert len(chunks) >= 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/loader-failed-chunking.spec.md` for full context
2. **Check dependencies** — TASK-633 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — read `splitters/token.py` for tiktoken pattern
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** `SemanticTextSplitter` and update `__init__.py`
6. **Run tests**: `pytest tests/loaders/test_semantic_splitter.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
