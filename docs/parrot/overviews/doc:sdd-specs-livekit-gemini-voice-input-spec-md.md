---
type: Wiki Overview
title: 'Feature Specification: Gemini STT-only mode (voice WS)'
id: doc:sdd-specs-livekit-gemini-voice-input-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The Gemini voice path (`/ws/voice`, `agent_voice.py` / `GeminiLiveClient`)
  runs
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Gemini STT-only mode (voice WS)

**Feature ID**: FEAT-257
**Date**: 2026-06-24
**Author**: Juanfran
**Status**: approved
**Target version**: next

> **Backend-only spec.** This covers ONLY the ai-parrot side: a Speech-to-Text-only
> mode on the existing Gemini voice WebSocket. The frontend wiring that consumes it
> (re-enable PTT in livekit, open the STT session, route the transcription to
> `/agents/chat`) is handled **directly in `navigator-frontend-next`** and is NOT
> part of this spec.
> Source brainstorm: `sdd/proposals/livekit-gemini-voice-input.brainstorm.md`.

---

## 1. Motivation & Business Requirements

### Problem Statement
The Gemini voice path (`/ws/voice`, `agent_voice.py` / `GeminiLiveClient`) runs
Gemini Live **full-duplex** — Gemini transcribes the user AND generates a spoken
response. For the new livekit voice-input flow, we need Gemini **only to
transcribe** the user's speech; the **ai-parrot agent** (`/agents/chat`) produces
the answer and the answer is spoken into the LiveKit room (FEAT-256). If Gemini
also answered, we'd have a "double brain".

We need a reusable **STT-only mode**: feed mic PCM, emit `input_transcription`,
**suppress Gemini's own model response** (no audio, no text answer).

### Goals
- Add an `stt_only` switch to the Gemini voice session.
- In STT-only mode: keep emitting `input_transcription` (user speech); Gemini does
  **NOT** generate a model response (no spoken/text answer, no `response_chunk`).
- Default behavior (no flag) unchanged → full-duplex (ws-pcm keeps working).

### Non-Goals (explicitly out of scope)
- **All frontend work** — PTT re-enable, opening the STT session in livekit, and
  routing the transcription to `/agents/chat` are done directly in the frontend
  repo, not here.
- Gemini as the conversational brain (the ai-parrot agent answers).
- Multi-driver / turn arbitration (phase 2).
- Any change to FEAT-256 output, fullmode, or the default ws-pcm full-duplex flow.

---

## 2. Architectural Design

### Overview
Extend the Gemini voice session start to accept `stt_only: bool` (default `False`).
When `True`, configure Gemini Live to transcribe input but not respond: request
input transcription only, and do not emit/forward any model response. The handler
keeps streaming mic PCM in and emitting `transcription` (is_user) frames out; it
stops emitting `response_chunk` / model audio.

### Component Diagram
```
client mic PCM ─→ /ws/voice (start_session {stt_only:true})
                      │  GeminiLiveClient (input_audio_transcription ON,
                      │                     model response SUPPRESSED)
                      ▼
                  transcription (is_user)  ──→ client   (NO response_chunk)
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `handlers/agent_voice.py` | modifies | accept `stt_only` in start_session; skip forwarding model responses when set |
| `clients/live.py` `GeminiLiveClient` | modifies | config + run-loop honor STT-only (transcribe input, no model output) |

### New Public Interfaces
```python
# start_session payload gains an optional flag (default False):
#   { ..., "stt_only": bool }
# In STT-only: emits transcription(is_user=True); never emits response_chunk / model audio.
```

---

## 3. Module Breakdown

### Module 1: Gemini STT-only mode
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` +
  `packages/ai-parrot/src/parrot/clients/live.py`
- **Responsibility**: thread an `stt_only` flag from the start_session message into
  the Gemini Live config + run loop. When set: enable input transcription, suppress
  the model response (no audio modality / discard model output), keep emitting the
  user `transcription` frames. When unset: behavior is exactly as today (full-duplex).
- **Depends on**: existing `GeminiLiveClient`.

### Module 2: Tests
- **Path**: ai-parrot unit tests for the voice path.
- **Responsibility**: STT-only emits user transcription and NO model response;
  default mode still full-duplex.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_stt_only_emits_user_transcription` | M1 | STT-only mode forwards `transcription(is_user=True)` |
| `test_stt_only_suppresses_model_response` | M1 | STT-only mode emits NO `response_chunk` / model audio |
| `test_default_still_full_duplex` | M1 | without `stt_only`, the existing ws-pcm full-duplex flow is unchanged |

### Integration Tests
| Test | Description |
|---|---|
| `test_voice_ws_stt_only_session` | mocked Gemini: start_session `stt_only=true` → mic frames → only user transcription frames out |

---

## 5. Acceptance Criteria

- [ ] `start_session` accepts `stt_only` (default `False`; absent → today's behavior).
- [ ] STT-only mode emits user `transcription` frames and **no** model response
      (`response_chunk` / model audio).
- [ ] Default (no flag) keeps the ws-pcm full-duplex flow byte-for-byte unchanged.
- [ ] Unit + integration tests pass (`pytest packages/ -k voice -v`).
- [ ] No change to FEAT-256, fullmode, or other transports.

---

## 6. Codebase Contract

> Verified against ai-parrot `dev` (post FEAT-256), 2026-06-24.

### Existing Signatures to Use
```python
# clients/live.py — GeminiLiveClient
#   input_audio_transcription=types.AudioTranscriptionConfig()   # live.py:666
#   output_audio_transcription=types.AudioTranscriptionConfig()  # live.py:667
#   emits input_transcription (user) live.py:806-814 ; output_transcription live.py:822-831
#   config knobs: response_modalities, enable_input_transcription,
#                 enable_output_transcription                      # live.py:722
# handlers/agent_voice.py — the /ws/voice handler: parses start_session, runs the
#   Gemini session, forwards transcription / response_chunk frames to the client.
```

### Does NOT Exist (Anti-Hallucination)
- ~~an `stt_only` flag / STT-only mode~~ — to be added (M1). Gemini runs full-duplex today.
- ~~a separate STT-only client class~~ — reuse `GeminiLiveClient` with a flag; do NOT fork it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Minimal, additive change: a flag + a branch in the config/run-loop. Do NOT
  duplicate `GeminiLiveClient`.
- Verify the exact Gemini Live setting that yields "transcribe input, no model
  response" (see Open Q) — prefer config over discarding output after the fact, but
  discarding/suppressing forwarding is an acceptable fallback.
- Async throughout; keep logging.

### Known Risks / Gotchas
- **Double brain**: the whole point — STT-only must NOT answer. Assert in tests.
- Don't regress the default full-duplex path (ws-pcm depends on it).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `google-genai` (Gemini Live) | (existing) | already used; no new dep |

---

## 8. Open Questions
- [ ] **Exact STT-only config**: the precise `google-genai` Live setting to transcribe input WITHOUT a model response (minimal `response_modalities`? omit output audio + ignore model turns?). — *Owner: implementer (verify vs `google-genai`)*.
- [ ] Should STT-only still emit interim (partial) user transcriptions, or only finals? *Default: emit as today (partials + final); the frontend decides.* — *Owner: implementer*.

---

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-24 | Juanfran | Initial draft — backend-only. STT-only mode on the Gemini voice WS (FEAT-257). Frontend consumer handled directly in navigator-frontend-next (out of scope here). |
