---
type: Wiki Overview
title: 'TASK-1632: STT-only voice WS integration test'
id: doc:sdd-tasks-completed-task-1632-stt-only-integration-test-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §4 Integration. End-to-end (mocked Gemini) coverage of the STT-only
  session on
relates_to:
- concept: mod:parrot
  rel: mentions
---

# TASK-1632: STT-only voice WS integration test

**Feature**: FEAT-257 — Gemini STT-only mode (voice WS)
**Spec**: `sdd/specs/livekit-gemini-voice-input.spec.md`
**Status**: done
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

Implemented 2026-06-24. Both integration tests pass (2 passed).

**File created:**
- `packages/ai-parrot-server/tests/handlers/test_voice_ws_stt_only_integration.py`

**Tests:**
1. `test_voice_ws_stt_only_session`: Drives a complete `_handle_start_session` → `_run_voice_session` pipeline with `stt_only=True`. The mock `ask_stream` yields a user transcription frame and a model audio frame, then signals shutdown. Asserts `transcription` (is_user=True) is present and `response_chunk` is absent.
2. `test_voice_ws_full_duplex_session`: Same pipeline without `stt_only`. Asserts `response_chunk` IS emitted for the model audio frame (regression guard for default full-duplex path).

**Mocking approach:** Same pattern as TASK-1631 unit tests — worktree path injection via `sys.path` / `parrot.__path__` extension, google.genai stub, mock `bot.ask_stream` as an async generator that sets `shutdown_event` after yielding responses to exit the voice loop cleanly.
