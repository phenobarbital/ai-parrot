# TASK-858: Refactor video/audio loaders to use canonical metadata

**Feature**: FEAT-125 — AI-Parrot Loaders Metadata Standardization
**Spec**: `sdd/specs/ai-parrot-loaders-metadata-standarization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-855, TASK-856
**Assigned-to**: unassigned

---

## Context

This task covers the video/audio portion of **Module 3** of the spec. These
loaders all extend `BaseVideoLoader` and emit multiple Document variants per
source (transcript, SRT, VTT, dialog chunks, summaries). Each emit-site must
be individually refactored to use `create_metadata` (or `build_default_meta`
from TASK-856).

The key challenge is that `audio.py` constructs `Document` objects directly
with raw `metadata` dicts inside loops, and each variant has different
loader-specific keys.

---

## Scope

Refactor the following loaders to route ALL metadata through `create_metadata`
or `build_default_meta`:

- **`audio.py`** (AudioLoader, extends BaseVideoLoader):
  - 7 emit sites (lines 18, 50, 71, 87, 104, 118, 146).
  - Each builds a raw `metadata = {...}` dict. Replace with `self.build_default_meta(...)` or `self.create_metadata(...)`.
  - Loader-specific keys to preserve at top level: `origin`, `vtt_path`, `transcript_path`, `srt_path`, `summary_path`, `summary`.
  - Replace `self._language` references with `self.language` (alias from TASK-856 makes this safe).

- **`video.py`** (VideoLoader, extends BaseVideoLoader):
  - Inherits transcription methods from `BaseVideoLoader`.
  - Verify all `Document` constructions use `create_metadata`.

- **`videolocal.py`** (VideoLocalLoader, extends BaseVideoLoader):
  - 4+ emit sites (lines 71, 125, 150–211).
  - Loader-specific keys: video timing, segment info.

- **`videounderstanding.py`** (VideoUnderstandingLoader, extends BaseVideoLoader):
  - Multiple emit sites (lines 195, 225, 239, 250, 256, 262, 289, 305, 319, 325, 339, 348, 360).
  - Loader-specific keys: model name, prompt id, scene timing, sections.

**NOT in scope**: youtube.py, vimeo.py (TASK-859). web.py, webscraping.py (TASK-860).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/audio.py` | MODIFY | Replace 7 raw metadata dicts with create_metadata/build_default_meta calls |
| `packages/ai-parrot-loaders/src/parrot_loaders/video.py` | MODIFY | Verify/refactor metadata construction |
| `packages/ai-parrot-loaders/src/parrot_loaders/videolocal.py` | MODIFY | Replace 4+ raw metadata dicts |
| `packages/ai-parrot-loaders/src/parrot_loaders/videounderstanding.py` | MODIFY | Replace 13+ raw metadata dicts |

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
# packages/ai-parrot-loaders/src/parrot_loaders/basevideo.py
class BaseVideoLoader(AbstractLoader):                              # line 46
    # After TASK-856:
    #   build_default_meta(path, *, language=None, title=None, **kwargs) -> dict
    #   self._language → property alias for self.language
    #   self.language set via AbstractLoader.__init__

# packages/ai-parrot-loaders/src/parrot_loaders/audio.py
class AudioLoader(BaseVideoLoader):                                 # line 8
    # Emit sites (raw metadata dicts):
    #   metadata = {...}                                            # line 18
    #   metadata={...}                                              # line 50
    #   metadata={...}                                              # line 71
    #   metadata={...}                                              # line 87
    #   metadata={...}                                              # line 104
    #   metadata=_info                                              # line 132
    #   metadata = {...}                                            # line 146
    async def _load(self, source, **kwargs) -> List[Document]:      # line 198

# packages/ai-parrot-loaders/src/parrot_loaders/video.py
class VideoLoader(BaseVideoLoader):                                 # line 9
    async def _load(self, source, **kwargs) -> List[Document]:      # line 67

# packages/ai-parrot-loaders/src/parrot_loaders/videolocal.py
#   metadata = {...}                                                # line 71
#   metadata={...}                                                  # line 125, 150, 156, 167, 182, 188, 211

