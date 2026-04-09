# TASK-636: AbstractLoader Defaults & Wiring

**Feature**: loader-failed-chunking
**Spec**: `sdd/specs/loader-failed-chunking.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-635
**Assigned-to**: unassigned

---

## Context

Module 4 from the spec. Wires the new `SemanticTextSplitter` as the default splitter
in `AbstractLoader`, raises `chunk_size` from 800 to 2048, adds `min_chunk_size` and
`full_document` parameters, and removes the legacy `token_size` attribute
(per resolved open question).

---

## Scope

- Change `chunk_size` default from 800 to 2048 (abstract.py:62).
- Remove `self.token_size` (abstract.py:64) — legacy, per owner decision.
- Add `self.min_chunk_size: int = kwargs.get('min_chunk_size', 50)` parameter.
- Add `self.full_document: bool = kwargs.get('full_document', True)` parameter.
- Modify `_setup_text_splitters()` to use `SemanticTextSplitter` as the default
  splitter instead of `MarkdownTextSplitter`.
- Modify `_select_splitter_for_content()`: route 'text' and 'markdown' content types
  to `SemanticTextSplitter`; keep 'code' routing to `TokenTextSplitter`.
- Pass `min_chunk_size` to splitter constructors.
- Write tests for the new defaults and wiring.

**NOT in scope**: Individual loader changes (TASK-637/638/639), SemanticTextSplitter
implementation (TASK-635).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/loaders/abstract.py` | MODIFY | New defaults, wiring, remove token_size |
| `tests/loaders/test_abstract_loader_defaults.py` | CREATE | Tests for new defaults |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader     # pdf.py:8
from parrot.stores.models import Document              # pdf.py:7
from parrot_loaders.splitters.base import BaseTextSplitter  # splitters/__init__.py:1
from parrot_loaders.splitters.md import MarkdownTextSplitter  # splitters/__init__.py:2
from parrot_loaders.splitters.token import TokenTextSplitter  # splitters/__init__.py:3
# After TASK-635:
from parrot_loaders.splitters.semantic import SemanticTextSplitter  # splitters/__init__.py (new)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/loaders/abstract.py
class AbstractLoader(ABC):                                           # line 35
    # Current __init__ defaults (lines 62-79):
    self.chunk_size: int = kwargs.get('chunk_size', 800)             # line 62 → CHANGE to 2048
    self.chunk_overlap: int = kwargs.get('chunk_overlap', 100)       # line 63 → keep
    self.token_size: int = kwargs.get('token_size', 20)              # line 64 → REMOVE
    self._use_markdown_splitter: bool = kwargs.get('use_markdown_splitter', True)  # line 77
    self._use_huggingface_splitter: bool = kwargs.get('use_huggingface_splitter', False)  # line 78
    self._auto_detect_content_type: bool = kwargs.get('auto_detect_content_type', True)  # line 79

    def _get_markdown_splitter(self, chunk_size, chunk_overlap,
                               strip_headers=False) -> MarkdownTextSplitter:  # line 138
    def _setup_text_splitters(self, tokenizer, text_splitter, kwargs):  # line 168
        # line 171-174: creates self.markdown_splitter
        # line 177-178: if _use_markdown_splitter: self.text_splitter = markdown_splitter
        # line 180-206: else: various TokenTextSplitter configurations

    def _detect_content_type(self, document: Document) -> str:       # line 331
    def _select_splitter_for_content(self, content_type: str):       # line 372
        # line 382-383: markdown → self.markdown_splitter
        # line 384-390: code → TokenTextSplitter(chunk_size=min(self.chunk_size, 2048))
        # line 392-393: default → self.text_splitter

    async def chunk_documents(self, documents, ...) -> List[Document]:  # line 978
    def _chunk_with_text_splitter(self, documents, ...) -> List[Document]:  # line 1008
