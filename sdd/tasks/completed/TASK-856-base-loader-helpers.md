# TASK-856: Base loader helpers — basepdf and basevideo build_default_meta

**Feature**: FEAT-125 — AI-Parrot Loaders Metadata Standardization
**Spec**: `sdd/specs/ai-parrot-loaders-metadata-standarization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-855
**Assigned-to**: unassigned

---

## Context

`BasePDF` and `BaseVideoLoader` are abstract-ish base classes extended by
concrete loaders (`pdf.py`, `pdfmark.py`, `pdftables.py`, `video.py`,
`videolocal.py`, `videounderstanding.py`, `audio.py`, `youtube.py`, `vimeo.py`).

This task adds a `build_default_meta(...)` convenience helper to each base
class. The helper wraps `create_metadata` with sensible PDF/video defaults,
so subclass refactors (later tasks) stay short and consistent.

Additionally, `BaseVideoLoader._language` is aliased to `self.language` from
`AbstractLoader` to avoid breaking subclasses that reference it.

Implements **Module 4** of the spec.

---

## Scope

- Add `build_default_meta(self, path, *, language=None, title=None, **kwargs) -> dict` to `BasePDF`:
  - Calls `self.create_metadata(path, doctype=self.doctype, source_type=self._source_type, language=language, title=title, **kwargs)`.
  - Returns the metadata dict.
- Add `build_default_meta(self, path, *, language=None, title=None, **kwargs) -> dict` to `BaseVideoLoader`:
  - Calls `self.create_metadata(path, doctype='video_transcript', source_type='video', language=language or self._language, title=title, **kwargs)`.
  - Returns the metadata dict.
- In `BaseVideoLoader.__init__`, ensure `self._language` assignment is preserved but also pass `language` up to `super().__init__(..., language=language)`:
  - Currently `super().__init__` is called WITHOUT `language=`. After TASK-855, `AbstractLoader.__init__` accepts `language`. Thread it through.
  - Keep `self._language = language` as a read-only alias (`@property` that returns `self.language`) for backward compat — one release deprecation.
- In `BasePDF.__init__`, pass `language` through to `super().__init__` if supplied (currently `BasePDF` has `self._lang = 'eng'` on line 34 — this is an OCR language code, not the document language; leave it alone, it serves a different purpose).

**NOT in scope**: Refactoring any concrete loader emit sites. Changing `_load` methods.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/basepdf.py` | MODIFY | Add `build_default_meta` helper |
| `packages/ai-parrot-loaders/src/parrot_loaders/basevideo.py` | MODIFY | Add `build_default_meta` helper, thread `language` to super, add `_language` property alias |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader  # used by both basepdf.py and basevideo.py
from parrot.stores.models import Document            # basevideo.py:13
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/basepdf.py
class BasePDF(AbstractLoader):                                      # line 9
    extensions: set[str] = {'.pdf'}                                 # line 13

    def __init__(
        self,
        source=None,
        *,
        tokenizer=None,
        text_splitter=None,
        source_type: str = 'file',
        as_markdown: bool = False,
        use_chapters: bool = False,
        use_pages: bool = False,
        **kwargs
    ):                                                              # line 15
        super().__init__(source, tokenizer=tokenizer, text_splitter=text_splitter,
                         source_type=source_type, **kwargs)
        self._lang = 'eng'          # OCR language code, NOT document language  # line 34
        self.doctype = 'pdf'                                        # line 35
        self._source_type = source_type                             # line 36
```

```python
# packages/ai-parrot-loaders/src/parrot_loaders/basevideo.py
class BaseVideoLoader(AbstractLoader):                              # line 46
    extensions: List[str] = ['.youtube']                            # line 50

    def __init__(
        self,
        source=None,
        tokenizer=None,
        text_splitter=None,
        source_type: str = 'video',
        language: str = "en",
        video_path=None,
        download_video: bool = True,
        diarization: bool = False,
        **kwargs
    ):                                                              # line 53
        super().__init__(source, tokenizer=tokenizer, text_splitter=text_splitter,
                         source_type=source_type, **kwargs)         # line 67
        # NOTE: language is NOT passed to super().__init__ today
        self._language = language                                   # line 98
