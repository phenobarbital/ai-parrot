# Feature Specification: Rust-backed Semantic Text Splitter

**Feature ID**: FEAT-141
**Date**: 2026-05-04
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

The current `SemanticTextSplitter` (`packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py`,
435 LOC) is the default splitter wired into
`AbstractLoader._setup_text_splitters()` (`packages/ai-parrot/src/parrot/loaders/abstract.py:245-251`)
and runs on **every** RAG corpus we ingest unless the operator explicitly
overrides it.

It is "semantic" only in name. Multiple production cases produce chunks
cut **mid-word**, with no respect for sentence or paragraph boundaries:

- AT&T `att.concierge` corpus: a JSON-LD FAQ entry whose original text is
  `"Your AT&T Prepaid account allows you to see your data usage, change your
  plan, check your balance, enroll & set up AutoPay."` was indexed as
  `"...allows you to see your data us"` — cutting off the literal
  `"set up AutoPay"` reference. The retrieval test for `"can I setup
  autopay?"` then fails to surface the obvious match because the answer
  is **not in the chunk**.

The recently-added `_ATOMIC_CONTENT_KINDS` guard for `'faq'` / `'table'`
(FEAT-140-adjacent fix in `parrot/loaders/abstract.py:1312-1319`)
patches one symptom: it tells the loader "do not chunk these". But the
underlying splitter still mishandles long-form content (full-page
markdown, trafilatura output, blog posts, technical docs) — the same
mid-word, sub-sentence cuts will appear there too as soon as we stop
treating those documents as atomic.

We need a splitter that is **physically incapable** of cutting in the
middle of a word. That rules out the current ad-hoc Python implementation
and points to a well-tested library.

`semantic-text-splitter` (Rust crate by Ben Brandt, Python bindings on
PyPI) provides exactly that: strict respect for a boundary hierarchy
(sentence > line > paragraph > section), token-aware capacity, optional
HuggingFace / tiktoken integration, and a `MarkdownSplitter` variant that
respects code fences, headers and lists.

### Goals

- Replace the body of `SemanticTextSplitter` with a thin wrapper over
  `semantic_text_splitter.TextSplitter`. Same class name, same module path,
  same public API (`split_text`, `create_chunks`).
- Replace the body of `MarkdownTextSplitter` (228 LOC) with a thin wrapper
  over `semantic_text_splitter.MarkdownSplitter`. Same approach.
- Preserve the `TextChunk` dataclass shape and the metadata contract
  (`chunk_index`, `total_chunks`, `splitter_type`, `chunk_id`).
- Preserve the constructor kwargs that consumers actually use today:
  `chunk_size`, `chunk_overlap`, `min_chunk_size`, `model_name`,
  `**kwargs`.
- Eliminate ~660 LOC of unmaintained custom splitting code.
- Make mid-word cuts impossible by construction.

### Non-Goals (explicitly out of scope)

- Replacing `TokenTextSplitter` (`packages/ai-parrot-loaders/src/parrot_loaders/splitters/token.py`,
  143 LOC). It powers `code` content_type via
  `_select_splitter_for_content` (`abstract.py:432`) and works correctly.
- Modifying `BaseTextSplitter` ABC or the `TextChunk` dataclass shape
  (`base.py:8-16`). The contract stays, only the concrete implementations
  change.
- Touching `_ATOMIC_CONTENT_KINDS` or anything in `chunk_documents()` —
  the FAQ/table fix (FEAT-140-adjacent) stays as-is.
- Embedding-based "semantic" chunking (Greg Kamradt / LlamaIndex
  `SemanticChunker` style). Different approach, separate spec if ever
  pursued.
- Migrating already-stored vectors. Operators reload corpora through the
  new splitter to benefit; old vectors remain valid (just suboptimally
  chunked).
- Backward-compatibility shims for the old constructor kwargs that no
  consumer uses (`encoding_name`, `sentence_endings`, `preserve_code_blocks`,
  `preserve_tables`) — they get accepted via `**kwargs` and silently
  ignored. The Rust splitter handles those concerns natively.

---

## 2. Architectural Design

### Overview

Two file rewrites, one dependency addition, zero API breakage. Every
existing import (`from parrot_loaders.splitters import SemanticTextSplitter`
or `MarkdownTextSplitter`) keeps working unchanged because the class
names and module paths are preserved — only the implementation underneath
changes.

The new `SemanticTextSplitter` is a wrapper that:

1. Accepts the same constructor kwargs as today (`chunk_size`,
   `chunk_overlap`, `min_chunk_size`, `model_name`, `**kwargs`).
