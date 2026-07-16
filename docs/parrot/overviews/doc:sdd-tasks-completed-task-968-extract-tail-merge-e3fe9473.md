---
type: Wiki Overview
title: 'TASK-968: Extract `_enforce_min_chunk_size` helper on `BaseTextSplitter`'
id: doc:sdd-tasks-completed-task-968-extract-tail-merge-helper-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 4 of FEAT-141. The `min_chunk_size` tail-merge logic currently
relates_to:
- concept: mod:parrot_loaders.splitters
  rel: mentions
---

# TASK-968: Extract `_enforce_min_chunk_size` helper on `BaseTextSplitter`

**Feature**: FEAT-141 — Rust-backed Semantic Text Splitter
**Spec**: `sdd/specs/rust-semantic-text-splitter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-141. The `min_chunk_size` tail-merge logic currently
lives inline inside `BaseTextSplitter.create_chunks`
(`packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py`,
lines 84-106). The two new Rust-backed wrappers (TASK-969 / TASK-970)
will override `create_chunks` and need to invoke the same merge logic
on their own `TextChunk` lists.

This task extracts the inline block into an idempotent helper method
`_enforce_min_chunk_size` on `BaseTextSplitter`, then changes
`create_chunks` to call it. **Behavior must be byte-identical** for the
legacy code path so existing consumers see no change.

Done before Modules 2/3 so the helper is available when the wrappers
are written.

Spec sections: §2 Architectural Design (point 5),
§3 Module 4, §7 "Patterns to Follow" (7.1).

---

## Scope

- Add a new method `_enforce_min_chunk_size(chunks: List[TextChunk]) -> List[TextChunk]`
  on `BaseTextSplitter` in
  `packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py`.
- Move the existing tail-merge body from `create_chunks` (lines 84-106)
  into the helper, **preserving exact semantics**:
    - No-op when `self.min_chunk_size <= 0` or `len(chunks) < 2`.
    - No-op when `chunks[-1].token_count >= self.min_chunk_size`.
    - Otherwise merge the last chunk's text into the previous chunk
      with `"\n\n"` separator, recompute `token_count` via
      `self._count_tokens`, copy the predecessor's `chunk_id`, drop the
      last chunk, and rewrite `total_chunks` on every remaining chunk
      to `len(chunks)`.
- Replace the inline block in `create_chunks` with
  `chunks = self._enforce_min_chunk_size(chunks)` (or equivalent).
- Add unit tests proving:
    - The legacy path produces output byte-identical to the
      pre-refactor implementation (snapshot a list of chunk dicts).
    - The helper is idempotent: calling it twice yields the same list.
    - The helper is a no-op on lists where every chunk is ≥ minimum.
    - `total_chunks` is updated consistently after a merge.

**NOT in scope**:
- Touching `_count_tokens`, `_merge_splits`, or `_get_overlap_splits`.
- Any change to the new Rust wrappers (TASK-969 / TASK-970 use this helper).
- Removing or renaming any existing public method.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py` | MODIFY | Add `_enforce_min_chunk_size`, refactor `create_chunks` to call it |
| `packages/ai-parrot-loaders/tests/splitters/__init__.py` | CREATE | Empty file (package marker) — only if `tests/splitters/` doesn't exist |
| `packages/ai-parrot-loaders/tests/splitters/test_base_min_chunk_size.py` | CREATE | Idempotency + legacy-path snapshot tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py:1-5 (current)
import re
import uuid
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py
@dataclass                                                    # line 8
class TextChunk:
    text: str
    start_position: int
    end_position: int
    token_count: int
    metadata: Dict[str, Any]
    chunk_id: Optional[str] = None

