# TASK-634: Fix MarkdownTextSplitter Character-vs-Token Bugs

**Feature**: loader-failed-chunking
**Spec**: `sdd/specs/loader-failed-chunking.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-633
**Assigned-to**: unassigned

---

## Context

The MarkdownTextSplitter has a critical inconsistency: `_merge_markdown_sections()`,
`_split_large_section()`, and `_get_overlap_content()` all use `len()` (character count)
to compare against `chunk_size`, while `_count_tokens()` uses `words * 1.3`. This means
the splitter operates in mixed units. Per spec open question resolution, this must be
fixed as a side-effect even though SemanticTextSplitter replaces it as default.

This is an additional task derived from the resolved open question in Section 8 of the spec.

---

## Scope

- Replace all `len()` calls in `_merge_markdown_sections()` with `self._count_tokens()`.
- Replace all `len()` calls in `_split_large_section()` with `self._count_tokens()`.
- Replace all `len()` calls in `_get_overlap_content()` with `self._count_tokens()`.
- Write unit tests verifying the fix.

**NOT in scope**: Changing `_count_tokens()` implementation (it stays as `words * 1.3`),
creating SemanticTextSplitter (TASK-635), any loader changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py` | MODIFY | Replace len() with _count_tokens() in 3 methods |
| `tests/loaders/test_markdown_splitter_fix.py` | CREATE | Unit tests for the fix |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_loaders.splitters.md import MarkdownTextSplitter  # splitters/__init__.py:2
from parrot_loaders.splitters.base import BaseTextSplitter     # splitters/__init__.py:1
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/splitters/md.py
class MarkdownTextSplitter(BaseTextSplitter):                        # line 6

    def _count_tokens(self, text: str) -> int:                       # line 44
        """Count tokens (approximation using words for markdown)"""
        words = len(text.split())
        return int(words * 1.3)  # Rough token approximation

    def _merge_markdown_sections(self, sections: List[Dict[str, Any]]) -> List[str]:  # line 142
        # BUG lines to fix:
        # line 153: section_size = len(section_text)    → self._count_tokens(section_text)
        # line 156: if section_size > self.chunk_size   → (already uses self.chunk_size, just fix the unit)
        # line 169: if current_size + section_size > self.chunk_size  → same
        # line 176: current_size = sum(len(part) for part in current_chunk_parts)
        #           → sum(self._count_tokens(part) for part in current_chunk_parts)

    def _split_large_section(self, text: str) -> List[str]:          # line 187
        # BUG lines to fix:
        # line 197: para_size = len(paragraph)    → self._count_tokens(paragraph)
        # line 199: if current_size + para_size > self.chunk_size  → (already correct comparison)
        # line 202: current_size = para_size      → (already correct variable name)

    def _get_overlap_content(self, parts: List[str]) -> List[str]:   # line 212
        # BUG lines to fix:
        # line 222: if overlap_size + len(part) <= self.chunk_overlap
        #           → overlap_size + self._count_tokens(part) <= self.chunk_overlap
```

### Does NOT Exist
- ~~`MarkdownTextSplitter._count_chars()`~~ — no such method
- ~~`MarkdownTextSplitter.use_token_counting`~~ — no such flag

---

## Implementation Notes

### Key Changes

Each `len()` call that measures text size against `chunk_size` or `chunk_overlap` must
be replaced with `self._count_tokens()`. This is a simple find-and-replace within 3 methods.

**In `_merge_markdown_sections()` (line 142):**
```python
# Before (line 153):
section_size = len(section_text)
# After:
section_size = self._count_tokens(section_text)

# Before (line 176):
current_size = sum(len(part) for part in current_chunk_parts)
# After:
current_size = sum(self._count_tokens(part) for part in current_chunk_parts)
```

**In `_split_large_section()` (line 187):**
```python
# Before (line 197):
para_size = len(paragraph)
# After:
para_size = self._count_tokens(paragraph)
```

**In `_get_overlap_content()` (line 212):**
```python
# Before (line 222):
if overlap_size + len(part) <= self.chunk_overlap:
# After:
if overlap_size + self._count_tokens(part) <= self.chunk_overlap:
```

### Key Constraints
- Do NOT change `_count_tokens()` implementation — it stays as `words * 1.3`.
- Do NOT change the overall algorithm (parse → merge → split).
- The fix only ensures consistent units throughout the class.

---

## Acceptance Criteria

- [ ] No `len()` calls used for size comparison against `chunk_size` or `chunk_overlap` in md.py
- [ ] `_merge_markdown_sections()` uses `_count_tokens()` for all size measurements
- [ ] `_split_large_section()` uses `_count_tokens()` for all size measurements
- [ ] `_get_overlap_content()` uses `_count_tokens()` for overlap measurement
- [ ] All tests pass: `pytest tests/loaders/test_markdown_splitter_fix.py -v`
- [ ] Existing MarkdownTextSplitter tests (if any) still pass

---

## Test Specification

```python
# tests/loaders/test_markdown_splitter_fix.py
import pytest
from parrot_loaders.splitters.md import MarkdownTextSplitter


class TestMarkdownSplitterTokenConsistency:
    def test_chunk_size_in_tokens_not_chars(self):
        """Chunks respect chunk_size in tokens, not characters."""
        # chunk_size=50 tokens ≈ ~38 words
        splitter = MarkdownTextSplitter(chunk_size=50, chunk_overlap=0)
        # Create text with 100+ words across sections
        text = "# Section 1\n\n" + " ".join(["word"] * 60) + "\n\n# Section 2\n\n" + " ".join(["word"] * 60)
        chunks = splitter.split_text(text)
        # Should produce multiple chunks, not one giant chunk
        assert len(chunks) >= 2

    def test_small_sections_merged_by_tokens(self):
        """Small sections are merged until token limit, not char limit."""
        splitter = MarkdownTextSplitter(chunk_size=100, chunk_overlap=0)
        text = "# A\n\nShort.\n\n# B\n\nAlso short.\n\n# C\n\nStill short."
        chunks = splitter.split_text(text)
        # All sections are small in tokens — should merge into fewer chunks
        assert len(chunks) <= 2

    def test_large_section_split_by_tokens(self):
        """Oversized sections split at paragraph boundaries using token count."""
        splitter = MarkdownTextSplitter(chunk_size=30, chunk_overlap=0)
        long_text = "# Big Section\n\n" + "\n\n".join(
            [" ".join(["word"] * 20) for _ in range(5)]
        )
        chunks = splitter.split_text(long_text)
        assert len(chunks) >= 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/loader-failed-chunking.spec.md` for full context
2. **Check dependencies** — TASK-633 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — read `splitters/md.py` to confirm line numbers
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the len() → _count_tokens() replacements
6. **Run tests**: `pytest tests/loaders/test_markdown_splitter_fix.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