# packages/ai-parrot-loaders/src/parrot_loaders/videounderstanding.py
#   base_metadata = {...}                                           # line 195
#   main_doc_metadata = {...}                                       # line 225
#   chunk_metadata = {...}                                          # line 239
#   scene_metadata = {...}                                          # line 262
#   instructions_metadata = {...}                                   # line 305
#   spoken_metadata = {...}                                         # line 325
#   error_metadata = {...}                                          # line 348
```

```python
# After TASK-855, AbstractLoader provides:
# create_metadata(path, doctype, source_type, doc_metadata, *, language=None, title=None, **kwargs)
# self.language: str
```

### Does NOT Exist
- ~~`AudioLoader.create_metadata`~~ — AudioLoader does not override `create_metadata`; inherits from BaseVideoLoader → AbstractLoader.
- ~~`VideoLocalLoader.build_default_meta`~~ — inherits from BaseVideoLoader after TASK-856.
- ~~`AudioLoader.language`~~ — inherits from AbstractLoader after TASK-855 (via BaseVideoLoader).

---

## Implementation Notes

### Refactor strategy per emit-site
For each `metadata = { "url": ..., "source": ..., ... }` or `Document(..., metadata={...})`:
1. Identify which variant this is (transcript, srt, vtt, dialog, summary, scene, etc.).
2. Determine the `doctype` (e.g. `"audio_transcript"`, `"video_transcript"`, `"srt"`, `"vtt"`, `"dialog"`, `"scene_analysis"`).
3. Call `self.build_default_meta(source_path, doctype=doctype, extra_key=val, ...)` or `self.create_metadata(...)`.
4. Move variant-specific keys (origin, vtt_path, srt_path, start_time, end_time, etc.) to `**kwargs`.

### Key Constraints
- Each emit-site is a **separate** refactor. Do not try to collapse them.
- `audio.py` constructs Documents inside loops — each iteration may have different extras.
- Replace `self._language` reads with `self.language` throughout.
- Do NOT change `__init__` signatures on any of these loaders.
- `video.py` may have minimal direct emit sites if most logic lives in `BaseVideoLoader._load`.

### References in Codebase
- `packages/ai-parrot-loaders/src/parrot_loaders/audio.py`
- `packages/ai-parrot-loaders/src/parrot_loaders/video.py`
- `packages/ai-parrot-loaders/src/parrot_loaders/videolocal.py`
- `packages/ai-parrot-loaders/src/parrot_loaders/videounderstanding.py`

---

## Acceptance Criteria

- [ ] `audio.py` — all 7 emit sites route through `create_metadata` or `build_default_meta`
- [ ] `video.py` — all Document constructions use canonical metadata
- [ ] `videolocal.py` — all emit sites route through `create_metadata`
- [ ] `videounderstanding.py` — all emit sites route through `create_metadata`
- [ ] No raw `metadata = {...}` dicts remain in any of the 4 files
- [ ] Loader-specific keys (origin, vtt_path, srt_path, start_time, end_time, etc.) at top level
- [ ] `document_meta` is closed-shape with exactly 5 canonical keys on every emitted Document
- [ ] `self._language` references replaced with `self.language`
- [ ] Tests pass: `pytest packages/ai-parrot-loaders/tests/ -v -k "audio or video"`
- [ ] No breaking changes to loader public signatures

---

## Test Specification

```python
# packages/ai-parrot-loaders/tests/test_video_audio_metadata.py
import pytest

CANONICAL_DOC_META_KEYS = {"source_type", "category", "type", "language", "title"}


class TestAudioLoaderMetadata:
    def test_canonical_metadata_shape(self):
        from parrot_loaders.audio import AudioLoader
        loader = AudioLoader(language="en")
        meta = loader.create_metadata(
            "test_audio.mp3",
            doctype="audio_transcript",
            source_type="audio",
            origin="/tmp/audio.mp3",
            vtt_path="/tmp/audio.vtt"
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "origin" in meta
        assert "vtt_path" in meta
        assert "origin" not in meta["document_meta"]


class TestVideoUnderstandingMetadata:
    def test_extras_at_top_level(self):
        from parrot_loaders.videounderstanding import VideoUnderstandingLoader
        loader = VideoUnderstandingLoader(language="en")
        meta = loader.create_metadata(
            "video.mp4",
            doctype="scene_analysis",
            source_type="video",
            model_name="gpt-4o",
            scene_index=3
        )
        assert "model_name" in meta
        assert "scene_index" in meta
        assert "model_name" not in meta["document_meta"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-855 and TASK-856 are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm TASK-855 and TASK-856 changes are present
   - Read each loader file to verify emit-site line numbers
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-858-refactor-video-audio-loaders.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-04-27
**Notes**: All emit sites in audio.py (7), videolocal.py (4+), and
videounderstanding.py (7) replaced with create_metadata() calls. Loader-specific
extras (origin, vtt_path, srt_path, dialog timing, model_used, video_title,
scene_number, etc.) now live at top level. video.py verified clean — no direct
Document constructions (delegates to abstract load_video). self._language
references removed (create_metadata uses self.language via property alias).
10 new canonical-shape tests in test_video_audio_metadata.py — all pass.
91 total tests pass; 7 pre-existing failures unchanged.

**Deviations from spec**: none
