---
type: Wiki Overview
title: 'TASK-006: Avatar session orchestrator (M5)'
id: doc:sdd-tasks-completed-task-006-avatar-session-orchestrator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 5** (spec §3) — the Phase A glue. It opens a LiveAvatar
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

# TASK-006: Avatar session orchestrator (M5)

**Feature**: FEAT-242 — LiveAvatar Phase A (avatar as the "mouth" of AgentChat)
**Spec**: `sdd/specs/liveavatar-phase-a-mouth.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-002, TASK-003, TASK-004, TASK-005
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** (spec §3) — the Phase A glue. It opens a LiveAvatar
session (LITE, with `livekit_config` so the avatar joins our room), consumes
`ask_stream()`, runs the flattener + sentence segmenter, synthesizes each
sentence to PCM via `VoiceSynthesizer`/Supertonic, and pushes PCM frames to the
`AvatarWebSocket`. Owns session lifecycle (keep-alive, guaranteed stop).
Capability: avatar orchestration.

---

## Scope

- Implement `AvatarSessionOrchestrator` in `orchestrator.py` with
  `async def run(self, agent_name, session_id, tenant_id) -> AvatarSessionHandle`.
- Wire the components from prior tasks:
  1. `LiveKitRoomManager.mint_room_tokens` → `livekit_config` (TASK-004).
  2. `LiveAvatarClient.create_session_token(..., livekit_config=...)` + `start_session` (TASK-002).
  3. Open `AvatarWebSocket`, await `connected` (TASK-003).
  4. Iterate `bot.ask_stream(question)`; for each `str` chunk → `SpeakableFlattener.feed` (TASK-005);
     for the final `AIMessage` sentinel → `flush()` + stop speaking.
  5. Per complete sentence → `VoiceSynthesizer` (Supertonic `synthesize_pcm`) → `AvatarWebSocket.send_audio_frame`.
- Guarantee `stop_session` + WS close + keep-alive cancel in `finally`.
- Per-sentence streaming to reduce TTFB (begin speaking before the full answer).
- Graceful degradation: on TTS failure, log and continue text-only (do not crash the turn).

**NOT in scope**: HTTP endpoint / avatar-mode flag (TASK-007), opt-in gating
(TASK-008), frontend (TASK-009). Do NOT modify `ask_stream` or `VoiceSynthesizer`
internals — call them as-is.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/orchestrator.py` | CREATE | `AvatarSessionOrchestrator` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` | MODIFY | Re-export `AvatarSessionOrchestrator` |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_orchestrator.py` | CREATE | Streaming + lifecycle tests (fakes) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-18.

### Verified Imports
```python
import asyncio
import logging
from typing import Optional
from parrot.integrations.liveavatar import (
    LiveAvatarClient, AvatarWebSocket, LiveKitRoomManager, SpeakableFlattener,
)
from parrot.integrations.liveavatar.models import AvatarSessionHandle
from parrot.voice.tts.synthesizer import VoiceSynthesizer            # verified: ai-parrot-integrations
# AIMessage type comes from the bot's ask_stream iterator (see below); import from
# parrot.models.responses only if a type check is needed:
from parrot.models.responses import AIMessage                       # verified: responses.py:72
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/base.py:1456
async def ask_stream(self, question, ...) -> AsyncIterator[Union[str, AIMessage]]: ...
#   yields plain str chunks, then a final AIMessage sentinel.

# packages/ai-parrot/src/parrot/models/responses.py:72
class AIMessage(BaseModel):
    response: Optional[str]; output: Any; data: Optional[Any]; code: Optional[str]
    tool_calls: List[ToolCall]; output_mode: OutputMode; artifact_id: Optional[str]
    @property
    def to_text(self) -> str: ...                       # line 249

# packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py:528
def synthesize_pcm(self, text: str, *, voice=None, language=None,
                   silence_duration: float = 0.3) -> bytes: ...
#   returns raw PCM int16 LE mono 24 kHz — NO resampling needed before AvatarWebSocket.

# packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py:22,53
class VoiceSynthesizer:
    def _get_backend(self) -> AbstractTTSBackend: ...   # string-dispatch (google|supertonic)
#   Use the supertonic backend; reach synthesize_pcm via the SupertonicONNXBackend/pipeline.
#   Confirm the public path from VoiceSynthesizer to synthesize_pcm at impl
#   (VoiceSynthesizer.synthesize() returns SynthesisResult; for raw PCM use the
#    supertonic pipeline's synthesize_pcm directly).
```

