---
type: Wiki Overview
title: 'TASK-1608: Mode B — pluggable STT (internal + LiveAvatar)'
id: doc:sdd-tasks-completed-task-1608-pluggable-stt-mode-b-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Q-internal-stt-full resolved: Mode B must offer **our internal STT in addition'
relates_to:
- concept: mod:parrot.voice.transcriber
  rel: mentions
---

# TASK-1608: Mode B — pluggable STT (internal + LiveAvatar)

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1607
**Assigned-to**: unassigned

---

## Context

Q-internal-stt-full resolved: Mode B must offer **our internal STT in addition
to LiveAvatar's**, selectable per session — internal `FasterWhisper` (local) /
`OpenAIWhisper` (cloud) via the existing `VoiceTranscriber`, OR LiveAvatar STT
(default, via the data-channel `user.transcription` events).
(Spec §2 Mode B, §4 M-B3. Note: **Silero is VAD, not STT**.)

---

## Scope

- Provide a transcribe path the FULL-mode frontend can call when it wants
  **internal STT**: either reuse `/api/v1/agents/voice/{agent_id}`
  (`AgentVoiceTalk`, which already transcribes an audio upload via
  `VoiceTranscriber` then runs the agent) or add a lightweight
  **transcribe-only** endpoint `POST /api/v1/agents/transcribe/{agent_id}`
  returning `{text}` (no agent call) so the frontend then drives `/agents/chat`.
- Honor a per-request STT backend selector (`stt_backend ∈ {faster_whisper,
  openai}`) — reuse `AgentVoiceTalk._read_voice_options` semantics.
- Document that LiveAvatar STT is the default (frontend consumes
  `user.transcription`); internal STT is opt-in.
- Tests with a fake transcriber backend.

**NOT in scope**: VAD; changing transcriber backends; the bifurcation helper
(TASK-1607).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` | MODIFY | expose transcribe-only path / selector (or confirm `/agents/voice` covers it) |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | register transcribe route if a new endpoint is added |
| `packages/ai-parrot-server/tests/handlers/test_transcribe_stt.py` | CREATE | internal STT selectable, text returned |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Signatures
```python
# handlers/agent_voice.py
class AgentVoiceTalk(AgentTalk):          # :57   endpoint POST /api/v1/agents/voice/{agent_id}
    async def handle_upload(self): ...    # :94   parses multipart, finds audio
    # _find_audio_attachment :163 ; _transcribe_attachment :192 (lazy VoiceTranscriber)
    # _read_voice_options :137  (stt_backend, tts_backend, audio_format)
# parrot.voice.transcriber  (ai-parrot-integrations)
#   VoiceTranscriber.transcribe_file(path, language) :114 ; .transcribe_url :157
#   FasterWhisperBackend (local, default), OpenAIWhisperBackend (cloud)
# manager.py  _register_voice_routes :1454  (registers /agents/voice; mirror for a new route)
```

### Does NOT Exist
- ~~a Silero STT backend~~ — Silero is VAD; STT backends are Whisper-family (FasterWhisper / OpenAIWhisper / Moonshine)
- ~~internal STT inside the LiveAvatar FULL room~~ — FULL room mic is LiveAvatar's; internal STT requires the browser to send audio to ai-parrot

---

## Implementation Notes
- Prefer reusing the existing `VoiceTranscriber` invocation in `agent_voice.py`
  rather than duplicating transcription logic.
- A transcribe-only endpoint keeps Mode B clean: frontend → transcribe → text →
  `/agents/chat` (streaming) → bifurcation (TASK-1607).
- Lazy-import the voice stack; 503 if `[voice-local]`/`[voice-openai]` missing.

---

## Acceptance Criteria
- [ ] The frontend can obtain a transcript from ai-parrot internal STT (FasterWhisper local or OpenAI cloud), selectable per request.
- [ ] LiveAvatar STT remains the documented default (no code needed — data-channel events).
- [ ] Missing voice extra → 503, not a crash.
- [ ] `pytest .../test_transcribe_stt.py -q` green (fake backend).

---

## Agent Instructions
Standard SDD flow.

## Completion Note
*(Agent fills this in when done)*
