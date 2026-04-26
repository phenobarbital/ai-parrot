# TASK-859: Refactor YouTube and Vimeo loaders to use canonical metadata

**Feature**: FEAT-125 — AI-Parrot Loaders Metadata Standardization
**Spec**: `sdd/specs/ai-parrot-loaders-metadata-standarization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-855, TASK-856
**Assigned-to**: unassigned

---

## Context

YouTube and Vimeo loaders extend `BaseVideoLoader` and emit multiple Document
variants per video (full transcript, per-chunk transcript, SRT, VTT, dialog,
summaries). They also have streaming-specific extras like `video_id`, `channel`,
`topic_tags`, `duration`.

This is part of **Module 3** of the spec — split out from TASK-858 because these
loaders have their own large set of emit-sites and unique extras.

---

## Scope

- **`youtube.py`** (YoutubeLoader, extends BaseVideoLoader):
  - 4+ emit-site groups (lines 293, 366, 409, 467).
  - Each group may have per-chunk and full-doc variants.
  - Loader-specific keys to preserve at top level: `topic_tags`, `video_id`, `channel`, `duration`, `caption_language`.
  - Replace all raw `metadata = {...}` / `base_metadata = {...}` dicts with `self.create_metadata(...)` or `self.build_default_meta(...)` calls.

- **`vimeo.py`** (VimeoLoader, extends BaseVideoLoader):
  - 3+ emit sites (lines 16, 80, 115).
  - Loader-specific keys: `topic_tags`, `video_id`, `duration`.
  - Replace all raw metadata dicts.

**NOT in scope**: audio.py, video.py, videolocal.py, videounderstanding.py (TASK-858). web.py, webscraping.py (TASK-860).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/youtube.py` | MODIFY | Replace 4+ raw metadata dict groups with create_metadata calls |
| `packages/ai-parrot-loaders/src/parrot_loaders/vimeo.py` | MODIFY | Replace 3+ raw metadata dicts with create_metadata calls |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader     # abstract.py:36
from parrot.stores.models import Document              # stores/models.py:21
from parrot_loaders.basevideo import BaseVideoLoader   # basevideo.py:46
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/youtube.py
# Emit sites (raw metadata dicts):
#   base_metadata = {...}                                           # line 293
#   metadata = {...}                                                # line 366
#   metadata = {...}                                                # line 409
#   metadata = {...}                                                # line 467
# YoutubeLoader extends BaseVideoLoader

# packages/ai-parrot-loaders/src/parrot_loaders/vimeo.py
# Emit sites (raw metadata dicts):
#   metadata = {...}                                                # line 16
#   metadata={...}                                                  # line 64, 72, 92, 107
#   metadata = {...}                                                # line 115
# VimeoLoader extends BaseVideoLoader

# After TASK-855 + TASK-856:
# BaseVideoLoader.build_default_meta(path, *, language=None, title=None, **kwargs) -> dict
# AbstractLoader.create_metadata(path, doctype, source_type, doc_metadata, *, language=None, title=None, **kwargs) -> dict
# self.language: str (inherited)
```

### Does NOT Exist
- ~~`YoutubeLoader.create_metadata`~~ — inherits from BaseVideoLoader → AbstractLoader.
- ~~`VimeoLoader.build_default_meta`~~ — inherits from BaseVideoLoader after TASK-856.
- ~~`YoutubeLoader._language`~~ — will be a property alias after TASK-856; use `self.language`.

---

## Implementation Notes

### Refactor strategy
For each raw `metadata = { "url": ..., "source": ..., ... }`:
1. Identify the video URL/path and the Document variant type.
2. Call `self.build_default_meta(url, doctype="youtube_transcript", language=caption_lang, title=video_title, topic_tags=tags, video_id=vid, channel=channel, duration=dur)`.
3. All extras (`topic_tags`, `video_id`, `channel`, `duration`, etc.) go as `**kwargs` → top-level metadata.

### Key Constraints
- YouTube caption tracks may specify language — pass it as `language=` to override `self.language`.
- `topic_tags` is currently sometimes in `doc_metadata` — move to top level.
- Each emit-site group (per-chunk vs full-doc vs SRT) needs its own `doctype`.
- Do NOT change `__init__` signatures.

### References in Codebase
- `packages/ai-parrot-loaders/src/parrot_loaders/youtube.py`
- `packages/ai-parrot-loaders/src/parrot_loaders/vimeo.py`

---

## Acceptance Criteria

- [ ] `youtube.py` — all emit-site groups route through `create_metadata` or `build_default_meta`
- [ ] `vimeo.py` — all emit sites route through `create_metadata` or `build_default_meta`
- [ ] No raw `metadata = {...}` dicts remain in either file
- [ ] `topic_tags`, `video_id`, `channel`, `duration` at top level (not in `document_meta`)
- [ ] `document_meta` is closed-shape (5 canonical keys) on every emitted Document
- [ ] Caption language passed as `language=` when available
- [ ] Tests pass: `pytest packages/ai-parrot-loaders/tests/ -v -k "youtube or vimeo"`
- [ ] No breaking changes to loader public signatures

---

## Test Specification

```python
# packages/ai-parrot-loaders/tests/test_youtube_vimeo_metadata.py
import pytest

CANONICAL_DOC_META_KEYS = {"source_type", "category", "type", "language", "title"}


class TestYoutubeLoaderMetadata:
    def test_canonical_metadata_shape(self):
        from parrot_loaders.youtube import YoutubeLoader
        loader = YoutubeLoader(language="en")
        meta = loader.create_metadata(
            "https://youtube.com/watch?v=abc123",
            doctype="youtube_transcript",
            source_type="video",
            topic_tags=["AI", "ML"],
            video_id="abc123",
            channel="test_channel"
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "topic_tags" in meta
        assert "video_id" in meta
        assert "topic_tags" not in meta["document_meta"]

    def test_caption_language_propagates(self):
        from parrot_loaders.youtube import YoutubeLoader
        loader = YoutubeLoader(language="en")
        meta = loader.create_metadata(
            "https://youtube.com/watch?v=abc123",
            doctype="youtube_transcript",
            source_type="video",
            language="es"
        )
        assert meta["document_meta"]["language"] == "es"


class TestVimeoLoaderMetadata:
    def test_canonical_metadata_shape(self):
        from parrot_loaders.vimeo import VimeoLoader
        loader = VimeoLoader(language="en")
        meta = loader.create_metadata(
            "https://vimeo.com/123456",
            doctype="vimeo_transcript",
            source_type="video",
            video_id="123456",
            duration=120
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "video_id" in meta
        assert "duration" in meta
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-855 and TASK-856 are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm TASK-855 and TASK-856 changes are present
   - Read both loader files to verify emit-site line numbers
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-859-refactor-youtube-vimeo-loaders.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
