---
type: Wiki Overview
title: 'TASK-970: Rewrite `MarkdownTextSplitter` as a thin Rust wrapper'
id: doc:sdd-tasks-completed-task-970-rewrite-markdown-text-splitter-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 3 of FEAT-141. Mirrors TASK-969 but for the Markdown splitter.
relates_to:
- concept: mod:parrot_loaders.splitters
  rel: mentions
---

# TASK-970: Rewrite `MarkdownTextSplitter` as a thin Rust wrapper

**Feature**: FEAT-141 — Rust-backed Semantic Text Splitter
**Spec**: `sdd/specs/rust-semantic-text-splitter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-967, TASK-968
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-141. Mirrors TASK-969 but for the Markdown splitter.
Replaces the 228-LOC custom implementation in
`packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py` with a
thin (~80 LOC) wrapper around `semantic_text_splitter.MarkdownSplitter`.

The Markdown variant of the Rust splitter respects fenced code blocks,
headers, list items, and blockquotes natively — exactly the behavior
the legacy implementation tries (and partially fails) to recreate via
regex.

The class name and module path are preserved. Consumer call sites
(`AbstractLoader._get_markdown_splitter` at
`packages/ai-parrot/src/parrot/loaders/abstract.py:169-182`) keep working
unchanged.

This task is **independent** of TASK-969 at the file level (different
file), but per the spec's worktree strategy (§Worktree Strategy) it runs
sequentially in the same worktree because both share the dep introduced
by TASK-967.

Spec sections: §3 Module 3, §6 Codebase Contract, §7.2 Byte-vs-char
offsets, §7.3 Logging contract, §8 open question on `with_trim`.

---

## Scope

- **Delete** the body of `packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py`
  including `header_pattern`, `code_block_pattern`, and any private
  helpers used only by the legacy algorithm.
- **Rewrite** the file as a wrapper that:
  1. Inherits `BaseTextSplitter`.
  2. Accepts the current constructor kwargs (`chunk_size`,
     `chunk_overlap`, `strip_headers`, `return_each_line`, `**kwargs`).
  3. Adds the same `tokenizer` opt-in kwarg as `SemanticTextSplitter`
     for parity (so a user who switches between the two doesn't get
     surprises).
  4. Builds `self._rust = MarkdownSplitter(...)` choosing char- /
     HF-tokenizer- / tiktoken-based mode (same selection logic as
     TASK-969).
  5. Implements `split_text(text) -> List[str]` via
     `self._rust.chunks(text)`.
  6. Overrides `create_chunks(text, metadata) -> List[TextChunk]` using
     `chunk_indices` + the byte→char converter, then calls
     `self._enforce_min_chunk_size(chunks)`.
  7. Logs **one INFO** line at construction:
     `"Using semantic-text-splitter (Rust, Markdown) chunk_size=N capacity=chars|tokens overlap=M"`.
  8. Accepts legacy kwargs (`strip_headers`, `return_each_line`) but
     silently drops them — the Rust `MarkdownSplitter` handles those
     concerns natively. Emit a single WARNING line if either is set to
     a non-default value, matching the pattern in TASK-969.
- Target ≤ 100 LOC for the entire `md.py` after the rewrite.

**Open-question default (per spec §8):** do NOT enable `with_trim`.
Keep boundary spacing intact so the offset round-trip invariant
`text[s:e] == chunk.text` holds trivially. If the consumer wants
trimmed chunks they can `.strip()` themselves.

**NOT in scope**:
- Touching `SemanticTextSplitter` (TASK-969) or `BaseTextSplitter`
  (TASK-968).
- Adding new tests beyond a smoke import (full test suite is TASK-971).
- Tuple-capacity (`capacity=(min, max)`) support — keep single int.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py` | REWRITE | 228 LOC → ≤ 100 LOC wrapper |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_loaders.splitters.base import BaseTextSplitter, TextChunk
# base.py:9   TextChunk
# base.py:19  BaseTextSplitter
# base.py:_NEW_  _enforce_min_chunk_size  (added by TASK-968)

from semantic_text_splitter import MarkdownSplitter
# verified surface (PyPI 0.30.x):
#   MarkdownSplitter(capacity, overlap=0)
#   MarkdownSplitter.from_huggingface_tokenizer(tokenizer, capacity, overlap=0)
#   MarkdownSplitter.from_tiktoken_model(model, capacity, overlap=0)
#   .chunks(text) -> list[str]
#   .chunk_indices(text) -> list[tuple[int, str]]   (byte offsets)