2. Builds either a `TextSplitter(capacity=chunk_size, overlap=chunk_overlap)`
   (char-based, default) or `TextSplitter.from_huggingface_tokenizer(...)` /
   `TextSplitter.from_tiktoken_model(...)` if a `tokenizer=` kwarg is
   provided (token-based, opt-in).
3. Implements `split_text(text)` by calling `self._rust.chunks(text)`.
4. Implements `create_chunks(text, metadata)` by calling
   `self._rust.chunk_indices(text)` (which gives `(byte_offset, chunk_text)`
   tuples), translating byte offsets to character positions via UTF-8
   decoding when needed, and packaging into the existing `TextChunk`
   dataclass with the same `chunk_id` pattern and metadata structure.
5. Re-implements the `min_chunk_size` tail-merge from
   `BaseTextSplitter.create_chunks` (`base.py:84-106`) — the Rust splitter
   has no min-chunk concept, so the trailing undersized chunk is merged
   with its predecessor in the wrapper.

The `MarkdownTextSplitter` follows the same pattern with
`MarkdownSplitter` instead of `TextSplitter`.

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│  packages/ai-parrot-loaders/src/parrot_loaders/         │
│                                                         │
│  splitters/                                             │
│  ┌──────────────────┐  ┌──────────────────────┐         │
│  │ base.py          │  │ token.py             │         │
│  │ BaseTextSplitter │  │ TokenTextSplitter    │         │
│  │ TextChunk        │  │ (UNCHANGED)          │         │
│  │ (UNCHANGED)      │  └──────────────────────┘         │
│  └────────┬─────────┘                                   │
│           │ ABC                                         │
│           ▼                                             │
│  ┌──────────────────┐  ┌──────────────────────┐         │
│  │ semantic.py      │  │ md.py                │         │
│  │ SemanticText-    │  │ MarkdownText-        │         │
│  │ Splitter         │  │ Splitter             │         │
│  │ (REWRITE)        │  │ (REWRITE)            │         │
│  └────────┬─────────┘  └─────────┬────────────┘         │
│           │                      │                      │
│           ▼                      ▼                      │
│  ┌────────────────────────────────────────────┐         │
│  │ semantic_text_splitter (Rust, PyPI)        │         │
│  │   TextSplitter, MarkdownSplitter           │         │
│  └────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────┘

         ▲
         │ used by (single consumer)
         │
┌────────┴────────────────────────────────────┐
│  packages/ai-parrot/src/parrot/loaders/     │
│  abstract.py                                │
│  AbstractLoader._setup_text_splitters       │
│  default = SemanticTextSplitter             │
│  (NO CHANGE — class name preserved)         │
└─────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BaseTextSplitter` | extends (unchanged ABC) | New wrappers inherit; `split_text` is the abstract method |
| `TextChunk` dataclass | constructed (unchanged shape) | Wrappers package outputs into this, byte-identical fields |
| `AbstractLoader._setup_text_splitters` (`abstract.py:245-251`) | callee | No code change — `SemanticTextSplitter()` with same kwargs builds the new wrapper |
| `AbstractLoader._get_markdown_splitter` (`abstract.py:169-182`) | callee | No code change — `MarkdownTextSplitter()` with same kwargs builds the new wrapper |
| `_select_splitter_for_content` (`abstract.py:421-433`) | callee | Routes `code` to `TokenTextSplitter` (untouched), everything else to `text_splitter` (the new wrapper) |
| `chunk_documents` (`abstract.py:1289-1384`) | callee | No code change — calls `splitter.create_chunks(text, metadata)`, gets `TextChunk` objects back as before |
| `pyproject.toml` of `ai-parrot-loaders` | adds dependency | One line under `dependencies = [ ... ]` |

### Data Models

`TextChunk` shape stays exactly as today (`base.py:8-16`):

```python
@dataclass
class TextChunk:
    text: str
    start_position: int       # char offset, not byte offset
    end_position: int         # char offset
    token_count: int          # exact when tokenizer provided, estimated otherwise
    metadata: Dict[str, Any]  # chunk_index, total_chunks, splitter_type, ...
    chunk_id: Optional[str] = None
