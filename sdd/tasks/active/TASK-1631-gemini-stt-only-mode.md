# TASK-1631: Gemini STT-only mode (voice WS)

**Feature**: FEAT-257 — Gemini STT-only mode (voice WS)
**Spec**: `sdd/specs/livekit-gemini-voice-input.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. The Gemini voice path runs full-duplex today (Gemini transcribes
AND answers). For the livekit voice-input flow the frontend needs Gemini to **only
transcribe**; the ai-parrot agent answers. Add an `stt_only` switch that keeps input
transcription but **suppresses Gemini's model response** (no double brain). Default
(no flag) must stay byte-for-byte the current full-duplex behavior (ws-pcm).

---

## Scope

- Thread an `stt_only: bool` flag from the `start_session` message through
  `agent_voice.py` into `GeminiLiveClient`.
- In STT-only mode: enable input transcription; do NOT generate/forward a model
  response (no `response_chunk`, no model audio). Keep emitting the user
  `transcription` frames.
- Default (flag absent/false): unchanged full-duplex flow.
- Unit tests for both modes.

**NOT in scope**: any frontend change (handled directly in navigator-frontend-next);
multi-driver; FEAT-256 output.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` | MODIFY | parse `stt_only` from start_session; pass to the client; don't forward model responses when set |
| `packages/ai-parrot/src/parrot/clients/live.py` | MODIFY | `GeminiLiveClient` honors STT-only (transcribe input, suppress model output) |
| `packages/ai-parrot-server/tests/.../test_agent_voice_stt_only.py` | CREATE | unit tests (Gemini mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# clients/live.py — GeminiLiveClient
#   input_audio_transcription=types.AudioTranscriptionConfig()    # live.py:666
#   output_audio_transcription=types.AudioTranscriptionConfig()   # live.py:667
#   emits input_transcription (user)  live.py:806-814
#   config knobs in the run/config path: response_modalities,
#       enable_input_transcription, enable_output_transcription   # live.py:722
# handlers/agent_voice.py — /ws/voice handler: parses start_session, runs the Gemini
#   session, forwards transcription / response_chunk frames to the client.
```

### Does NOT Exist
- ~~an `stt_only` flag / STT-only mode~~ — add it (this task).
- ~~a separate STT-only client class~~ — reuse `GeminiLiveClient` with a flag; do NOT fork.

---

## Implementation Notes

### Key Constraints
- Prefer the native config knob that yields "transcribe input, no model response"
  (investigate `response_modalities` / disabling output). If a clean config switch
  isn't available, suppress forwarding the model response as a fallback — but STILL
  avoid wasting a Gemini answer if possible.
- **Double-brain guard**: STT-only must NOT answer — assert in tests.
- Do NOT regress the default full-duplex path (ws-pcm depends on it).
- Async throughout; keep existing logging.

### References in Codebase
- `clients/live.py` (Gemini config + run loop), `handlers/agent_voice.py` (start_session parsing + frame forwarding).

---

## Acceptance Criteria

- [ ] `start_session` accepts `stt_only` (default false; absent → current behavior).
- [ ] STT-only emits user `transcription` frames and NO `response_chunk` / model audio.
- [ ] Default (no flag) full-duplex flow unchanged.
- [ ] Unit tests pass (`pytest packages/ai-parrot-server -k stt_only -v`).
- [ ] `ruff check` clean.

---

## Test Specification
```python
async def test_stt_only_emits_user_transcription(...): ...
async def test_stt_only_suppresses_model_response(...): ...
async def test_default_still_full_duplex(...): ...
```

---

## Completion Note
*(Agent fills this in when done)*