```

```python
# After TASK-855, AbstractLoader gains:
# AbstractLoader.__init__(..., language: str = 'en', ...)
# AbstractLoader.create_metadata(..., *, language=None, title=None, **kwargs)
# AbstractLoader._derive_title(path) -> str
# AbstractLoader._validate_metadata(metadata) -> dict
```

### Does NOT Exist
- ~~`BasePDF.build_default_meta`~~ — does not exist; this task adds it.
- ~~`BaseVideoLoader.build_default_meta`~~ — does not exist; this task adds it.
- ~~`BaseVideoLoader.language`~~ — today only `_language` exists (line 98). After TASK-855, `self.language` will be set by `AbstractLoader.__init__`.
- ~~`BasePDF.language`~~ — does not exist until TASK-855 adds it via `AbstractLoader`.

---

## Implementation Notes

### Pattern to Follow
```python
# basevideo.py — thread language to super and add alias + helper
class BaseVideoLoader(AbstractLoader):
    def __init__(self, ..., language: str = "en", ...):
        super().__init__(
            source, tokenizer=tokenizer, text_splitter=text_splitter,
            source_type=source_type, language=language, **kwargs  # ADD language=
        )
        # Keep _language as deprecated alias
        # self._language = language  ← REMOVE direct assignment

    @property
    def _language(self) -> str:
        return self.language

    @_language.setter
    def _language(self, value: str):
        self.language = value

    def build_default_meta(self, path, *, language=None, title=None, **kwargs) -> dict:
        return self.create_metadata(
            path,
            doctype='video_transcript',
            source_type='video',
            language=language or self.language,
            title=title,
            **kwargs
        )
```

### Key Constraints
- `BasePDF._lang` (line 34) is for OCR (`'eng'`), not document language — leave it unchanged.
- `BaseVideoLoader.__init__` currently does NOT pass `language` to `super().__init__`. This task must add it.
- The `_language` property alias is for backward compat only; subclasses that read `self._language` must keep working.
- `build_default_meta` is a thin wrapper — no I/O, no side effects.

### References in Codebase
- `packages/ai-parrot-loaders/src/parrot_loaders/basevideo.py` — line 67 (super call), line 98 (_language)
- `packages/ai-parrot-loaders/src/parrot_loaders/basepdf.py` — line 27 (super call)

---

## Acceptance Criteria

- [ ] `BasePDF.build_default_meta(path)` returns a dict with canonical `document_meta`
- [ ] `BaseVideoLoader.build_default_meta(path)` returns a dict with canonical `document_meta` and `doctype='video_transcript'`
- [ ] `BaseVideoLoader.__init__` passes `language=language` to `super().__init__`
- [ ] `self._language` is a property alias for `self.language` on `BaseVideoLoader`
- [ ] Existing subclasses referencing `self._language` still work
- [ ] `BasePDF._lang` (OCR code) is unchanged
- [ ] Tests pass: `pytest packages/ai-parrot-loaders/tests/ -v -k "basepdf or basevideo or video or audio"`

---

## Test Specification

```python
# packages/ai-parrot-loaders/tests/test_base_loader_helpers.py
import pytest
from pathlib import Path


CANONICAL_DOC_META_KEYS = {"source_type", "category", "type", "language", "title"}


class TestBasePDFHelper:
    def test_build_default_meta_canonical_shape(self):
        from parrot_loaders.basepdf import BasePDF
        # BasePDF is abstract; use a minimal concrete subclass
        class ConcretePDF(BasePDF):
            async def _load(self, path, **kwargs):
                return []
        loader = ConcretePDF()
        meta = loader.build_default_meta(Path("/tmp/test.pdf"))
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert meta["type"] == "pdf"


class TestBaseVideoLoaderHelper:
    def test_build_default_meta_canonical_shape(self):
        from parrot_loaders.basevideo import BaseVideoLoader
        class ConcreteVideo(BaseVideoLoader):
            async def _load(self, source, **kwargs):
                return []
        loader = ConcreteVideo(language="es")
        meta = loader.build_default_meta("https://example.com/video.mp4")
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert meta["document_meta"]["language"] == "es"
        assert meta["type"] == "video_transcript"

    def test_language_alias(self):
        from parrot_loaders.basevideo import BaseVideoLoader
        class ConcreteVideo(BaseVideoLoader):
            async def _load(self, source, **kwargs):
                return []
        loader = ConcreteVideo(language="fr")
        assert loader._language == "fr"
        assert loader.language == "fr"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-855 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Confirm TASK-855 changes are present (AbstractLoader.language, create_metadata with language/title)
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-856-base-loader-helpers.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker-feat-125
**Date**: 2026-04-27
**Notes**: Implemented as specified. Added `build_default_meta` to both `BasePDF` and `BaseVideoLoader`. `BaseVideoLoader` now threads `language` to `super().__init__` and provides `_language` property alias. 17 tests all pass.

**Deviations from spec**: Updated root `conftest.py` to add parrot-loaders/src to sys.path and navigator stubs — needed for parrot-loaders tests to collect.