```

No new public types. The wrapper holds a private `self._rust` attribute
(the underlying `TextSplitter` / `MarkdownSplitter`) and a small set of
state needed to compute token counts when the wrapper is char-based but
the consumer still asks for `token_count`.

### New Public Interfaces

None. The class names, module paths, and constructor signatures are
preserved.

A new **internal** kwarg `tokenizer` is added to both wrappers for
opt-in token-based capacity. When provided, it must be either:

- a HuggingFace tokenizer (anything with a `Tokenizer.from_pretrained(...)`
  surface) → routed through `TextSplitter.from_huggingface_tokenizer(...)`
- a tiktoken encoding name (e.g. `"cl100k_base"`) → routed through
  `TextSplitter.from_tiktoken_model(...)`

When omitted (the default), capacity is character-based — which is what
every current consumer is implicitly relying on (none of them pass a
tokenizer today).

```python
# Char-based — current default, unchanged behavior for existing call sites
SemanticTextSplitter(chunk_size=512, chunk_overlap=50)

# Token-based (opt-in, new in this spec)
SemanticTextSplitter(chunk_size=512, tokenizer=hf_tokenizer)
SemanticTextSplitter(chunk_size=512, tokenizer="cl100k_base")
```

---

## 3. Module Breakdown

### Module 1: Add Rust Splitter Dependency
- **Path**: `packages/ai-parrot-loaders/pyproject.toml`
- **Responsibility**: Add `"semantic-text-splitter>=0.30,<1.0"` to the
  `dependencies = [ ... ]` block (currently lines 28-33). Verify `uv pip
  install -e packages/ai-parrot-loaders` resolves cleanly. Does NOT touch
  optional-dependencies or other groups.
- **Depends on**: nothing.

### Module 2: Rewrite `SemanticTextSplitter`
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py`
- **Responsibility**: Delete the 435-LOC custom implementation. Replace
  with a wrapper (~80 LOC target) that:
  - Inherits `BaseTextSplitter`.
  - Builds `semantic_text_splitter.TextSplitter` in `__init__`, choosing
    char-based or token-based mode based on the optional `tokenizer=` kwarg.
  - Implements `split_text(text) -> List[str]` via `self._rust.chunks(text)`.
  - Overrides `create_chunks(text, metadata) -> List[TextChunk]` using
    `self._rust.chunk_indices(text)` for accurate offsets, then applies the
    `min_chunk_size` tail-merge from `base.py:84-106` (extracted as a
    shared helper or inlined — see implementation note 7.1 below).
  - Logs one INFO line at construction:
    `"Using semantic-text-splitter (Rust) chunk_size=N capacity=chars|tokens overlap=M"`.
  - Accepts unused legacy kwargs (`encoding_name`, `sentence_endings`,
    `preserve_code_blocks`, `preserve_tables`, `model_name`) via
    `**kwargs` and silently drops them — the Rust splitter handles
    those concerns natively.
- **Depends on**: Module 1.

### Module 3: Rewrite `MarkdownTextSplitter`
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py`
- **Responsibility**: Delete the 228-LOC custom implementation. Replace
  with a wrapper (~80 LOC target) following the same pattern as Module 2,
  but using `semantic_text_splitter.MarkdownSplitter` instead of
  `TextSplitter`. The Markdown variant respects headers, code fences,
  list items, and blockquotes natively.
- **Depends on**: Module 1.

### Module 4: Tail-Merge Helper Refactor (optional)
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py`
- **Responsibility**: The `min_chunk_size` tail-merge logic at
  `base.py:84-106` is currently inside `BaseTextSplitter.create_chunks`.
  Both new wrappers need it but they override `create_chunks` to use the
  Rust splitter's `chunk_indices`. Extract the tail-merge into a
  `_enforce_min_chunk_size(chunks: List[TextChunk]) -> List[TextChunk]`
  helper on `BaseTextSplitter` so both wrappers can call it after they
  build their `TextChunk` list. **Do not change** the existing
  `create_chunks` behavior — the helper must be idempotent and produce
  byte-identical output for the legacy path.
- **Depends on**: nothing (can be done before Modules 2/3).

### Module 5: New Splitter Test Suite
- **Path**: `packages/ai-parrot-loaders/tests/splitters/test_rust_splitters.py` (new)
- **Responsibility**: Comprehensive coverage of the new wrappers. Tests
  enumerated in §4. Includes the AutoPay regression case from
  `att.concierge` as a deterministic fixture so the bug can never come
  back silently.
- **Depends on**: Modules 2-3.

### Module 6: Verify No-Code-Change for Single Consumer
- **Path**: `packages/ai-parrot/src/parrot/loaders/abstract.py`
  (verification only — no edits)