import logging
import uuid
from typing import Any, Dict, List, Optional, Union
```

### Existing Class Signature (current — to be replaced)

```python
# packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py
class MarkdownTextSplitter(BaseTextSplitter):                 # line 6
    def __init__(                                             # line 17
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        strip_headers: bool = False,
        return_each_line: bool = False,
        **kwargs,
    ):
        super().__init__(chunk_size, chunk_overlap, **kwargs)  # line 34
        self.strip_headers = strip_headers
        self.return_each_line = return_each_line
        # ... regex compilations and helpers (228 LOC total) ...
```

### Required Public Constructor After Rewrite

```python
class MarkdownTextSplitter(BaseTextSplitter):
    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        strip_headers: bool = False,        # legacy — accept, drop
        return_each_line: bool = False,     # legacy — accept, drop
        min_chunk_size: int = 0,
        tokenizer: Optional[Union[str, Any]] = None,
        **kwargs,
    ):
        ...
```

The current consumer at `abstract.py:178-182` calls
`MarkdownTextSplitter(chunk_size=4000, chunk_overlap=200)` — that signature
must keep working. Adding `min_chunk_size` and `tokenizer` is additive.

### Single Consumer (no change required)

```python
# packages/ai-parrot/src/parrot/loaders/abstract.py:174-182
def _get_markdown_splitter(self, ...) -> MarkdownTextSplitter:
    """Create a MarkdownTextSplitter with common settings."""
    return MarkdownTextSplitter(
        chunk_size=...,
        chunk_overlap=...,
    )
