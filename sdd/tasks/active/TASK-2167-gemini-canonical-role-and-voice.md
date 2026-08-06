# TASK-2167: Gemini: canonical role envelope + per-call voice override

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2166
**Assigned-to**: unassigned
**Parallel-safe**: yes — Gemini lane — same file as TASK-2166, so sequential within the lane but disjoint from the Nova lane.

---

## Context

`GeminiLiveClient.stream_voice()` never sets `role` (it stays `None`,
`clients/live.py:187`) and hides the user's transcription in
`metadata["user_transcription"]` (`live.py:875`). Nova, meanwhile, sets
`role="USER"/"ASSISTANT"` (`nova/audio.py:897`). `VoiceSession._relay()` only
reads `resp.role` (`voice/session.py:271`), so a UI built for Nova cannot render
Gemini transcripts at all.

This task makes Gemini emit the canonical envelope. It is the producer half of
the breaking change; the consumer halves are TASK-2173 (VoiceBot memory),
TASK-2174 (handler + chat.html) and TASK-2175 (cross-distribution tests).

Implements: **Spec §3 Module 3 (envelope half)**.

---

## Scope

- Set `role="assistant"` on every model-originated `LiveVoiceResponse`
  (text and audio) yielded by `stream_voice()`.
- Emit the user's transcription as a text response with `role="user"` instead of
  `metadata["user_transcription"]`, and remove that metadata key from the
  producer (`live.py:875`).
- Add a per-call voice override: `stream_voice()`/`_build_live_config()` accept a
  voice name that beats the constructor's `self.voice_name` for that call.
- Validate the requested voice against the descriptor's `voice_catalog`; on a
  miss, warn and fall back to the client default rather than passing it through.
- Flip `supports_per_call_voice=True` in Gemini's descriptor.
- Tests per spec §4.

**NOT in scope**: consumers of the old metadata key — they are migrated by
TASK-2173/2174/2175. This task may leave those call sites temporarily reading a
key that is no longer produced; that is expected and is why TASK-2173/2174 are
sequenced immediately after.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/live.py` | MODIFY | Canonical `role`, drop metadata key, voice override |
| `packages/ai-parrot/tests/clients/test_live_envelope.py` | CREATE | Envelope + voice-override tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.clients.live import GeminiLiveClient, LiveVoiceResponse   # clients/live.py
from parrot.models.voice import VoiceStreamOptions                    # models/voice.py (TASK-2164)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/live.py
@dataclass
class LiveVoiceResponse:
    text: str = ""
    audio_data: Optional[bytes] = None
    role: Optional[str] = None                                # line 187 — never set by stream_voice
    metadata: Dict[str, Any] = field(default_factory=dict)
    def to_websocket_message(self) -> Dict[str, Any]:         # includes "role" at line 214

# inside stream_voice() — the two transcription paths:
    metadata={"user_transcription": text},                    # line 875 — REMOVE, emit role="user"
    if hasattr(server_content, 'output_transcription') ...:   # line 883
        turn_metadata.output_transcription = text             # line 887

# role is set ONLY in ask(), never in the streaming path:
    role="user",                                              # line 1266

# speech config built from the constructor voice:
    voice_name=self.voice_name                                # line 673 (inside _build_live_config)
```

### Does NOT Exist

- ~~`GeminiLiveClient.stream_voice` setting `role` today~~ — it does not; `role="user"` at `live.py:1266` is inside `ask()`, a different method.
- ~~Uppercase roles on the Gemini side~~ — the canonical form is lowercase `"user"`/`"assistant"`. Nova's uppercase values are normalized separately by TASK-2170.
- ~~An enumerated Gemini voice catalog in the repo~~ — not written down anywhere. Use the descriptor's `voice_catalog` from TASK-2165 and prefer warn-and-fallback over hard rejection (spec §8 leaves catalog completeness open).
- ~~`metadata["assistant_transcription"]`~~ — no such key exists; do not invent a mirror of the key being removed.

---

## Implementation Notes

### Key Constraints
- Canonical roles are lowercase strings: `"user"` and `"assistant"`. Do not use
  an enum — `LiveVoiceResponse.role` is `Optional[str]` (`live.py:187`) and
  `to_websocket_message()` (`live.py:214`) serializes it directly.
- Removing `metadata["user_transcription"]` is deliberate and has no deprecation
  window (spec §5). Do NOT emit both forms.
- Keep the `stt_only` contract intact: in STT-only mode only the `role="user"`
  transcription frames are emitted — no assistant text, no audio.
- The per-call voice must not mutate `self.voice_name`; resolve it locally per
  call so concurrent sessions on one client do not interfere.

---

## Acceptance Criteria

- [ ] Model text/audio responses carry `role="assistant"`
- [ ] User transcription is emitted as a response with `role="user"`
- [ ] `metadata["user_transcription"]` is no longer produced by `live.py`
- [ ] Per-call voice beats the constructor value and does not mutate client state
- [ ] An out-of-catalog voice warns and falls back instead of being passed through
- [ ] STT-only still emits only `role="user"` frames
- [ ] Gemini descriptor `supports_per_call_voice=True`
- [ ] Tests pass: `pytest packages/ai-parrot/tests/clients/test_live_envelope.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/live.py`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# packages/ai-parrot/tests/clients/test_live_envelope.py
import pytest
from parrot.clients.live import GeminiLiveClient


class TestCanonicalRole:
    async def test_model_text_is_assistant(self, mocked_live_session):
        responses = [r async for r in mocked_live_session.stream_voice(...)]
        assert any(r.role == "assistant" for r in responses if r.text)

    async def test_user_transcription_is_role_user(self, mocked_live_session):
        responses = [r async for r in mocked_live_session.stream_voice(...)]
        assert any(r.role == "user" for r in responses)

    async def test_no_user_transcription_metadata(self, mocked_live_session):
        responses = [r async for r in mocked_live_session.stream_voice(...)]
        assert all("user_transcription" not in r.metadata for r in responses)


class TestVoiceOverride:
    def test_per_call_voice_wins(self):
        client = GeminiLiveClient(voice_name="Puck")
        cfg = client._build_live_config(voice="Charon")
        assert "Charon" in str(cfg.speech_config)
        assert client.voice_name == "Puck"  # no state mutation

    def test_unknown_voice_falls_back_warned(self, caplog):
        client = GeminiLiveClient(voice_name="Puck")
        cfg = client._build_live_config(voice="matthew")  # a Nova voice
        assert "Puck" in str(cfg.speech_config)
        assert any("matthew" in r.message for r in caplog.records)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/googlelive-nova2-audiobot-homologation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
