---
type: Wiki Overview
title: 'TASK-246-002: Add resolve_stt/resolve_tts factories and wire them into pipeline.py'
id: doc:sdd-tasks-completed-task-246-002-resolve-factories-pipeline-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-246 Module 3 — env-driven provider factory and pipeline wiring.
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
---

# TASK-246-002: Add resolve_stt/resolve_tts factories and wire them into pipeline.py

**Feature**: livekit-native-voice-adapters
**Spec**: sdd/specs/livekit-native-voice-adapters.spec.md
**Status**: [ ] pending | [ ] in-progress | [ ] done
**Priority**: high
**Depends-on**: TASK-246-001
**Assigned-to**: unassigned

## Context

FEAT-246 Module 3 — env-driven provider factory and pipeline wiring.
With voice_adapters.py in place (TASK-246-001), this task adds
`resolve_stt(vad)` / `resolve_tts()` to `voice_adapters.py` and modifies
`pipeline.py` to use them instead of the hardcoded Deepgram/Cartesia defaults.

## Scope

### In `voice_adapters.py` (TASK-246-001 file), add:

1. `resolve_stt(vad: Any) -> Any` — reads `LIVEAVATAR_STT_PROVIDER` env var
   (default `"whisper"`). Dispatch:
   - `"whisper"` → `stt.StreamAdapter(stt=WhisperSTT(), vad=vad)`
   - `"moonshine"` → `stt.StreamAdapter(stt=MoonshineSTT(), vad=vad)`
   - `"deepgram"` → lazy import `livekit.plugins.deepgram.STT()` (existing)
   - `"openai"` → lazy import `livekit.plugins.openai.STT()` (expose as option per spec open question)
   - Unknown → log warning + fallback to whisper

2. `resolve_tts() -> Any` — reads `LIVEAVATAR_TTS_PROVIDER` env var
   (default `"supertonic"`). Dispatch:
   - `"supertonic"` → build `SupertonicPipeline` from env `SUPERTONIC_MODEL_DIR`
     (raise `ValueError` if not set), return `SupertonicTTS(pipeline=pipeline)`
   - `"cartesia"` → lazy import `livekit.plugins.cartesia.TTS()` (existing)
   - `"inference"` → lazy import LiveKit inference TTS (existing)
   - Unknown → log warning + fallback to supertonic

### In `pipeline.py` (FEAT-243 file, modify):

Replace `_default_stt()` and `_default_tts()` private functions with calls to
`resolve_stt` / `resolve_tts` from `voice_adapters`. Keep the function signatures
backward-compatible:

- `build_session(vad, *, stt=None, tts=None, ...)` stays unchanged.
- When `stt is None`: call `resolve_stt(vad)` instead of `_default_stt()`.
- When `tts is None`: call `resolve_tts()` instead of `_default_tts()`.
- Keep `_default_stt` and `_default_tts` as deprecated wrappers (or remove them —
  spec says replace; no callers outside pipeline.py itself, so safe to remove).
- Add import: `from parrot.integrations.liveavatar.livekit_agent.voice_adapters import resolve_stt, resolve_tts`
- The `DEFAULT_STT_MODEL` constant and `_default_turn_detection`/`_default_session_factory`
  are unchanged.

## Files to Modify

- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/voice_adapters.py` — add `resolve_stt`, `resolve_tts`
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/pipeline.py` — replace `_default_stt`/`_default_tts` with `resolve_*`

## Files to Create

None.

## Implementation Notes

- `resolve_stt` wraps non-streaming STT in `stt.StreamAdapter(stt=..., vad=vad)`.
- For `"supertonic"`: read `SUPERTONIC_MODEL_DIR` from env; if not set, raise
  `ValueError("SUPERTONIC_MODEL_DIR env var required for supertonic TTS")`.
- Keep deepgram/cartesia branches intact (lazy import, try/except ImportError)
  so existing deployments keep working if they set the env var.
- Lazy imports inside `resolve_*` branches — keep at function scope so module
  imports without the extras.
- The `stt.StreamAdapter` constructor: `stt.StreamAdapter(stt=<stt_instance>, vad=<vad_instance>)`.
  Verify exact constructor signature at implementation time.

## Codebase Contract

### Verified Imports (in voice_adapters.py)
Already imported in TASK-246-001. Add:
```python
import os  # for os.environ.get
from typing import Any
```

### Existing Signatures (pipeline.py to modify)
```python
# Current pipeline.py (to replace)
def _default_stt() -> Any: ...   # line 32 — deepgram.STT
def _default_tts() -> Any: ...   # line 44 — cartesia.TTS

def build_session(vad, *, stt=None, tts=None, turn_detection=None, session_factory=None) -> Any:
    stt = stt if stt is not None else _default_stt()
    tts = tts if tts is not None else _default_tts()
    ...
```

### After modification:
```python
from parrot.integrations.liveavatar.livekit_agent.voice_adapters import resolve_stt, resolve_tts

def build_session(vad, *, stt=None, tts=None, turn_detection=None, session_factory=None) -> Any:
    stt = stt if stt is not None else resolve_stt(vad)
    tts = tts if tts is not None else resolve_tts()
    ...
```

## Acceptance Criteria

- [ ] With no env vars, `resolve_stt(fake_vad)` returns a `StreamAdapter` wrapping `WhisperSTT`
- [ ] With no env vars, `resolve_tts()` raises `ValueError` about `SUPERTONIC_MODEL_DIR`
      (expected — test by setting the env var or mocking)
- [ ] `LIVEAVATAR_STT_PROVIDER=moonshine` → `StreamAdapter` wrapping `MoonshineSTT`
- [ ] `LIVEAVATAR_TTS_PROVIDER=cartesia` → lazy import attempt for cartesia
- [ ] `build_session(fake_vad, stt=fake_stt, tts=fake_tts)` passes explicit components unchanged
- [ ] Existing FEAT-243 pipeline tests still pass (no signature break)

## Completion Note
(Agent fills this in when done)

## Completion Note

Modified `pipeline.py`:
- Removed `_default_stt()` and `_default_tts()` (Deepgram/Cartesia hardcoded defaults).
- `build_session()` now does a local import of `resolve_stt` / `resolve_tts` from
  `voice_adapters.py` and calls them when `stt` / `tts` are not explicitly passed.
- `DEFAULT_STT_MODEL` constant retained (still used by `resolve_stt` Deepgram branch).
- Updated module docstring to document provider selection.
- Removed unused `import os` (was used only by `_default_stt`).
- ruff clean. All 113 existing liveavatar tests pass.
