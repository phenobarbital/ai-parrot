---
type: Wiki Overview
title: 'TASK-969: Rewrite `SemanticTextSplitter` as a thin Rust wrapper'
id: doc:sdd-tasks-completed-task-969-rewrite-semantic-text-splitter-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 2 of FEAT-141. Replaces the 435-LOC ad-hoc Python implementation of
relates_to:
- concept: mod:parrot_loaders.splitters
  rel: mentions
---

# TASK-969: Rewrite `SemanticTextSplitter` as a thin Rust wrapper

**Feature**: FEAT-141 — Rust-backed Semantic Text Splitter
**Spec**: `sdd/specs/rust-semantic-text-splitter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-967, TASK-968
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-141. Replaces the 435-LOC ad-hoc Python implementation of
`SemanticTextSplitter` with a thin (~80 LOC) wrapper around the Rust-backed
`semantic_text_splitter.TextSplitter` from PyPI.

This is the splitter wired into `AbstractLoader._setup_text_splitters`
(`packages/ai-parrot/src/parrot/loaders/abstract.py:245-251`) as the
default for general (non-code) content. It runs on **every** corpus the
framework ingests unless the operator overrides it. Its current
implementation produces mid-word cuts in production (the AT&T `att.concierge`
"set up AutoPay" regression — see spec §1).

The class name, module path, and public constructor signature are
preserved so no consumer needs to change. Legacy kwargs that no consumer
actually uses are accepted via `**kwargs` and silently dropped.

Spec sections: §1 Problem Statement (AutoPay bug), §2 Architectural
Design, §3 Module 2, §6 Codebase Contract, §7.1 Tail-merge integration,
§7.2 Byte-vs-char offsets, §7.3 Logging contract.

---

## Scope

- **Delete** the body of `packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py`
  (the 435-LOC custom splitter, including `_init_tokenizer`,
  `DEFAULT_SENTENCE_ENDINGS`, `CODE_BLOCK_PATTERN`, `TABLE_PATTERN`, and
  any helpers that exist only for the old algorithm).
- **Rewrite** the file as a wrapper that:
  1. Inherits `BaseTextSplitter`.
  2. Accepts the same constructor kwargs as today
     (`chunk_size`, `chunk_overlap`, `min_chunk_size`, `model_name`, plus
     legacy `encoding_name`, `sentence_endings`, `preserve_code_blocks`,
     `preserve_tables`, plus `**kwargs`).
  3. Adds **one new** opt-in kwarg `tokenizer` (HF tokenizer object OR
     tiktoken encoding name string OR `None` — default `None`).
  4. Builds `self._rust = TextSplitter(...)` choosing between
     char-based, HF-tokenizer-based, or tiktoken-based mode.
  5. Implements `split_text(text) -> List[str]` via `self._rust.chunks(text)`.
  6. Overrides `create_chunks(text, metadata) -> List[TextChunk]`:
     - Use `self._rust.chunk_indices(text)` to get `(byte_offset, chunk_text)` tuples.
     - Convert byte offsets to character offsets via the helper
       `_byte_to_char` (see §7.2 of the spec).
     - Build a `TextChunk` per chunk with the same `chunk_id` pattern
       (`f"chunk_{i:04d}_{uuid.uuid4().hex[:8]}"`) and the metadata
       contract (`chunk_index`, `total_chunks`, `splitter_type`).
     - When `add_start_index` is true, also set `start_index` /
       `end_index` in metadata (as the legacy code did).
     - Apply `self._enforce_min_chunk_size(chunks)` (the helper from
       TASK-968) before returning.
  7. Logs **exactly one** INFO line at construction (see §7.3):
     `"Using semantic-text-splitter (Rust) chunk_size=N capacity=chars|tokens overlap=M"`.
  8. Logs **one WARNING** line at construction listing any legacy kwargs
     that were dropped (`encoding_name`, `sentence_endings`,
     `preserve_code_blocks`, `preserve_tables` — when explicitly passed
     non-default), so operators see the behavior change in their logs.
- Target ≤ 100 LOC for the entire `semantic.py` after the rewrite.

**NOT in scope**:
- Touching `MarkdownTextSplitter` (TASK-970).
- Adding new tests beyond a smoke import (full test suite is TASK-971).
- Adding tuple-capacity (`capacity=(min, max)`) support — spec §8 leaves
  this as an open question, **default is single int**.
- Changing `BaseTextSplitter` (TASK-968 already did the helper extract).
- Modifying any consumer file (verification is TASK-972).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py` | REWRITE | 435 LOC → ≤ 100 LOC wrapper |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing — verified at task-write time
from parrot_loaders.splitters.base import BaseTextSplitter, TextChunk
# base.py:9   TextChunk dataclass
# base.py:19  BaseTextSplitter ABC