```

### Does NOT Exist

- ~~`MarkdownSplitter.with_trim(True)`~~ — `with_trim` is a builder
  pattern argument in the Rust API but on the Python binding it is a
  constructor kwarg `trim=True`. Per spec §8 default, do NOT pass it
  (the lib defaults match what we want).
- ~~`MarkdownSplitter.split(text)`~~ — method is `chunks(text)`.
- ~~`MarkdownTextSplitter.from_*` factory classmethods on our wrapper~~
  — do not invent these. The constructor handles all modes via the
  `tokenizer` kwarg.
- ~~Regex constants `header_pattern`, `code_block_pattern`~~ — these go
  away with the legacy body. Do not preserve them as module constants.

---

## Implementation Notes

### Pattern to Follow

Mirror the structure in TASK-969 closely. The only differences:

1. Import `MarkdownSplitter` instead of `TextSplitter`.
2. The legacy-kwarg list is `("strip_headers", "return_each_line")`.
3. The INFO log line names the Markdown variant:
   `"Using semantic-text-splitter (Rust, Markdown) chunk_size=N capacity=... overlap=M"`.
4. Keep the same byte→char helper. Either re-import it from
   `.semantic` or duplicate it locally — both are acceptable; if
   importing, make sure the import does not create a circular
   dependency (it shouldn't — `.semantic` doesn't import from `.md`).

```python
"""Rust-backed Markdown splitter.

Thin wrapper around semantic_text_splitter.MarkdownSplitter. The
underlying Rust implementation respects fenced code blocks, headers,
lists, and blockquotes natively.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional, Union

from semantic_text_splitter import MarkdownSplitter

from .base import BaseTextSplitter, TextChunk
from .semantic import _byte_to_char  # reuse to avoid duplication

logger = logging.getLogger(__name__)

_LEGACY_KWARGS = ("strip_headers", "return_each_line")


class MarkdownTextSplitter(BaseTextSplitter):
    """Markdown-aware splitter backed by the Rust crate.

    Respects fenced code blocks, headers, lists, blockquotes. Never
    cuts a fence in half; never splits between a header and its first
    body sentence.
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        strip_headers: bool = False,
        return_each_line: bool = False,
        min_chunk_size: int = 0,
        tokenizer: Optional[Union[str, Any]] = None,
        **kwargs,
    ):
        super().__init__(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            min_chunk_size=min_chunk_size,
            **kwargs,
        )
        if tokenizer is None:
            self._rust = MarkdownSplitter(
                capacity=chunk_size, overlap=chunk_overlap,
            )
            self._capacity_unit = "chars"
        elif isinstance(tokenizer, str):
            self._rust = MarkdownSplitter.from_tiktoken_model(
                tokenizer, capacity=chunk_size, overlap=chunk_overlap,
            )
            self._capacity_unit = "tokens"
        else:
            self._rust = MarkdownSplitter.from_huggingface_tokenizer(
                tokenizer, capacity=chunk_size, overlap=chunk_overlap,
            )
            self._capacity_unit = "tokens"

        logger.info(
            "Using semantic-text-splitter (Rust, Markdown) "
            "chunk_size=%d capacity=%s overlap=%d",
            chunk_size, self._capacity_unit, chunk_overlap,
        )
        if strip_headers or return_each_line:
            logger.warning(
                "MarkdownTextSplitter ignored legacy kwargs: %s "
                "(handled natively by the Rust splitter)",
                ", ".join(
                    name for name, val in (
                        ("strip_headers", strip_headers),
                        ("return_each_line", return_each_line),
                    ) if val
                ),
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

- `splitter_type` in metadata MUST be exactly `"MarkdownTextSplitter"`
  (driven by `self.__class__.__name__` — keep it that way).
- One INFO log at construction; one WARNING only when legacy kwargs are
  set non-default; no per-chunk logs.
- `min_chunk_size` defaults to `0` (matching the legacy class), unlike
  `SemanticTextSplitter` which defaults to `30`. Do not change this
  default — it changes existing behavior for the markdown path.
- The reuse of `_byte_to_char` from `.semantic` is preferred but if
  TASK-969 hasn't been merged yet, copy the helper locally and TODO it
  for dedup once both are in.

### References in Codebase

- `packages/ai-parrot-loaders/src/parrot_loaders/splitters/semantic.py`
  (after TASK-969) — pattern source.
- `packages/ai-parrot/src/parrot/loaders/abstract.py:169-182` — single
  consumer.
- Spec §8 → `with_trim` open question (default: do not enable).

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py`
      is ≤ 100 LOC.
- [ ] `from parrot_loaders.splitters import MarkdownTextSplitter`
      keeps working.
- [ ] `MarkdownTextSplitter(chunk_size=4000, chunk_overlap=200)`
      constructs without error (matches the consumer call at
      `abstract.py:178-182`).
- [ ] For a markdown text containing a fenced code block longer than
      `chunk_size`, `split_text` never produces a chunk that breaks the
      fence (one chunk contains the entire fence, or chunks split
      cleanly at fence boundaries — never mid-fence).
- [ ] For a markdown text `# Header\n\nbody1\n\n## H2\n\nbody2`,
      consecutive chunks never split between a header and its first
      body line.
- [ ] `text[chunk.start_position:chunk.end_position] == chunk.text`
      holds for every chunk produced by `create_chunks` (round-trip
      offset invariant).
- [ ] Construction emits exactly one INFO log line.
- [ ] No linting errors:
      `ruff check packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py`.
- [ ] Pre-existing tests pass:
      `pytest packages/ai-parrot-loaders/tests/ -v` and
      `pytest packages/ai-parrot/tests/loaders/ -v`.

---

## Test Specification

Smoke check inline; comprehensive tests in TASK-971.

```python
from parrot_loaders.splitters import MarkdownTextSplitter

md = """# Title

Some intro paragraph that's long enough to matter.

## Section A

```python
def hello():
    print("a code block longer than chunk size " * 20)
```

## Section B

A list:

- item one
- item two
- item three
"""

s = MarkdownTextSplitter(chunk_size=200, chunk_overlap=20)
chunks = s.split_text(md)
assert chunks
# No fence-mid-cut: each chunk has either zero or an even number of ``` markers
for c in chunks:
    assert c.count("```") % 2 == 0, f"fence broken in chunk: {c!r}"

# Offset round-trip
typed = s.create_chunks(md)
for c in typed:
    assert md[c.start_position:c.end_position] == c.text
    assert c.metadata["splitter_type"] == "MarkdownTextSplitter"
```

---

## Agent Instructions

1. Read the spec sections in **Context**.
2. Confirm TASK-967 (dep), TASK-968 (helper), TASK-969 (semantic
   wrapper, where `_byte_to_char` lives) are in
   `sdd/tasks/completed/`.
3. Re-verify the codebase contract; confirm the import path
   `from .semantic import _byte_to_char` resolves after TASK-969.
4. Rewrite `md.py` per the pattern; keep ≤ 100 LOC.
5. Run smoke checks above and the existing test suites.
6. Move this file to `sdd/tasks/completed/`, update `.index.json` →
   `done`, fill in Completion Note, commit.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-04
**Notes**: Rewrote md.py as specified. Final file is 87 LOC (target ≤100). 
Reuses _byte_to_char from .semantic as specified. min_chunk_size defaults to 0
(matching legacy behaviour). All smoke checks pass including fence preservation,
offset round-trip, and consumer API compatibility.
**Deviations from spec**: none
