---
type: Wiki Overview
title: 'TASK-1512: AgentVoiceTalk handler'
id: doc:sdd-tasks-completed-task-1512-agentvoicetalk-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** of the spec (§3) — the heart of the feature. A thin
  REST
relates_to:
- concept: mod:parrot.voice
  rel: mentions
- concept: mod:parrot.voice.transcriber.models
  rel: mentions
- concept: mod:parrot.voice.transcriber.transcriber
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

# TASK-1512: AgentVoiceTalk handler

**Feature**: FEAT-231 — AgentTalk Voice Support
**Spec**: `sdd/specs/agentalk-voice-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1510, TASK-1511
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of the spec (§3) — the heart of the feature. A thin REST
subclass `AgentVoiceTalk(AgentTalk)` in **ai-parrot-server** that inherits agent
resolution, PBAC, HITL, auth envelopes, session and output negotiation from
`AgentTalk`, and overrides only the two voice seams: STT inbound and TTS
outbound. Mirrors the existing `InfographicTalk(AgentTalk)` precedent.

Depends on the two backends (TASK-1510 Supertonic, TASK-1511 Moonshine) being
available at runtime, but reaches the voice stack via **lazy, extras-guarded
imports** — the server has no hard dependency on `ai-parrot-integrations`.

---

## Scope

- **Implement** `AgentVoiceTalk(AgentTalk)` in a new file
  `parrot/handlers/agent_voice.py`, decorated `@is_authenticated()` `@user_session()`
  (re-applied, exactly like `InfographicTalk`), with a distinct `_logger_name`.
- **Override `post()`**:
  - **Inbound (STT):** after `handle_upload()`, detect an audio attachment. If
    present, persist its bytes to a tempfile (use `tempfile`, already imported in
    the parent module), lazily import `VoiceTranscriber` + `VoiceTranscriberConfig`,
    call `transcribe_file(Path)`, and inject the resulting transcript as
    `data['query']` so the inherited text dispatch runs unchanged. Always
    `unlink()` the tempfile in a `finally`. If no audio attachment is present,
    fall through to the inherited text behaviour.
  - **Outbound (TTS):** after the inherited `bot.ask()` produces the `AIMessage`,
    lazily import `VoiceSynthesizer` + `TTSConfig`, synthesize **only**
    `response.response` (str), and attach `audio_base64` (base64 of
    `SynthesisResult.audio`) + `audio_format` (`SynthesisResult.mime_format`) to
    the JSON envelope produced by the inherited `_prepare_response`. `output` /
    `data` / `media` stay in `content`, never synthesized.
- **Graceful degradation:** wrap the synthesizer call in
  `try/except (ValueError, RuntimeError, ImportError)` → return text-only (omit
  `audio_base64`, still HTTP 200 with `content`). Same guard for the STT import on
  the inbound side (if the voice stack is missing, return a clean error rather
  than crashing).
- Backend selection (`faster_whisper` | `moonshine`, `google` | `supertonic`) is
  driven by `VoiceTranscriberConfig` / `TTSConfig`; default audio output
  `audio/wav` (spec U5).
- **Write** unit tests (handler-level, with a stub bot and stubbed voice services).

**NOT in scope**: route registration in `manager.py` (TASK-1513), the backends
themselves (TASK-1510/1511), any change to `AgentTalk.post()` or to `AIMessage`/
`AgentResponse`, streaming audio.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` | CREATE | `AgentVoiceTalk(AgentTalk)` |
| `packages/ai-parrot-server/tests/handlers/test_agent_voice.py` | CREATE | Unit tests (path: mirror existing server handler tests) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# host (same package)
from .agent import AgentTalk                              # verified: handlers/infographic.py:25 (precedent)
from navigator_auth.decorators import is_authenticated, user_session  # verified: handlers/infographic.py:21
from ..models.responses import AIMessage                  # verified: handlers/agent.py:36