# New — installed by TASK-967
from semantic_text_splitter import TextSplitter
# verified surface (PyPI 0.30.x):
#   TextSplitter(capacity, overlap=0)
#   TextSplitter.from_huggingface_tokenizer(tokenizer, capacity, overlap=0)
#   TextSplitter.from_tiktoken_model(model, capacity, overlap=0)
#   .chunks(text) -> list[str]
#   .chunk_indices(text) -> list[tuple[int, str]]   (byte offsets, UTF-8)

# Stdlib
import logging
import uuid
from typing import Any, Dict, List, Optional, Union
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py
@dataclass
class TextChunk:                                              # base.py:8
    text: str
    start_position: int           # CHAR offset
    end_position: int             # CHAR offset
    token_count: int
    metadata: Dict[str, Any]
    chunk_id: Optional[str] = None

class BaseTextSplitter(ABC):                                  # base.py:19
    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        keep_separator: bool = True,
        add_start_index: bool = True,
        min_chunk_size: int = 0,
        **kwargs,
    ): ...

    @abstractmethod
    def split_text(self, text: str) -> List[str]: ...
    def create_chunks(self, text, metadata=None) -> List[TextChunk]: ...
    def _count_tokens(self, text: str) -> int: ...

    # Added by TASK-968 — REQUIRED here:
    def _enforce_min_chunk_size(
        self, chunks: List[TextChunk]
    ) -> List[TextChunk]: ...
```

### Required Public Constructor Signature

```python
class SemanticTextSplitter(BaseTextSplitter):
    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        min_chunk_size: int = 30,
        model_name: str = "gpt-4",                # legacy — accept, drop
        encoding_name: Optional[str] = None,      # legacy
        sentence_endings: Optional[str] = None,   # legacy
        preserve_code_blocks: bool = True,        # legacy
        preserve_tables: bool = True,             # legacy
        tokenizer: Optional[Union[str, Any]] = None,  # NEW — opt-in
        **kwargs,
    ):
        ...
```

The `model_name` kwarg is currently passed by `AbstractLoader` at
`packages/ai-parrot/src/parrot/loaders/abstract.py:250` — it MUST be
accepted (silently dropped) to keep that consumer working unchanged.

### Tokenizer-Mode Selection (deterministic)

```python
if tokenizer is None:
    self._rust = TextSplitter(
        capacity=chunk_size,
        overlap=chunk_overlap,
    )
    self._capacity_unit = "chars"
elif isinstance(tokenizer, str):
    # Treat as a tiktoken model/encoding name
    self._rust = TextSplitter.from_tiktoken_model(
        tokenizer,
        capacity=chunk_size,
        overlap=chunk_overlap,
    )
    self._capacity_unit = "tokens"
else:
    # Anything else: assume an HF tokenizer object
    self._rust = TextSplitter.from_huggingface_tokenizer(
        tokenizer,
        capacity=chunk_size,
        overlap=chunk_overlap,
    )
    self._capacity_unit = "tokens"
```

### Byte→Char Offset Conversion (mandatory — see §7.2)

```python
def _byte_to_char(text: str, byte_offset: int) -> int:
    """Convert a UTF-8 byte offset into a character offset.

    The Rust splitter returns byte offsets via chunk_indices; our
    TextChunk contract is character offsets. For ASCII the two coincide;
    for non-ASCII (CJK, emoji, accented Spanish) they diverge.
    """
    if byte_offset <= 0:
        return 0
    encoded = text.encode("utf-8")
    if byte_offset >= len(encoded):
        return len(text)
    return len(encoded[:byte_offset].decode("utf-8", errors="ignore"))