- **Responsibility**: Confirm that `abstract.py:245-251` (default
  `SemanticTextSplitter` instantiation) and `abstract.py:178-182` (default
  `MarkdownTextSplitter` instantiation) work unchanged after Modules 2-3
  land. Confirm `chunk_documents` still receives `TextChunk` objects with
  the expected fields. Run the existing `tests/loaders/` suite and confirm
  zero regressions. This module is verification only — it produces no
  diff, only test results.
- **Depends on**: Modules 2-5.

---

## 4. Test Specification

### Unit Tests (Module 5 — `test_rust_splitters.py`)

| Test | Module | Description |
|---|---|---|
| `test_semantic_split_text_no_mid_word_cuts` | M2 | For a long text with no natural sentence boundary > chunk_size, `split_text` returns chunks where every chunk's first/last token (bounded by whitespace) is a complete word. |
| `test_semantic_autopay_regression` | M2 | Hardcoded `att.concierge` Q&A text. After splitting with `chunk_size=512`, the substring `"set up AutoPay"` appears intact in some chunk. This is the regression guard for the production bug. |
| `test_semantic_create_chunks_offsets_slice_back` | M2 | For every chunk produced by `create_chunks`, `text[chunk.start_position:chunk.end_position]` reconstructs `chunk.text` exactly. Trip-wire on UTF-8 byte/char offset confusion. |
| `test_semantic_min_chunk_size_tail_merge` | M2/M4 | Text engineered to produce a tiny trailing chunk under `min_chunk_size=30`. Assert the tail is merged into its predecessor and `total_chunks` in metadata is updated accordingly. |
| `test_semantic_overlap_honored` | M2 | `chunk_size=200, chunk_overlap=50` on a long text. Consecutive chunks share at least 30 chars of suffix/prefix (Rust splitter does best-effort overlap, not exact). |
| `test_semantic_tokenizer_changes_capacity` | M2 | Same text + same `chunk_size=100`, char-based vs HF-tokenizer-based modes produce different chunk counts. Proves the `tokenizer=` kwarg is wired through. |
| `test_semantic_legacy_kwargs_silently_accepted` | M2 | Constructing with `encoding_name=...`, `sentence_endings=...`, `preserve_code_blocks=...`, `model_name=...` does not raise. The kwargs are dropped. |
| `test_semantic_metadata_contract` | M2 | `create_chunks(text, {"src": "x"})` returns chunks where every metadata dict contains `chunk_index`, `total_chunks`, `splitter_type=="SemanticTextSplitter"`, and the original `"src": "x"` is preserved. |
| `test_semantic_chunk_id_format` | M2 | Every `TextChunk.chunk_id` matches the regex `^chunk_\d{4}_[0-9a-f]{8}$`. |
| `test_markdown_preserves_code_fences` | M3 | Markdown text with a ```` ```python ... ``` ```` block longer than `chunk_size`. The fence is never broken across chunks (either kept whole, or split at fence boundaries — never mid-fence). |
| `test_markdown_preserves_headers` | M3 | Markdown with `# H1\n\nbody1\n\n## H2\n\nbody2`. Chunks never split between a header and its first sentence of body. |
| `test_markdown_create_chunks_offsets_slice_back` | M3 | Same offset invariant as M2 test. |
| `test_markdown_metadata_splitter_type` | M3 | `splitter_type == "MarkdownTextSplitter"` in chunk metadata. |
| `test_base_enforce_min_chunk_size_idempotent` | M4 | Calling `_enforce_min_chunk_size` on a list where every chunk already satisfies the minimum returns the same list (byte-identical objects). |
| `test_base_create_chunks_legacy_path_unchanged` | M4 | Construct a custom `BaseTextSplitter` subclass with the legacy `create_chunks` path. Verify output is byte-identical to pre-refactor (snapshot test). |

### Integration Tests

| Test | Description |
|---|---|
| `test_existing_loader_tests_pass` | `pytest packages/ai-parrot/tests/loaders/ -v` returns green (zero regressions in `test_chunk_documents_atomic.py` and `test_late_chunking_threshold.py`). |
| `test_abstract_loader_default_uses_new_semantic` | Instantiate a minimal subclass of `AbstractLoader`. Assert `loader.text_splitter.__class__.__name__ == "SemanticTextSplitter"` and that `loader.text_splitter._rust.__class__.__name__ == "TextSplitter"` (i.e. the Rust object is wired underneath). |
| `test_chunk_documents_no_mid_word_cuts_for_long_doc` | Build a `Document` with `content_kind="trafilatura_main"` (NOT atomic) and a 5000-char body. Run through `_chunk_with_text_splitter`. Assert every output chunk satisfies the no-mid-word invariant. End-to-end smoke test that the new splitter actually fixes the underlying bug. |

