# TASK-633: BaseTextSplitter Enhancements

**Feature**: loader-failed-chunking
**Spec**: `sdd/specs/loader-failed-chunking.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task for FEAT-092. All subsequent splitter and loader changes depend on
`BaseTextSplitter` having `min_chunk_size` support and a default `_count_tokens()`
implementation. This is Module 1 from the spec.

---

## Scope

- Add `min_chunk_size: int = 0` parameter to `BaseTextSplitter.__init__()`.
- Make `_count_tokens()` non-abstract with a default word-based estimate implementation:
  `int(len(text.split()) * 1.3)`. Subclasses can still override.
- Modify `create_chunks()` to enforce minimum chunk size: if the last chunk has fewer
  tokens than `min_chunk_size`, merge it with the previous chunk.
- Write unit tests for the new behavior.

**NOT in scope**: SemanticTextSplitter (TASK-635), MarkdownTextSplitter fixes (TASK-634),
AbstractLoader changes (TASK-636).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py` | MODIFY | Add min_chunk_size, default _count_tokens, merge logic |
| `tests/loaders/test_base_splitter.py` | CREATE | Unit tests for new BaseTextSplitter behavior |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_loaders.splitters.base import BaseTextSplitter, TextChunk  # splitters/__init__.py:1, base.py:8
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/splitters/base.py:19
class BaseTextSplitter(ABC):
    def __init__(
        self,
        chunk_size: int = 4000,
        chunk_overlap: int = 200,
        keep_separator: bool = True,
        add_start_index: bool = True
    ):                                                    # line 22-28
        self.chunk_size = chunk_size                      # line 29
        self.chunk_overlap = chunk_overlap                # line 30
        self.keep_separator = keep_separator              # line 31
        self.add_start_index = add_start_index            # line 32

    @abstractmethod
    def split_text(self, text: str) -> List[str]:         # line 34

    def create_chunks(
        self, text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[TextChunk]:                                 # line 39
        # Iterates over split_text() results, creates TextChunk objects
        # Uses _count_tokens() for token_count field
        # Position tracking via text.find()

    @abstractmethod
    def _count_tokens(self, text: str) -> int:            # line 82

    def _merge_splits(self, splits: List[str], separator: str) -> List[str]:  # line 87
    def _get_overlap_splits(self, splits: List[str], separator: str) -> List[str]:  # line 121

@dataclass
class TextChunk:                                          # line 8
    text: str
    start_position: int
    end_position: int
    token_count: int
    metadata: Dict[str, Any]
    chunk_id: Optional[str] = None
```

### Does NOT Exist
- ~~`BaseTextSplitter.min_chunk_size`~~ — does not exist yet (YOU are adding it)
- ~~`BaseTextSplitter._count_tokens()` default implementation~~ — currently abstract (YOU are changing this)
- ~~`BaseTextSplitter.merge_small_chunks()`~~ — no such method exists

---

## Implementation Notes

### Pattern to Follow

The `min_chunk_size` enforcement should happen in `create_chunks()` after all chunks are
generated. Check if the last chunk's token_count < min_chunk_size and if so, merge it
with the previous chunk:

```python
# After generating all chunks in create_chunks():
if self.min_chunk_size > 0 and len(chunks) >= 2:
    if chunks[-1].token_count < self.min_chunk_size:
        # Merge last chunk text into previous
        prev = chunks[-2]
        last = chunks[-1]
        merged_text = prev.text + "\n\n" + last.text
        # Update prev chunk with merged content
        # Remove last chunk
```

### Key Constraints
- `_count_tokens()` must remain overridable (not final).
- Remove `@abstractmethod` from `_count_tokens()` but keep it as a regular method.
- Default implementation: `return int(len(text.split()) * 1.3)` (word-based estimate).
- `min_chunk_size=0` means no enforcement (backwards compatible default).
- Do NOT change `split_text()` — it stays abstract.

---

## Acceptance Criteria

- [ ] `BaseTextSplitter.__init__()` accepts `min_chunk_size: int = 0`
- [ ] `_count_tokens()` has a default implementation (no longer abstract)
- [ ] `create_chunks()` merges undersized final chunks when `min_chunk_size > 0`
- [ ] Existing `MarkdownTextSplitter` and `TokenTextSplitter` still work (they override `_count_tokens()`)
- [ ] All tests pass: `pytest tests/loaders/test_base_splitter.py -v`

---

## Test Specification

```python
# tests/loaders/test_base_splitter.py
import pytest
from parrot_loaders.splitters.base import BaseTextSplitter, TextChunk


class ConcreteTestSplitter(BaseTextSplitter):
    """Concrete splitter for testing (splits on double newline)."""
    def split_text(self, text: str):
        return [p.strip() for p in text.split('\n\n') if p.strip()]


class TestBaseTextSplitterEnhancements:
    def test_min_chunk_size_parameter(self):
        """min_chunk_size parameter accepted and stored."""
        splitter = ConcreteTestSplitter(chunk_size=100, min_chunk_size=10)
        assert splitter.min_chunk_size == 10

    def test_min_chunk_size_default_zero(self):
        """Default min_chunk_size is 0 (no enforcement)."""
        splitter = ConcreteTestSplitter()
        assert splitter.min_chunk_size == 0

    def test_default_count_tokens(self):
        """Default _count_tokens uses word-based estimate."""
        splitter = ConcreteTestSplitter()
        count = splitter._count_tokens("hello world foo bar")
        assert count > 0  # should be ~5 (4 words * 1.3)

    def test_merge_undersized_final_chunk(self):
        """Final chunk below min_chunk_size is merged with previous."""
        splitter = ConcreteTestSplitter(chunk_size=5000, min_chunk_size=10)
        text = "This is a long paragraph with enough words to pass the minimum.\n\nTiny."
        chunks = splitter.create_chunks(text)
        # "Tiny." alone has ~1 token, should be merged with previous
        assert len(chunks) == 1

    def test_no_merge_when_min_chunk_size_zero(self):
        """No merging when min_chunk_size is 0."""
        splitter = ConcreteTestSplitter(chunk_size=5000, min_chunk_size=0)
        text = "First paragraph.\n\nSecond paragraph."
        chunks = splitter.create_chunks(text)
        assert len(chunks) == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/loader-failed-chunking.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — read `splitters/base.py` to confirm signatures
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the changes to `BaseTextSplitter`
6. **Run tests**: `pytest tests/loaders/test_base_splitter.py -v`
7. **Move this file** to `tasks/completed/TASK-633-base-splitter-enhancements.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
