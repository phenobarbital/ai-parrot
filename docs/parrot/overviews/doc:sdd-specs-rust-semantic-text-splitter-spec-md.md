---
type: Wiki Overview
title: 'Feature Specification: Rust-backed Semantic Text Splitter'
id: doc:sdd-specs-rust-semantic-text-splitter-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The current `SemanticTextSplitter` (`packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py`,
relates_to:
- concept: mod:parrot_loaders.splitters
  rel: mentions
---

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

…(truncated)…
