# TASK-1632: STT-only voice WS integration test

**Feature**: FEAT-257 — Gemini STT-only mode (voice WS)
**Spec**: `sdd/specs/livekit-gemini-voice-input.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1631
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration. End-to-end (mocked Gemini) coverage of the STT-only session on
the `/ws/voice` handler.

---

## Scope

- `test_voice_ws_stt_only_session`: open a voice WS with `start_session
  {stt_only: true}` (Gemini mocked) → feed mic frames → assert ONLY user
  `transcription` frames are emitted, NO `response_chunk` / model audio.
- A companion assertion that without the flag the full-duplex path still emits a model response (mocked).

**NOT in scope**: production code (TASK-1631); frontend.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/.../test_voice_ws_stt_only_integration.py` | CREATE | integration test (Gemini/WS mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# handlers/agent_voice.py — /ws/voice handler + start_session {stt_only}
# GeminiLiveClient mocked (no real Gemini network).
```

### Does NOT Exist
- ~~a live Gemini in tests~~ — mock it.

---

## Implementation Notes

### Key Constraints
- No real network: mock the Gemini client; drive the handler with a fake WS.
- Assert the absence of model-response frames in STT-only.

### References in Codebase
- The unit tests from TASK-1631 for mocking patterns.

---

## Acceptance Criteria

- [ ] Integration test passes (`pytest packages/ai-parrot-server -k stt_only -v`).
- [ ] Proves STT-only yields user transcription only (no model response).

---

## Test Specification
```python
async def test_voice_ws_stt_only_session(...): ...
```

---

## Completion Note
*(Agent fills this in when done)*