```

### Does NOT Exist
- ~~`AbstractLoader.full_document`~~ — does not exist yet (YOU are adding it)
- ~~`AbstractLoader.min_chunk_size`~~ — does not exist yet (YOU are adding it)
- ~~`AbstractLoader._use_semantic_splitter`~~ — no such flag (do NOT create one)
- ~~`AbstractLoader.semantic_splitter`~~ — no such attribute yet

---

## Implementation Notes

### Changes to `__init__()` (around line 62):
```python
# BEFORE:
self.chunk_size: int = kwargs.get('chunk_size', 800)
self.chunk_overlap: int = kwargs.get('chunk_overlap', 100)
self.token_size: int = kwargs.get('token_size', 20)

# AFTER:
self.chunk_size: int = kwargs.get('chunk_size', 2048)
self.chunk_overlap: int = kwargs.get('chunk_overlap', 200)
self.min_chunk_size: int = kwargs.get('min_chunk_size', 50)
self.full_document: bool = kwargs.get('full_document', True)
# token_size removed entirely
```

### Changes to `_setup_text_splitters()` (line 168):
- Create a `SemanticTextSplitter` as the default instead of `MarkdownTextSplitter`.
- Still create `self.markdown_splitter` for explicit markdown use.
- When `_use_markdown_splitter=True` (default), use `SemanticTextSplitter` as
  `self.text_splitter` (not MarkdownTextSplitter).
- Pass `min_chunk_size` to the semantic splitter constructor.

### Changes to `_select_splitter_for_content()` (line 372):
```python
# BEFORE:
if content_type == 'markdown':
    return self.markdown_splitter
elif content_type == 'code':
    return TokenTextSplitter(...)
else:
    return self.text_splitter

# AFTER:
if content_type == 'code':
    return TokenTextSplitter(
        chunk_size=min(self.chunk_size, 2048),
        chunk_overlap=self.chunk_overlap,
        model_name='gpt-4'
    )
else:
    # Both 'markdown' and 'text' use semantic splitter
    return self.text_splitter  # which is now SemanticTextSplitter
```

### Key Constraints
- `_use_markdown_splitter` kwarg still accepted but its semantics change:
  it now means "use the smart default splitter" (SemanticTextSplitter).
- Users who explicitly pass `text_splitter=MarkdownTextSplitter(...)` still get it.
- `chunk_overlap` default also raised from 100 to 200 to match semantic chunks.
- Grep for any references to `self.token_size` in abstract.py before removing.

---

## Acceptance Criteria

- [ ] Default `chunk_size` is 2048
- [ ] Default `chunk_overlap` is 200
- [ ] `self.token_size` removed
- [ ] `self.min_chunk_size` parameter exists (default 50)
- [ ] `self.full_document` parameter exists (default True)
- [ ] `SemanticTextSplitter` is the default splitter
- [ ] `_select_splitter_for_content()` routes markdown and text to semantic splitter
- [ ] Code content still routes to `TokenTextSplitter`
- [ ] Passing explicit `text_splitter=` kwarg overrides the default
- [ ] All tests pass: `pytest tests/loaders/test_abstract_loader_defaults.py -v`

---

## Test Specification

```python
# tests/loaders/test_abstract_loader_defaults.py
import pytest
from parrot.loaders.abstract import AbstractLoader


class TestAbstractLoaderDefaults:
    def test_default_chunk_size_2048(self):
        """Default chunk_size is 2048."""
        # Need a concrete subclass to test
        # AbstractLoader is ABC, so use a minimal concrete implementation
        assert True  # Implement with concrete test loader

    def test_min_chunk_size_default_50(self):
        """Default min_chunk_size is 50."""
        assert True

    def test_full_document_default_true(self):
        """Default full_document is True."""
        assert True

    def test_token_size_removed(self):
        """token_size attribute no longer exists."""
        assert True

    def test_semantic_splitter_is_default(self):
        """Default text_splitter is SemanticTextSplitter."""
        assert True

    def test_explicit_chunk_size_override(self):
        """Passing chunk_size=800 explicitly still works."""
        assert True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/loader-failed-chunking.spec.md` for full context
2. **Check dependencies** — TASK-635 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — read `abstract.py` lines 60-80 and 168-206 and 372-393
4. **IMPORTANT**: Grep for `token_size` in `abstract.py` and any other files that reference it
   before removing — ensure no code depends on it
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** the changes
7. **Run tests**: `pytest tests/loaders/test_abstract_loader_defaults.py -v`
8. **Move this file** to `tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