### Test Data / Fixtures

```python
# tests/splitters/conftest.py
import pytest

AUTOPAY_FAQ = (
    "Q: How do I access my AT&T Prepaid account?\n\n"
    "A: You can access and manage your AT&T Prepaid account by logging "
    "into your AT&T Prepaid account. Your AT&T Prepaid account allows "
    "you to see your data usage, change your plan, check your balance, "
    "enroll & set up AutoPay."
)

def _no_mid_word(chunk: str, full_text: str) -> bool:
    """A chunk respects word boundaries when its first and last
    characters are either at the start/end of the source text or are
    bordered by whitespace in the source."""
    start = full_text.find(chunk)
    if start == -1:
        return False
    end = start + len(chunk)
    starts_clean = start == 0 or full_text[start - 1].isspace()
    ends_clean = end == len(full_text) or full_text[end].isspace() or chunk[-1] in ".!?,;:"
    return starts_clean and ends_clean


@pytest.fixture
def autopay_text() -> str:
    return AUTOPAY_FAQ
```

---

## 5. Acceptance Criteria

- [ ] `semantic-text-splitter>=0.30,<1.0` is in
  `packages/ai-parrot-loaders/pyproject.toml` and resolves via
  `uv pip install -e packages/ai-parrot-loaders`.
- [ ] `from parrot_loaders.splitters import (SemanticTextSplitter,
  MarkdownTextSplitter, TokenTextSplitter, BaseTextSplitter)` keeps
  working unchanged.
- [ ] `SemanticTextSplitter(chunk_size=512).split_text(AUTOPAY_FAQ)`
  produces at least one chunk that contains the substring
  `"set up AutoPay"` intact.
- [ ] No chunk produced by either new splitter ever ends mid-word
  (verified by the `_no_mid_word` predicate over a corpus of test
  fixtures including long-form content).
- [ ] `chunk_overlap` parameter is honored (consecutive chunks share at
  least 60% of the requested overlap — the Rust splitter is best-effort,
  not exact).
- [ ] `min_chunk_size` tail-merge produces zero chunks below the
  threshold at the tail.
- [ ] `tokenizer=` opt-in kwarg switches capacity to token-based
  (verified by chunk-count delta on a fixture text).
- [ ] `MarkdownTextSplitter` does not split inside fenced code blocks or
  between a Markdown header and its first body paragraph.
- [ ] `TextChunk.start_position` / `end_position` are character offsets
  that round-trip with `text[s:e] == chunk.text` for **every** chunk.
- [ ] `chunk_id` format and metadata structure (`chunk_index`,
  `total_chunks`, `splitter_type`) are byte-identical to today.
- [ ] All existing tests in `packages/ai-parrot/tests/loaders/` pass
  (no regressions).
- [ ] All existing tests in `packages/ai-parrot-loaders/tests/` (if any
  reference splitters) pass.
- [ ] `semantic.py` is ≤ 100 LOC after the rewrite (down from 435).
- [ ] `md.py` is ≤ 100 LOC after the rewrite (down from 228).
- [ ] `_chunk_with_text_splitter` for a non-atomic 5000-char doc
  produces only chunks that respect word boundaries (end-to-end smoke test).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# packages/ai-parrot-loaders/src/parrot_loaders/splitters/__init__.py:1-12
# All four exports remain after this spec — only internals of two change.
from parrot_loaders.splitters import BaseTextSplitter      # base.py:19
from parrot_loaders.splitters import MarkdownTextSplitter  # md.py:6 (REWRITE TARGET)
from parrot_loaders.splitters import TokenTextSplitter     # token.py:5 (UNCHANGED)
from parrot_loaders.splitters import SemanticTextSplitter  # semantic.py:27 (REWRITE TARGET)

# Internal
from parrot_loaders.splitters.base import TextChunk        # base.py:9 (UNCHANGED)

# New external dep (added by Module 1)
from semantic_text_splitter import TextSplitter, MarkdownSplitter
# verified at write time: PyPI page lists these classes for >=0.30
```

### Existing Class & Function Signatures

```python
# packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py
@dataclass                                                  # line 8
class TextChunk:                                            # line 9
    text: str
    start_position: int
    end_position: int
    token_count: int
    metadata: Dict[str, Any]
    chunk_id: Optional[str] = None