### Does NOT Exist (do NOT reference)
- ~~a "speak text" command on LiveAvatar~~ — LITE Mode pushes PCM only (via AvatarWebSocket).
- ~~partial-token emission over `/ws/userinfo`~~ — streaming is `ask_stream()`; consume it directly (spec §6).
- ~~`VoiceSynthesizer.synthesize_pcm`~~ — `synthesize_pcm` lives on the Supertonic
  pipeline (`supertonic_inference.py:528`), NOT on `VoiceSynthesizer`. Verify the
  exact call path before use.

---

## Implementation Notes

### Pattern to Follow
```python
class AvatarSessionOrchestrator:
    def __init__(self, bot, *, client: LiveAvatarClient, room_manager: LiveKitRoomManager,
                 synthesizer: VoiceSynthesizer):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        ...

    async def run(self, agent_name, session_id, tenant_id=None) -> AvatarSessionHandle:
        tokens = self.room_manager.mint_room_tokens(room=session_id, identity=agent_name)
        handle = await self.client.create_session_token(self.cfg, livekit_config={...tokens...})
        try:
            await self.client.start_session(handle)
            async with AvatarWebSocket(handle) as ws:
                flattener = SpeakableFlattener()
                async for item in self.bot.ask_stream(question):
                    if isinstance(item, str):
                        for sentence in flattener.feed(item):
                            await self._speak(ws, sentence)
                    else:  # AIMessage sentinel
                        for sentence in flattener.flush():
                            await self._speak(ws, sentence)
                await ws.finish_speaking()
            return handle
        finally:
            await self.client.stop_session(handle)
```

### Key Constraints
- Async throughout; per-sentence speak to minimize TTFB.
- `finally` guarantees stop_session + WS close + keep-alive cancel.
- TTS failure → log + continue (text still rendered in UI by the existing path).
- Do NOT resample PCM — `synthesize_pcm` already returns 24 kHz mono 16-bit.

### Open Question to surface (do NOT guess)
- **P6 Supertonic chunking**: per-sentence latency / 400 ms-first-chunk feasibility
  on target hardware is unconfirmed. Keep synthesis per-sentence; add a `# TODO P6`
  where chunk timing would be tuned. Do NOT pre-optimize with a sub-sentence splitter.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/stream.py:197` — streaming consumer reference
- `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py:268` — TTS-out degradation pattern

---

## Acceptance Criteria

- [ ] `from parrot.integrations.liveavatar import AvatarSessionOrchestrator` works
- [ ] `test_orchestrator_streams_per_sentence`: `ask_stream` chunks → one PCM push per complete sentence
- [ ] `test_supertonic_pcm_format`: synthesized bytes are PCM int16 LE mono 24 kHz (no resampling)
- [ ] `test_session_lifecycle_stop_on_error` (orchestrator level): `stop_session` runs even when streaming raises
- [ ] TTS failure on one sentence does not abort the turn (graceful degradation)
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_orchestrator.py -v`
- [ ] No lint errors: `ruff check .../liveavatar/orchestrator.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_orchestrator.py
import pytest
from parrot.integrations.liveavatar import AvatarSessionOrchestrator


async def test_orchestrator_streams_per_sentence(fake_bot, fake_client, fake_ws, fake_room_mgr):
    """Two-sentence stream → two PCM pushes."""
    ...


async def test_session_lifecycle_stop_on_error(fake_bot_raises, fake_client, ...):
    """stop_session called on the error path."""
    ...
```

---

## Agent Instructions

1. Read spec §2 (orchestrator interface), §3 Module 5, §6 (ask_stream / synthesize_pcm).
2. Verify the Codebase Contract — especially the `VoiceSynthesizer` → `synthesize_pcm` call path.
3. Implement `AvatarSessionOrchestrator`, wiring TASK-002..005.
4. Run tests + ruff. Move file to `completed/`, update index, fill Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-18
**Notes**: All 3 unit tests pass, lint clean. ``synthesize_pcm_fn`` is an
injectable callable (decouples from ONNX at test time). ``synthesize_pcm`` path:
``SupertonicPipeline.synthesize_pcm()`` injected directly, not via
``VoiceSynthesizer.synthesize()`` (which returns WAV, not raw PCM). ``# TODO P6``
comment placed at the per-sentence speak call. ``stop_session`` guaranteed in
``finally``. TTS failure is logged and skipped (graceful degradation).
``SpeakableFlattener`` bug fixed: trailing whitespace from chunks is the
sentence boundary signal — ``_strip_markdown`` no longer strips trailing ws
before splitting (needed to detect "First sentence. " + "Second sentence." as 2 sentences).
**Deviations from spec**: None. ``synthesize_pcm_fn`` injection is cleaner than
importing ``SupertonicPipeline`` at construction time; ``make_supertonic_pcm_fn()``
factory provided for production wiring.