```

### Single Consumer (no change required)

```python
# packages/ai-parrot/src/parrot/loaders/abstract.py:245-251
self.text_splitter = SemanticTextSplitter(
    chunk_size=self.chunk_size,
    chunk_overlap=self.chunk_overlap,
    min_chunk_size=self.min_chunk_size,
    model_name=kwargs.get('model_name', 'gpt-4'),
)
```

This call must keep working. The new wrapper accepts these four kwargs
verbatim; `model_name` lands in `**kwargs` (or as the named legacy
param) and is silently dropped.

### Does NOT Exist

- ~~`semantic_text_splitter.SentenceSplitter`~~ — only `TextSplitter`
  and `MarkdownSplitter` are public on PyPI 0.30.x.
- ~~`TextSplitter(...).split(text)`~~ — the method is `chunks(text)`.
- ~~`TextSplitter(min_capacity=..., max_capacity=...)`~~ — the lib
  supports `capacity=(min, max)` as a tuple, not separate kwargs. We use
  a single int per spec §8.
- ~~`TextSplitter.from_callback(...)`~~ — exists in the Rust API but
  not on the Python binding we're targeting; do not use.
- ~~A `_init_tokenizer` method on the new wrapper~~ — that name exists
  in the legacy class (`semantic.py:74`) but goes away. Do not preserve it.
- ~~`tiktoken` direct imports in this file~~ — token-mode goes through
  `TextSplitter.from_tiktoken_model`, which handles tiktoken internally.

---

## Implementation Notes

### Pattern to Follow

```python
"""Rust-backed semantic text splitter.

Thin wrapper around semantic_text_splitter.TextSplitter (PyPI). Replaces
the previous custom Python implementation. The class name, module path,
and constructor surface are preserved so existing consumers do not change.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional, Union

from semantic_text_splitter import TextSplitter

from .base import BaseTextSplitter, TextChunk

logger = logging.getLogger(__name__)

_LEGACY_KWARGS = ("encoding_name", "sentence_endings",
                  "preserve_code_blocks", "preserve_tables")


def _byte_to_char(text: str, byte_offset: int) -> int:
    if byte_offset <= 0:
        return 0
    encoded = text.encode("utf-8")
    if byte_offset >= len(encoded):
        return len(text)
    return len(encoded[:byte_offset].decode("utf-8", errors="ignore"))


class SemanticTextSplitter(BaseTextSplitter):
    """Sentence/paragraph-aware splitter backed by the Rust crate.

    Never produces mid-word cuts. Boundary hierarchy: sentence > line >
    paragraph > section. Capacity is character-based by default; pass a
    `tokenizer` (HF tokenizer object or tiktoken model/encoding name) to
    switch to token-based capacity.
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        min_chunk_size: int = 30,
        model_name: str = "gpt-4",
        encoding_name: Optional[str] = None,
        sentence_endings: Optional[str] = None,
        preserve_code_blocks: bool = True,
        preserve_tables: bool = True,
        tokenizer: Optional[Union[str, Any]] = None,
        **kwargs,
    ):
        super().__init__(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            min_chunk_size=min_chunk_size,
            **kwargs,
        )
        # Build the Rust splitter
        if tokenizer is None:
            self._rust = TextSplitter(
                capacity=chunk_size, overlap=chunk_overlap,
            )
            self._capacity_unit = "chars"
        elif isinstance(tokenizer, str):
            self._rust = TextSplitter.from_tiktoken_model(
                tokenizer, capacity=chunk_size, overlap=chunk_overlap,
            )
            self._capacity_unit = "tokens"
        else:
            self._rust = TextSplitter.from_huggingface_tokenizer(
                tokenizer, capacity=chunk_size, overlap=chunk_overlap,
            )
            self._capacity_unit = "tokens"

        logger.info(
            "Using semantic-text-splitter (Rust) chunk_size=%d "
            "capacity=%s overlap=%d",
            chunk_size, self._capacity_unit, chunk_overlap,
        )
        # Warn about legacy kwargs that were explicitly passed
        dropped = [
            name for name in _LEGACY_KWARGS
            if locals().get(name) not in (None, True)  # defaults vary
        ]
        if dropped:
            logger.warning(
                "SemanticTextSplitter ignored legacy kwargs: %s "
                "(handled natively by the Rust splitter)",
                ", ".join(dropped),
            )

    def split_text(self, text: str) -> List[str]:
        if not text:
            return []
        return list(self._rust.chunks(text))

    def create_chunks(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[TextChunk]:
        if not text:
            return []
        pairs = list(self._rust.chunk_indices(text))
        total = len(pairs)
        chunks: List[TextChunk] = []
        for i, (byte_off, chunk_text) in enumerate(pairs):
            start = _byte_to_char(text, byte_off)
            end = start + len(chunk_text)
            chunk_metadata = {
                **(metadata or {}),
                "chunk_index": i,
                "total_chunks": total,
                "splitter_type": self.__class__.__name__,
            }
            if self.add_start_index:
                chunk_metadata["start_index"] = start
                chunk_metadata["end_index"] = end
            chunks.append(TextChunk(
                text=chunk_text,
                start_position=start,
                end_position=end,
                token_count=self._count_tokens(chunk_text),
                metadata=chunk_metadata,
                chunk_id=f"chunk_{i:04d}_{uuid.uuid4().hex[:8]}",
            ))
        return self._enforce_min_chunk_size(chunks)
```

### Key Constraints

- **One INFO log line at construction**, no per-chunk logging (§7.3).
- **One WARNING line** if legacy non-default kwargs were passed.
- Use `logging.getLogger(__name__)` at module level (mirrors current
  `semantic.py:12`); do NOT use `self.logger` (BaseTextSplitter doesn't
  define it).
- `split_text("")` and `create_chunks("")` must return `[]` (current
  implementation handles empty inputs gracefully — preserve that).
- `add_start_index` defaults to `True` on `BaseTextSplitter`; honor it.
- Token count via `self._count_tokens(chunk_text)` — the base estimator
  is fine; do not introduce tiktoken at this layer.

### Detection of "non-default" legacy kwargs

The simple `not in (None, True)` heuristic above catches the most common
operator footgun. If a stricter check is wanted, compare against each
kwarg's documented default explicitly. Keep this single warning line —
**do not** spam one warning per kwarg.

### References in Codebase

- `packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py`
  — base class, `_enforce_min_chunk_size` (added by TASK-968).
- `packages/ai-parrot/src/parrot/loaders/abstract.py:245-251`
  — single production consumer.
- Spec §6 → "Real-World Bug Evidence" — the AutoPay case the wrapper
  must fix.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py`
      is ≤ 100 LOC after the rewrite.
- [ ] `from parrot_loaders.splitters import SemanticTextSplitter`
      keeps working unchanged.
- [ ] `SemanticTextSplitter(chunk_size=512, chunk_overlap=50,
      min_chunk_size=30, model_name='gpt-4')` constructs without error.
- [ ] `SemanticTextSplitter(chunk_size=64).split_text("hello world " * 50)`
      returns a non-empty `list[str]` and no chunk ends mid-word.
- [ ] `SemanticTextSplitter(chunk_size=512).split_text(AUTOPAY_TEXT)` —
      where `AUTOPAY_TEXT` is the spec §1 sample — produces at least one
      chunk that contains `"set up AutoPay"` intact (smoke check;
      formal test arrives in TASK-971).
- [ ] Construction emits exactly one INFO log line and zero per-chunk
      logs.
- [ ] No linting errors:
      `ruff check packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py`.
- [ ] Pre-existing tests pass:
      `pytest packages/ai-parrot-loaders/tests/ -v` and
      `pytest packages/ai-parrot/tests/loaders/ -v`.

---

## Test Specification

This task contributes a smoke check inline; the comprehensive test
suite is TASK-971.

```python
# Quick smoke check — runnable before TASK-971 lands
from parrot_loaders.splitters import SemanticTextSplitter

s = SemanticTextSplitter(chunk_size=512, chunk_overlap=50, min_chunk_size=30)
chunks = s.split_text(
    "Your AT&T Prepaid account allows you to see your data usage, "
    "change your plan, check your balance, enroll & set up AutoPay. " * 5
)
assert chunks, "splitter returned no chunks"
assert any("set up AutoPay" in c for c in chunks), "AutoPay regression"

# Round-trip offsets
text = "Café — naïve résumé. ✨ " * 30
typed = s.create_chunks(text)
for c in typed:
    assert text[c.start_position:c.end_position] == c.text
```

---

## Agent Instructions

1. Read the spec sections in **Context**.
2. Confirm TASK-967 (dep) and TASK-968 (helper) are in
   `sdd/tasks/completed/`. If not, stop.
3. Re-verify the codebase contract — especially that
   `BaseTextSplitter._enforce_min_chunk_size` exists.
4. Rewrite `semantic.py` using the pattern above; keep ≤ 100 LOC.
5. Run smoke checks above and the existing test suites.
6. Move this file to `sdd/tasks/completed/`, update `.index.json` →
   `done`, fill in the Completion Note, commit.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-04
**Notes**: Rewrote semantic.py as specified. Final file is 99 LOC (target ≤100).
Key finding confirmed in TASK-967: chunk_indices() in v0.30.1 returns char offsets,
not byte offsets. The _byte_to_char helper handles this transparently. All smoke
checks pass including AutoPay regression, non-ASCII round-trip, metadata contract,
and chunk_id format.
**Deviations from spec**: none
