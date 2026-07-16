---
type: Wiki Overview
title: 'TASK-1631: Gemini STT-only mode (voice WS)'
id: doc:sdd-tasks-completed-task-1631-gemini-stt-only-mode-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 1. The Gemini voice path runs full-duplex today (Gemini transcribes
---

# TASK-1631: Gemini STT-only mode (voice WS)

**Feature**: FEAT-257 — Gemini STT-only mode (voice WS)
**Spec**: `sdd/specs/livekit-gemini-voice-input.spec.md`
**Status**: done
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
# NOTE: The /ws/voice handler that parses start_session and forwards transcription /
#   response_chunk frames is at:
#   packages/ai-parrot-integrations/src/parrot/voice/handler.py (VoiceChatHandler)
#   NOT agent_voice.py (which is a REST handler for audio attachments).
#   The task file listing "agent_voice.py" is a stale reference — the correct file
#   is handler.py in the integrations package.
# VoiceChatHandler._handle_start_session: parses message dict, merges config, creates bot
# VoiceChatHandler._send_voice_response: forwards response_chunk / transcription frames
# WebSocketConnection: dataclass with session_id, bot, streaming_mode, etc.
```

### Does NOT Exist
- ~~an `stt_only` flag / STT-only mode~~ — add it (this task).
- ~~a separate STT-only client class~~ — reuse `GeminiLiveClient` with a flag; do NOT fork.
- ~~stt_only on WebSocketConnection~~ — add it (this task).

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

Implemented 2026-06-24. All 8 unit tests pass.

**Files modified:**
- `packages/ai-parrot/src/parrot/clients/live.py`: Added `stt_only: bool = False` parameter to `_build_live_config()` and `stream_voice()`. When `stt_only=True`, `response_modalities` is set to `[]` (suppresses model output), `output_audio_transcription` is set to `None`, and model_turn processing in the run loop is gated out. Input transcription (`input_audio_transcription`) is always enabled.
- `packages/ai-parrot-integrations/src/parrot/voice/handler.py`: Added `stt_only: bool = False` field to `WebSocketConnection`. `_handle_start_session()` parses `stt_only` from the incoming message and sets it on the connection. `session_started` message includes the flag. `_run_voice_session()` passes `stt_only=connection.stt_only` to `bot.ask_stream()`. `_send_voice_response()` skips all model-response forwarding (response_chunk, response_complete, ready_to_speak, avatar tee) when `stt_only=True`; user transcription frames are always forwarded.

**Tests created:**
- `packages/ai-parrot-server/tests/handlers/test_agent_voice_stt_only.py`: 8 unit tests covering transcription emission, model response suppression, default full-duplex behavior, start_session parsing, and live config construction.

**Note on stale codebase contract**: The task listed `agent_voice.py` as the WS voice handler. The actual WS voice handler is `packages/ai-parrot-integrations/src/parrot/voice/handler.py` (VoiceChatHandler). The contract in this file was updated to reflect the correct location before implementation.