class BaseTextSplitter(ABC):                                # line 19
    def __init__(                                           # line 22
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        keep_separator: bool = True,
        add_start_index: bool = True,
        min_chunk_size: int = 0,
        **kwargs
    ): ...

    @abstractmethod
    def split_text(self, text: str) -> List[str]: ...        # line 38

    def create_chunks(                                       # line 42
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[TextChunk]: ...
        # min_chunk_size tail-merge logic lives at lines 84-106
        # — to be extracted to _enforce_min_chunk_size in Module 4

    def _count_tokens(self, text: str) -> int: ...           # line 110
        # default: int(len(text.split()) * 1.3)

# packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py
# REWRITE TARGET — current signature must be preserved at module surface:
class SemanticTextSplitter(BaseTextSplitter):                # line 27
    def __init__(                                            # line 45
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        min_chunk_size: int = 30,
        model_name: str = "gpt-4",       # legacy — accept but drop
        encoding_name: Optional[str] = None,    # legacy
        sentence_endings: Optional[str] = None, # legacy
        preserve_code_blocks: bool = True,      # legacy
        preserve_tables: bool = True,           # legacy
        **kwargs
    ): ...

# packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py
# REWRITE TARGET — same pattern (verified file size 228 LOC)
class MarkdownTextSplitter(BaseTextSplitter):                # md.py:6
    def __init__(                                            # md.py:19
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        ...
    ): ...

# packages/ai-parrot-loaders/src/parrot_loaders/splitters/token.py
# UNCHANGED — keep as-is.
class TokenTextSplitter(BaseTextSplitter):                   # token.py:5
    ...
```

### Single Consumer Site (verified)

```python
# packages/ai-parrot/src/parrot/loaders/abstract.py
from parrot_loaders.splitters import (                      # line 19-23
    TokenTextSplitter,
    MarkdownTextSplitter,
    SemanticTextSplitter,
)

# Default text_splitter wiring — NO CHANGE NEEDED:
# abstract.py:245-251
self.text_splitter = SemanticTextSplitter(
    chunk_size=self.chunk_size,
    chunk_overlap=self.chunk_overlap,
    min_chunk_size=self.min_chunk_size,
    model_name=kwargs.get('model_name', 'gpt-4'),  # silently dropped post-rewrite
)

# Default markdown_splitter wiring — NO CHANGE NEEDED:
# abstract.py:169-182 calls _get_markdown_splitter which builds
# MarkdownTextSplitter(chunk_size=4000, chunk_overlap=200)
```

### Integration Points

| New / Changed | Connects To | Via | Verified At |
|---|---|---|---|
| New `SemanticTextSplitter` body | `_setup_text_splitters` default | constructor with same kwargs | `abstract.py:245-251` |
| New `MarkdownTextSplitter` body | `_get_markdown_splitter` default | constructor with same kwargs | `abstract.py:169-182` |
| `_enforce_min_chunk_size` (new helper) | both new wrappers | called inside their `create_chunks` overrides | new code in `base.py` |
| `semantic-text-splitter` PyPI dep | `pyproject.toml` of ai-parrot-loaders | `dependencies = [ ... ]` block | `pyproject.toml:28-33` |
| Existing `chunk_documents` | new wrappers | calls `splitter.create_chunks(text, metadata)` | `abstract.py:1289-1384` |

### Existing Tests (must keep passing)

```python
# packages/ai-parrot/tests/loaders/test_chunk_documents_atomic.py
#   — uses MinimalLoader without a real splitter; should NOT break
# packages/ai-parrot/tests/loaders/test_late_chunking_threshold.py
#   — uses _chunk_with_late_chunking, doesn't touch text_splitter
# Verified: no other test files import the splitters directly
# (grep -rln "SemanticTextSplitter\|MarkdownTextSplitter\|TokenTextSplitter"
#   over packages/{ai-parrot,ai-parrot-loaders}/tests confirms this)
```

### Real-World Bug Evidence

```python
# Production case: examples/chatbots/att/bot.py:34-44
# Configures vector_store='postgres', table='att.concierge', schema='att'.
# After ingestion via WebScrapingLoader → SemanticTextSplitter,
# the SQL probe:
#   SELECT document FROM att.concierge WHERE document ILIKE '%autopay%';
# returns chunks ending with "...allows you to see your data us"
# while the source text continues "...usage, change your plan,
# check your balance, enroll & set up AutoPay."
# Resolution path: TRUNCATE att.concierge → reload via flowtask after
# this spec ships.
```

### Rust Library Surface (verified at spec write time, PyPI 0.30.x)

```python
from semantic_text_splitter import TextSplitter, MarkdownSplitter

# Char-based (default mode for our wrappers)
splitter = TextSplitter(capacity=512, overlap=50)
chunks: list[str] = splitter.chunks(text)
indices: list[tuple[int, str]] = splitter.chunk_indices(text)
# indices yield (BYTE_OFFSET, chunk_text) — wrapper must convert
# byte offsets to char offsets when text contains non-ASCII

# Token-based (HF tokenizer)
splitter = TextSplitter.from_huggingface_tokenizer(tokenizer, capacity=512, overlap=50)

# Token-based (tiktoken)
splitter = TextSplitter.from_tiktoken_model("gpt-4", capacity=512, overlap=50)

# Markdown variant — same constructors, respects MD structure
md_splitter = MarkdownSplitter(capacity=512, overlap=50)
```

### Does NOT Exist (Anti-Hallucination)

- ~~`semantic_text_splitter.SentenceSplitter`~~ — only `TextSplitter`
  and `MarkdownSplitter` exist in the public Python API of `>=0.30`.
- ~~`TextSplitter(min_capacity=..., max_capacity=...)`~~ — the Rust lib
  supports tuple capacity `TextSplitter(capacity=(min, max))`, not separate
  kwargs. We pass a single int (`chunk_size`); the tuple form is an
  open question in §8.
- ~~`TextSplitter(...).split(text)`~~ — the method is `chunks(text)`,
  not `split`.
- ~~`TextChunk.byte_start` / `byte_end`~~ — our dataclass exposes
  `start_position` / `end_position` only, and they are character offsets
  by contract.
- ~~`BaseTextSplitter._enforce_min_chunk_size`~~ — does not exist yet,
  Module 4 creates it.
- ~~`SemanticTextSplitter._init_tokenizer`~~ — exists in the current
  custom impl (`semantic.py:74`) but goes away after the rewrite.
- ~~A second consumer of `SemanticTextSplitter` outside `abstract.py`~~
  — verified via `grep -rln` over `packages/`, `examples/`, `agents/`:
  the only consumer in source code is
  `packages/ai-parrot/src/parrot/loaders/abstract.py`. Tests reference
  the names but do not instantiate. The "44 import sites" figure
  initially mentioned in the brainstorm prompt was incorrect — actual
  count is 1 production consumer + 1 test file (the FAQ atomic test
  introduced this session).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

#### 7.1 Tail-merge helper extraction

Extract the existing tail-merge from `BaseTextSplitter.create_chunks`
(`base.py:84-106`) into a method on `BaseTextSplitter`:

```python
# In base.py — add after _count_tokens, do not change create_chunks
def _enforce_min_chunk_size(
    self, chunks: List[TextChunk]
) -> List[TextChunk]:
    """Merge an undersized trailing chunk with its predecessor.

    No-op if min_chunk_size <= 0 or fewer than 2 chunks.
    """
    if self.min_chunk_size <= 0 or len(chunks) < 2:
        return chunks
    if chunks[-1].token_count >= self.min_chunk_size:
        return chunks
    # ... move the existing merge logic here ...
```

Then change `create_chunks` to call `self._enforce_min_chunk_size(chunks)`
instead of having the merge inline. The behavior must be byte-identical
(snapshot-tested in M4).

#### 7.2 Byte-vs-char offsets

`TextSplitter.chunk_indices` returns **byte** offsets (UTF-8). Our
`TextChunk.start_position` / `end_position` contract is **character**
offsets. For ASCII text the two coincide; for non-ASCII (CJK, emoji,
accented Spanish) they diverge. The wrapper MUST convert:

```python
# Convert byte offset to char offset by encoding-decoding the prefix.
# This is O(N) per chunk in the worst case but called once per
# create_chunks; acceptable.
def _byte_to_char(text: str, byte_offset: int) -> int:
    return len(text.encode("utf-8")[:byte_offset].decode("utf-8", errors="ignore"))
```

A unit test with a non-ASCII fixture (`"Café — naïve résumé. ✨"`) is
mandatory in M2 and M3 to catch this.

#### 7.3 Logging contract

Exactly one INFO line at construction. No per-chunk logging (would flood
logs at scale).

```python
self.logger.info(
    "Using semantic-text-splitter (Rust) chunk_size=%d capacity=%s overlap=%d",
    self.chunk_size,
    "tokens" if self._tokenizer_used else "chars",
    self.chunk_overlap,
)
```

Use `logging.getLogger(__name__)` at module level, like the existing
`semantic.py:12`.

### Known Risks / Gotchas

- **Risk: silent ABI / API drift in `semantic-text-splitter`.**
  Mitigation: pin `>=0.30,<1.0`. The library is at 0.30.x and pre-1.0
  semver gives the author room to break things; we cap at <1.0 to force
  an explicit upgrade decision later.
- **Risk: byte-offset confusion** (see 7.2). Mitigation: dedicated
  unit test with non-ASCII text in both M2 and M3.
- **Risk: `chunk_overlap` semantics differ.** The current Python
  splitter measures overlap in tokens; the Rust splitter measures in the
  same units as `capacity` (chars or tokens). If a consumer passes
  `chunk_overlap=50` expecting "50 tokens" but `tokenizer=` is omitted,
  they get "50 chars". Mitigation: document in the wrapper docstring.
  Existing call sites use defaults, so no live breakage.
- **Risk: legacy kwargs silently dropped surprise an operator.** A
  user passing `preserve_code_blocks=False` today expects code blocks to
  be split; after the rewrite that kwarg is dropped and Markdown code
  fences will be preserved by `MarkdownSplitter` regardless. This is a
  behavior change disguised as a noop. Mitigation: emit a single
  WARNING log (not INFO) listing any legacy kwargs that were dropped, so
  operators see it in their logs and can decide if they care.
- **Risk: dependency install fails on exotic platforms.** The Rust
  library ships pre-built wheels for Linux x86_64 / aarch64, macOS, and
  Windows — covers our targets. Source-build fallback exists but
  requires Rust toolchain. Mitigation: document in the dep PR description.
- **Risk: `create_chunks` snapshot test catches false-positive
  regressions** if any hidden behavior of the legacy code (e.g. how it
  handles trailing whitespace) is not reproduced verbatim. Mitigation:
  the snapshot test is for the **legacy `BaseTextSplitter` path**, not
  for the new wrappers. The new wrappers are tested against semantic
  invariants (no mid-word, offset round-trip, overlap honored), not
  byte-identical output of the old splitter — that would be impossible
  by design (we want different, better output).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `semantic-text-splitter` | `>=0.30,<1.0` | Rust-backed splitter, replaces 660 LOC of custom Python |

No other dependency changes. The `tokenizers` and `tiktoken` packages
are already transitively available (used by HuggingFace and OpenAI
clients respectively); no new direct adds.

---

## 8. Open Questions

- [ ] Should we expose the Rust splitter's tuple capacity form
      `capacity=(min, max)` (lower+upper bounds, lets the splitter target
      a comfortable size band rather than just an upper limit) — or keep
      the existing single `chunk_size` int for API stability?
      *Owner: Jesus*. **Default if undecided at implementation:** keep
      single int. Add tuple support later if a use case emerges.
- [ ] For `MarkdownSplitter`, the Rust lib supports `with_trim` to strip
      whitespace from chunk boundaries. Default to True (cleaner chunks)
      or False (preserve original spacing for byte-accurate offsets)?
      *Owner: Jesus*. **Default if undecided:** False. Keeping spacing
      makes the offset round-trip invariant trivially true; consumers
      that want trimming can `.strip()` themselves.
- [ ] Migration approach: emit a one-release `DeprecationWarning` from
      the old splitter constructors before the rewrite, or hard cutover
      in this spec? *Owner: Jesus*. **Recommendation in §1:** hard
      cutover. The classes are internal implementation; the public API
      is `loader.load(split_documents=True)` which is unchanged. No user
      ever instantiates `SemanticTextSplitter` directly outside of
      `abstract.py`.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (one worktree, all 6 modules
  sequential).
- **Rationale**: All modules touch a tightly-coupled set of files
  (`splitters/{base,semantic,md}.py`, `pyproject.toml`, one new test
  file). Parallel execution would conflict immediately. Sequential is
  faster end-to-end and lets each module's tests guard the next.
- **Cross-feature dependencies**: none. This spec is independent of
  FEAT-140 (embeddings catalog update). Both can ship in either order.

Worktree creation (run from `dev`):

```bash
git checkout dev && git pull origin dev
git worktree add -b feat-141-rust-semantic-text-splitter \
  .claude/worktrees/feat-141-rust-semantic-text-splitter HEAD
cd .claude/worktrees/feat-141-rust-semantic-text-splitter
source .venv/bin/activate
uv pip install semantic-text-splitter   # smoke check before module 1
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-04 | Jesus Lara | Initial draft |