class BaseTextSplitter(ABC):                                  # line 19
    def __init__(                                             # line 22
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        keep_separator: bool = True,
        add_start_index: bool = True,
        min_chunk_size: int = 0,
        **kwargs
    ): ...

    @abstractmethod
    def split_text(self, text: str) -> List[str]: ...         # line 38

    def create_chunks(                                        # line 42
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[TextChunk]: ...
        # current tail-merge block: lines 84-106

    def _count_tokens(self, text: str) -> int: ...            # line 110
```

### Current Inline Tail-Merge (verbatim, lines 84-106) — to be extracted

```python
# Enforce min_chunk_size: merge undersized final chunk with previous
if self.min_chunk_size > 0 and len(chunks) >= 2:
    if chunks[-1].token_count < self.min_chunk_size:
        prev = chunks[-2]
        last = chunks[-1]
        merged_text = prev.text + "\n\n" + last.text
        merged_token_count = self._count_tokens(merged_text)
        # Update previous chunk with merged content
        chunks[-2] = TextChunk(
            text=merged_text,
            start_position=prev.start_position,
            end_position=last.end_position,
            token_count=merged_token_count,
            metadata={
                **prev.metadata,
                'total_chunks': prev.metadata.get('total_chunks', 1) - 1,
            },
            chunk_id=prev.chunk_id,
        )
        # Remove last chunk
        chunks.pop()
        # Update total_chunks in all remaining chunks
        for c in chunks:
            c.metadata['total_chunks'] = len(chunks)
```

### Does NOT Exist

- ~~`BaseTextSplitter._enforce_min_chunk_size`~~ — does not exist yet,
  this task creates it.
- ~~`BaseTextSplitter._merge_tail`~~ — do not invent a different name.
- ~~`TextChunk.with_text(...)`~~ — `TextChunk` has no helper methods,
  it's a plain dataclass; rebuild via `TextChunk(...)`.
- ~~A `Tuple` import~~ — not needed; the helper takes/returns `List[TextChunk]`.
- ~~`packages/ai-parrot-loaders/tests/splitters/`~~ directory — does not
  exist yet (verified at task-write time, only `tests/` flat files).
  The test file in this task creates it.

---

## Implementation Notes

### Pattern to Follow

```python
# In base.py — add immediately after _count_tokens (after current line 124)
def _enforce_min_chunk_size(
    self, chunks: List[TextChunk]
) -> List[TextChunk]:
    """Merge an undersized trailing chunk with its predecessor.

    No-op when min_chunk_size <= 0, when there are fewer than 2 chunks,
    or when the trailing chunk already meets the minimum.

    Idempotent: applying the helper twice yields the same list.
    """
    if self.min_chunk_size <= 0 or len(chunks) < 2:
        return chunks
    if chunks[-1].token_count >= self.min_chunk_size:
        return chunks

    prev = chunks[-2]
    last = chunks[-1]
    merged_text = prev.text + "\n\n" + last.text
    merged_token_count = self._count_tokens(merged_text)
    chunks[-2] = TextChunk(
        text=merged_text,
        start_position=prev.start_position,
        end_position=last.end_position,
        token_count=merged_token_count,
        metadata={
            **prev.metadata,
            'total_chunks': prev.metadata.get('total_chunks', 1) - 1,
        },
        chunk_id=prev.chunk_id,
    )
    chunks.pop()
    for c in chunks:
        c.metadata['total_chunks'] = len(chunks)
    return chunks
```

Then in `create_chunks`, replace the inline block (current lines 83-106)
with a single call:

```python
return self._enforce_min_chunk_size(chunks)
```

### Key Constraints

- The helper mutates `chunks` in place (matches current behavior) AND
  returns the list. Both are fine; tests should accept either contract.
- Preserve `chunk_id` of the predecessor on merge (the existing code does this).
- Do not change the merge separator — it's `"\n\n"`, keep it.
- Use `self._count_tokens` (not a free function) so subclasses that
  override token counting (e.g. `TokenTextSplitter` with tiktoken)
  continue to use their own counter on the merged text.
- The existing `create_chunks` produces chunks with metadata
  `chunk_index`, `total_chunks`, `splitter_type`, plus optionally
  `start_index` / `end_index`. The helper must not erase any of these.

### References in Codebase

- `packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py:84-106`
  — current inline implementation (the source of truth for the extracted
  behavior).
- `packages/ai-parrot-loaders/src/parrot_loaders/splitters/token.py:5`
  — `TokenTextSplitter` does not override `create_chunks`; it inherits
  the base method and therefore exercises the helper too. The legacy-path
  snapshot test should run through `TokenTextSplitter` to keep it black-box.

---

## Acceptance Criteria

- [ ] `BaseTextSplitter._enforce_min_chunk_size` exists and matches the
      pattern above.
- [ ] `BaseTextSplitter.create_chunks` calls `_enforce_min_chunk_size`
      instead of the inline merge block.
- [ ] `pytest packages/ai-parrot-loaders/tests/splitters/test_base_min_chunk_size.py -v`
      is green.
- [ ] All pre-existing tests pass:
      `pytest packages/ai-parrot-loaders/tests/ -v` and
      `pytest packages/ai-parrot/tests/loaders/ -v` show zero regressions.
- [ ] No linting errors:
      `ruff check packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py`.
- [ ] `from parrot_loaders.splitters import BaseTextSplitter, TextChunk`
      keeps working unchanged.

---

## Test Specification

```python
# packages/ai-parrot-loaders/tests/splitters/test_base_min_chunk_size.py
"""Tests for BaseTextSplitter._enforce_min_chunk_size and the
legacy create_chunks path (must remain byte-identical post-refactor)."""

import pytest
from parrot_loaders.splitters.base import BaseTextSplitter, TextChunk


class _DummySplitter(BaseTextSplitter):
    """Minimal concrete subclass for exercising the base behavior."""

    def split_text(self, text: str):
        # split into fixed-size pieces by whitespace tokens
        words = text.split()
        size = max(1, self.chunk_size)
        return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


@pytest.fixture
def splitter_min30() -> _DummySplitter:
    return _DummySplitter(chunk_size=10, min_chunk_size=30)


def _serialize(chunks):
    return [
        {
            "text": c.text,
            "start_position": c.start_position,
            "end_position": c.end_position,
            "token_count": c.token_count,
            "metadata": dict(c.metadata),
        }
        for c in chunks
    ]


class TestEnforceMinChunkSize:
    def test_noop_when_min_zero(self):
        s = _DummySplitter(chunk_size=10, min_chunk_size=0)
        chunks = s.create_chunks("a " * 50)
        again = s._enforce_min_chunk_size(list(chunks))
        assert _serialize(again) == _serialize(chunks)

    def test_noop_when_single_chunk(self, splitter_min30):
        chunks = splitter_min30.create_chunks("hello world")
        assert len(chunks) <= 1
        again = splitter_min30._enforce_min_chunk_size(list(chunks))
        assert _serialize(again) == _serialize(chunks)

    def test_idempotent(self, splitter_min30):
        chunks = splitter_min30.create_chunks("a " * 50)
        once = splitter_min30._enforce_min_chunk_size(list(chunks))
        twice = splitter_min30._enforce_min_chunk_size(list(once))
        assert _serialize(once) == _serialize(twice)

    def test_total_chunks_updated_after_merge(self):
        # Construct a scenario where the tail is undersized
        s = _DummySplitter(chunk_size=2, min_chunk_size=5)
        text = "alpha beta gamma delta epsilon"
        chunks = s.create_chunks(text)
        # All surviving chunks should agree on total_chunks
        totals = {c.metadata["total_chunks"] for c in chunks}
        assert len(totals) == 1
        assert totals.pop() == len(chunks)

    def test_legacy_path_preserves_metadata_keys(self, splitter_min30):
        chunks = splitter_min30.create_chunks(
            "a " * 80, metadata={"src": "fixture"}
        )
        for c in chunks:
            assert "chunk_index" in c.metadata
            assert "total_chunks" in c.metadata
            assert c.metadata["splitter_type"] == "_DummySplitter"
            assert c.metadata["src"] == "fixture"
```

---

## Agent Instructions

1. Read the spec sections referenced in **Context**.
2. Re-read `splitters/base.py` to confirm the line numbers in this
   contract still match (refactor first, code later).
3. Add `_enforce_min_chunk_size`; refactor `create_chunks`; run the
   new tests + the existing test suites.
4. Move this file to `sdd/tasks/completed/`, update `.index.json` → `done`,
   fill in Completion Note, commit.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-04
**Notes**: Extracted the tail-merge logic from `create_chunks` into
`_enforce_min_chunk_size` exactly as specified. Also removed the pre-existing
unused `import re` from `base.py` to satisfy ruff linting. All 6 tests pass.
**Deviations from spec**: Minor — also removed unused `import re` (pre-existing
lint issue in base.py); this is outside strict task scope but necessary for
the linting acceptance criterion.