# voice stack — LAZY, imported INSIDE the voice code path (not module top):
from parrot.voice.transcriber.transcriber import VoiceTranscriber        # verified: voice/transcriber/transcriber.py:30
from parrot.voice.transcriber.models import VoiceTranscriberConfig, TranscriberBackend  # verified: voice/transcriber/models.py:28,16
from parrot.voice.tts.synthesizer import VoiceSynthesizer  # verified: voice/tts/synthesizer.py:21
from parrot.voice.tts.models import TTSConfig             # verified: voice/tts/models.py:16
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py
import tempfile                                                   # line 11 (already imported in parent module)
@is_authenticated()                                              # line 100
@user_session()                                                  # line 101
class AgentTalk(BaseView):                                        # line 102
    async def _check_pbac_agent_access(self, ...): ...           # line 135  (inherited free)
    def _prepare_response(self, ...): ...                        # line 541  (inherited; extend envelope)
    async def _resolve_bot(self, ...): ...                       # line 984  (inherited; LLM-agnostic)
    async def _handle_attachments(self, ...): ...                # line 1261 (inherited)
    async def post(self):                                        # line 1523 (OVERRIDE this)
        attachments, data = await self.handle_upload()           # line 1580 (multipart already supported)
        query = data.pop('query', None)                          # line 1635 (inject transcript into data['query'])
        response: AIMessage = await bot.ask( ... )               # line 1847 (inherited agnostic dispatch)

# Precedent subclass — mirror its structure exactly:
# packages/ai-parrot-server/src/parrot/handlers/infographic.py
class InfographicTalk(AgentTalk):                                # line 57
    _logger_name: str = "Parrot.InfographicTalk"
    def post_init(self, *args, **kwargs) -> None: ...            # logger init

# Voice service signatures:
# VoiceTranscriber(config: VoiceTranscriberConfig)              # transcriber.py:64
#   async def transcribe_file(self, file_path: Path, language=None) -> TranscriptionResult  # :106
#   async def close(self)                                       # :289
# VoiceSynthesizer(config: Optional[TTSConfig] = None)          # synthesizer.py:46
#   async def synthesize(self, text: str, *, language=None) -> SynthesisResult  # :93
#   async def close(self)                                       # :138
# SynthesisResult.audio: bytes ; .mime_format: str             # tts/models.py:97,105
# AIMessage.response : str  (the ONLY speakable field)         # models/responses.py
```

### Does NOT Exist
- ~~`AgentVoiceTalk`~~ — this task creates it.
- ~~`VoiceSynthesizer` graceful degradation~~ — it **raises**; the handler must try/except.
- ~~`VoiceTranscriber.transcribe(bytes)`~~ — use `transcribe_file(Path)`; persist the upload to a tempfile first.
- ~~`AIMessage.audio` / `AIMessage.audio_base64`~~ — not a field; only `AIMessage.response` (str) is speakable. `audio_base64` is added to the JSON envelope, not the model.
- ~~Hard `import parrot.voice` at module top~~ — forbidden; lazy-import inside the voice path so server boot never requires `ai-parrot-integrations`.

---

## Implementation Notes

### Pattern to Follow
```python
@is_authenticated()
@user_session()
class AgentVoiceTalk(AgentTalk):
    _logger_name: str = "Parrot.AgentVoiceTalk"

    async def post(self):
        # 1) inbound: detect audio attachment from handle_upload(), persist to
        #    tempfile, transcribe, inject data['query'] = transcript, then run
        #    the inherited text dispatch (call super().post() OR replicate the
        #    minimal inbound seam — prefer delegating to the inherited path).
        # 2) outbound: after the AIMessage is produced, try:
        #       synth = VoiceSynthesizer(TTSConfig(backend=..., mime_format="audio/wav"))
        #       result = await synth.synthesize(response.response)
        #       envelope["audio_base64"] = base64.b64encode(result.audio).decode()
        #       envelope["audio_format"] = result.mime_format
        #    except (ValueError, RuntimeError, ImportError): text-only.
```

> **Design note for the implementer:** `AgentTalk.post()` is large (line 1523+).
> Decide between (a) calling `super().post()` after injecting `data['query']` and
> post-processing its response, or (b) overriding `post()` and re-using the
> inherited helper seams (`_resolve_bot`, `_prepare_response`). Option (a) keeps
> the text hot-path pristine (spec Non-Goal) — prefer it if `post()` returns a
> mutable envelope you can augment; otherwise factor the TTS attach into the
> response just before returning. Do NOT copy-paste `post()` body wholesale
> (that would duplicate the text path the spec forbids touching).

### Key Constraints
- async throughout; `self.logger`.
- Only `AIMessage.response` (str) is synthesized.
- Tempfile always cleaned up (`finally`).
- Lazy voice imports; degrade to text-only on `(ValueError, RuntimeError, ImportError)`.
- Re-apply auth decorators (subclasses do not inherit class decorators).

### References in Codebase
- `handlers/infographic.py` — the subclass precedent (decorators, `_logger_name`, `post_init`).
- `handlers/agent.py:1523-1847` — the inherited `post()` seams.
- `voice/transcriber/transcriber.py:106` / `voice/tts/synthesizer.py:93` — service calls.

---

## Acceptance Criteria

- [ ] `AgentVoiceTalk(AgentTalk)` created in `handlers/agent_voice.py`, decorated and with `_logger_name`.
- [ ] Audio attachment → tempfile → `transcribe_file(Path)` → transcript injected as `query`; tempfile unlinked.
- [ ] Inherited `bot.ask()` text dispatch runs unchanged (LLM-agnostic).
- [ ] Only `AIMessage.response` synthesized; envelope gains `audio_base64` + `audio_format`; `output`/`data`/`media` stay in `content`.
- [ ] TTS failure (`ValueError`/`RuntimeError`/`ImportError`) → text-only 200, no `audio_base64`.
- [ ] No-audio request falls through to inherited text behaviour.
- [ ] `AgentTalk.post()` is NOT modified.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_agent_voice.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/agent_voice.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_agent_voice.py
import base64
import pytest


async def test_voice_in_transcribes_and_injects_query(stub_bot, audio_request, monkeypatch):
    """Audio attachment is transcribed and injected as query; bot.ask sees text."""
    ...


async def test_voice_out_synthesizes_response_field_only(stub_bot, monkeypatch):
    """TTS reads AIMessage.response; output/data/media never synthesized."""
    ...


async def test_envelope_has_audio_base64_on_success(stub_bot, monkeypatch):
    resp = ...  # invoke handler
    assert "audio_base64" in resp and "audio_format" in resp


async def test_degrades_to_text_only_when_tts_raises(stub_bot, monkeypatch):
    # patch VoiceSynthesizer.synthesize to raise RuntimeError
    resp = ...
    assert "audio_base64" not in resp
    assert resp["content"]  # still present


async def test_no_audio_falls_through_to_text(stub_bot, text_request):
    ...  # behaves like inherited AgentTalk
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2, §3 Module 3, §6, §7).
2. **Check dependencies** — TASK-1510 and TASK-1511 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `AgentTalk` seams (`post` line 1523,
   `query` line 1635, `bot.ask` line 1847) and the `InfographicTalk` precedent are unchanged.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope; do NOT modify `AgentTalk.post()`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.8)
**Date**: 2026-06-09
**Notes**:
- Created `AgentVoiceTalk(AgentTalk)` decorated `@is_authenticated()` /
  `@user_session()` with `_logger_name = "Parrot.AgentVoiceTalk"` and a
  `post_init` that initialises the logger + per-request voice state. Mirrors
  the `InfographicTalk(AgentTalk)` precedent.
- **Inbound seam** is the overridden `handle_upload()`: it calls
  `super().handle_upload()`, detects an audio attachment (by mime/extension),
  transcribes it via a lazily-imported `VoiceTranscriber.transcribe_file(Path)`,
  injects `data['query']`, and removes the consumed attachment. The audio
  tempfile is always `unlink()`-ed in a `finally`. This makes the inherited
  `post()` text dispatch (`query = data.pop('query')` → `bot.ask(...)`) run
  **completely unchanged** and LLM-agnostic — `AgentTalk.post()` is not touched.
- **Outbound seam** is the overridden `post()`: it wraps `super().post()` and,
  only when voice input occurred (`_did_transcribe`), calls
  `_augment_with_audio()` which synthesizes **only** the envelope's `response`
  field (== `AIMessage.response`) via a lazily-imported `VoiceSynthesizer`,
  attaching `audio_base64` + `audio_format`. `output`/`data`/`media` stay in
  `content` and never pass through the synthesizer.
- Graceful degradation: TTS failures `(ValueError, RuntimeError, ImportError)`
  → text-only (original 200 response returned, no `audio_base64`). A missing
  STT stack returns a clean 503; a no-audio request behaves like the inherited
  text path (TTS gated on `_did_transcribe`).
- All voice imports are lazy/inside the voice code path — server boot never
  requires `ai-parrot-integrations`.
- Tests: 8 unit tests pass (detection, STT tempfile cleanup, response-only TTS,
  audio attach, degradation, non-JSON skip, inheritance contract); `ruff` clean.

**Deviations from spec**: The spec's design note offered two strategies; I
delegated to the inherited path (option (a)) by intercepting the two reachable
polymorphic seams — `handle_upload()` (inbound, where the inherited `post()`
already reads the upload) and `post()`-wrapping (outbound). This keeps the text
hot-path pristine without copy-pasting `post()`. The full `post()` round-trip
(behind the auth decorators) is exercised by the TASK-1513 integration test.
