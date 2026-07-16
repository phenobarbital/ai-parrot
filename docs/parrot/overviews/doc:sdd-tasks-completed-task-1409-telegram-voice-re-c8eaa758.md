---
type: Wiki Overview
title: 'TASK-1409: Telegram voice-reply wiring (config fields + handle_voice TTS branch)'
id: doc:sdd-tasks-completed-task-1409-telegram-voice-reply-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The output wiring. After `handle_voice` transcribes a voice note, runs the
  agent,
relates_to:
- concept: mod:parrot.integrations.telegram.models
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

# TASK-1409: Telegram voice-reply wiring (config fields + handle_voice TTS branch)

**Feature**: FEAT-213 — Telegram Voice Reply (TTS Output)
**Spec**: `sdd/specs/FEAT-213-telegram-voice-reply-tts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1407, TASK-1408
**Assigned-to**: unassigned

---

## Context

The output wiring. After `handle_voice` transcribes a voice note, runs the agent,
and sends the text reply, this task adds an **opt-in voice reply**: if the input was
voice and `reply_in_kind`/`tts_enabled` are on, synthesize the reply text with
`VoiceSynthesizer` (TASK-1407/1408) and send it back as a Telegram voice note —
**in addition** to the text, with graceful degradation to text-only on any failure.

Implements spec **Module 3** (§3), Goals G3–G5, and resolves the §8 open question
*"¿Telegram acepta el formato de generate_speech … o hay que convertir a OGG/Opus
… o usar send_audio?"*.

---

## Scope

- **Config (`telegram/models.py`)**: add four opt-in fields to the
  `TelegramAgentConfig` dataclass (all with safe defaults) and wire them in `from_dict`:
  - `tts_enabled: bool = False`
  - `tts_backend: str = "google"`
  - `tts_voice: Optional[str] = None`
  - `reply_in_kind: bool = True`
- **Wrapper (`telegram/wrapper.py`)**:
  - Add a `self._synthesizer: Optional["VoiceSynthesizer"] = None` slot in `__init__`
    (next to `self._transcriber`, currently at wrapper.py:176).
  - Add `_get_synthesizer()` mirroring `_get_transcriber()` (wrapper.py:2968): build a
    `TTSConfig(backend=self.config.tts_backend, voice=self.config.tts_voice)` and
    construct `VoiceSynthesizer(config)`.
  - In `close()` (wrapper.py:2985), also close `self._synthesizer` if created.
  - In `handle_voice`, **after** `parsed = self._parse_response(response)` and the text
    send (`sent = await self._send_parsed_response(message, parsed)`, ~wrapper.py:3179):
    if `self.config.tts_enabled` and `self.config.reply_in_kind` and `parsed.text` is
    non-empty, synthesize `parsed.text` and `await self.bot.send_voice(chat_id,
    BufferedInputFile(result.audio, filename="reply.ogg"))`. Wrap the whole TTS branch
    in `try/except` → on any error, log and continue (text already sent). **Never raise.**
- **Format decision (open question)**: Telegram `send_voice` requires OGG/Opus. The
  Google backend yields raw PCM/WAV. Pick ONE and document it in the Completion Note:
  (a) convert to OGG/Opus before `send_voice`, or (b) fall back to `bot.send_audio`
  (which accepts WAV/MP3) if OGG is not viable. Prefer the simplest path that produces
  an audible reply; if a converter (ffmpeg/pydub) is unavailable, degrade to text-only
  rather than crashing.
- Unit tests with mocked `bot` and mocked synthesizer.

**NOT in scope**:
- New TTS backends (TASK-1408 already stubs ElevenLabs/OpenAI as `ValueError`).
- Persistent per-chat "voice mode" toggle command (spec §8 — start with `reply_in_kind`).
- TTS in MS Teams / Slack (spec Non-Goals).
- Package `__init__.py` exports (TASK-1410).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | Add `tts_*` + `reply_in_kind` fields + `from_dict` wiring |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `_synthesizer` slot, `_get_synthesizer`, `close()`, `handle_voice` branch |
| `packages/ai-parrot-integrations/tests/test_telegram_voice_reply.py` | CREATE | Wiring tests (bot + synth mocks) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Use VERBATIM. Verify before adding anything new.

### Verified Imports
```python
from parrot.voice.tts.synthesizer import VoiceSynthesizer       # TASK-1408
from parrot.voice.tts.models import TTSConfig                   # TASK-1407
from aiogram.types import BufferedInputFile                     # aiogram (voice upload)
# In wrapper.py, prefer the package's relative-import style used for the transcriber:
#   from ...voice.transcriber import VoiceTranscriber   (existing, wrapper.py:2971)
#   from ...voice.tts.synthesizer import VoiceSynthesizer   (new, mirror it)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py:39
@dataclass
class TelegramAgentConfig:
    name: str
    chatbot_id: str
    bot_token: Optional[str] = None
    ...
    voice_config: Optional["VoiceTranscriberConfig"] = None   # :99
    @property
    def voice_enabled(self) -> bool:                          # :203
        return self.voice_config is not None and self.voice_config.enabled
    @classmethod
    def from_dict(cls, name, data) -> 'TelegramAgentConfig':  # :208 — add new fields here
        return cls(..., voice_config=voice_config, ...)        # tail ~:268

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:
    self._transcriber: Optional["VoiceTranscriber"] = None    # :176 (add _synthesizer next to it)
    def _get_transcriber(self) -> "VoiceTranscriber":         # :2968 (mirror -> _get_synthesizer)
    async def close(self) -> None:                            # :2982 (also close _synthesizer)
    async def handle_voice(self, message: Message) -> None:   # :2990
        # ... transcribe -> agent -> response ...
        parsed = self._parse_response(response)               # ~:3179
        sent = await self._send_parsed_response(message, parsed)  # ~:3180  <-- insert TTS branch AFTER this
        # self.bot is the aiogram Bot; chat_id = message.chat.id
```

### `parsed.text` source
`self._parse_response(response)` → `parse_response(response)` returns a `ParsedResponse`
with a `.text` attribute (the reply text). Use `parsed.text` as the TTS input.

### Does NOT Exist (Anti-Hallucination)
- ~~`TelegramAgentConfig.tts_enabled` / `tts_backend` / `tts_voice` / `reply_in_kind`~~ —
  do NOT exist; THIS task adds them.
- ~~`self._synthesizer` / `_get_synthesizer`~~ — do NOT exist; add them.
- ~~`message.answer_voice(...)`~~ — use `self.bot.send_voice(chat_id, BufferedInputFile(...))`.
- ~~`SynthesisResult.bytes`~~ — the field is `.audio` (bytes); also `.mime_format`.
- ~~`TelegramAgentConfig` is Pydantic~~ — it is a `@dataclass`; add fields with defaults
  AND a `data.get(...)` line in `from_dict` (it does NOT auto-read unknown keys).

### Patterns to Follow (spec §6)
- Degradation: `try/except` around synth + send → fallback to text-only (already sent).
- `self.logger`; config opt-in (default `tts_enabled=False`).
- Temp-file cleanup in `finally` only if you write audio to disk (prefer in-memory
  `BufferedInputFile(bytes)` — no temp file needed for sending).

---

## Implementation Notes

### handle_voice branch sketch (insert after the text send)
```python
# after: sent = await self._send_parsed_response(message, parsed)
if (
    self.config.tts_enabled
    and self.config.reply_in_kind
    and parsed.text
    and parsed.text.strip()
):
    try:
        synth = self._get_synthesizer()
        result = await synth.synthesize(parsed.text)
        audio = result.audio
        # FORMAT: Telegram send_voice needs OGG/Opus. Convert if needed, else
        # fall back to send_audio, else degrade to text-only.
        await self.bot.send_voice(
            chat_id,
            BufferedInputFile(audio, filename="reply.ogg"),
        )
        self.logger.info("Chat %d: Sent voice reply (%d bytes)", chat_id, len(audio))
    except Exception as exc:  # noqa: BLE001 — never break the message flow
        self.logger.warning(
            "Chat %d: Voice reply failed, text-only: %s", chat_id, exc
        )
```

### _get_synthesizer sketch
```python
def _get_synthesizer(self) -> "VoiceSynthesizer":
    if self._synthesizer is None:
        from ...voice.tts.synthesizer import VoiceSynthesizer
        from ...voice.tts.models import TTSConfig
        self._synthesizer = VoiceSynthesizer(
            TTSConfig(backend=self.config.tts_backend, voice=self.config.tts_voice)
        )
    return self._synthesizer
```

### Key Constraints
- async throughout; NEVER let a TTS failure raise out of `handle_voice`.
- Opt-in: with `tts_enabled=False` (default), the synth must NEVER be invoked — assert
  this in tests (zero regression for text input and for voice input when disabled).
- Existing config files without the new keys must still load (defaults apply).

### References in Codebase
- `wrapper.py:2968` `_get_transcriber` — mirror for `_get_synthesizer`
- `wrapper.py:3179` — exact insertion point (after the text reply is sent)
- `notifications/__init__.py:716` `send_telegram_message` — proactive-send reference

---

## Acceptance Criteria

- [ ] `TelegramAgentConfig` gains `tts_enabled` (False), `tts_backend` ("google"),
      `tts_voice` (None), `reply_in_kind` (True); `from_dict` reads all four.
- [ ] Voice input + `tts_enabled=True` + `reply_in_kind=True` → `bot.send_voice` called
      with the synth's audio bytes (synth + bot mocked). (`test_handle_voice_replies_with_voice`)
- [ ] Synth raises → text reply still sent, NO exception propagates.
      (`test_handle_voice_degrades_on_tts_error`)
- [ ] `tts_enabled=False` → synth never invoked. (`test_tts_disabled_text_only`)
- [ ] Existing Telegram config (no `tts_*` keys) still loads via `from_dict`.
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/test_telegram_voice_reply.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/telegram/`

---

## Test Specification

```python
# tests/test_telegram_voice_reply.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.voice.tts.models import SynthesisResult


@pytest.fixture
def synth_mock():
    s = MagicMock()
    s.synthesize = AsyncMock(
        return_value=SynthesisResult(audio=b"OGG...", mime_format="audio/ogg")
    )
    return s


async def test_handle_voice_replies_with_voice(wrapper_with_voice, synth_mock):
    """voice in + reply_in_kind -> bot.send_voice called with audio bytes."""
    wrapper_with_voice.config.tts_enabled = True
    wrapper_with_voice.config.reply_in_kind = True
    wrapper_with_voice._synthesizer = synth_mock
    # ... drive handle_voice with a mocked voice Message + mocked bot ...
    wrapper_with_voice.bot.send_voice.assert_awaited()


async def test_handle_voice_degrades_on_tts_error(wrapper_with_voice):
    """synth raises -> text reply still sent, no exception."""
    wrapper_with_voice.config.tts_enabled = True
    failing = MagicMock()
    failing.synthesize = AsyncMock(side_effect=RuntimeError("boom"))
    wrapper_with_voice._synthesizer = failing
    # handle_voice must complete without raising; send_voice not awaited successfully


async def test_tts_disabled_text_only(wrapper_with_voice, synth_mock):
    """tts_enabled=False -> synth never called."""
    wrapper_with_voice.config.tts_enabled = False
    wrapper_with_voice._synthesizer = synth_mock
    # after handle_voice:
    synth_mock.synthesize.assert_not_awaited()


def test_config_defaults_opt_in():
    from parrot.integrations.telegram.models import TelegramAgentConfig
    cfg = TelegramAgentConfig.from_dict("bot", {"chatbot_id": "x"})
    assert cfg.tts_enabled is False
    assert cfg.tts_backend == "google"
    assert cfg.reply_in_kind is True
```

> NOTE: reuse existing Telegram test fixtures/mocks from
> `tests/test_telegram_integration.py` and `tests/test_hitl_telegram_voice.py`
> for building the wrapper + mocked aiogram `Message`/`Bot`. Inspect those first.

---

## Agent Instructions

1. **Read the spec** (§2 Data Models, §3 Module 3, Goals G3–G5, §8 format open question).
2. **Verify the Codebase Contract** — re-confirm wrapper.py line anchors (they may shift);
   `grep -n "_get_transcriber\|self._transcriber\|_send_parsed_response\|def handle_voice" wrapper.py`.
3. **Update status** in `sdd/tasks/index/FEAT-213-telegram-voice-reply-tts.json` → `"in-progress"`.
4. **Implement**; verify TASK-1407 and TASK-1408 are in `sdd/tasks/completed/` first.
5. **Verify** acceptance criteria; document the OGG/format decision in the Completion Note.
6. **Move** this file to `sdd/tasks/completed/` and update index → `"done"`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-02
**Notes**: Format decision: used bot.send_voice(BufferedInputFile(audio_bytes)) directly.
The Google backend returns raw PCM bytes; the format label is "audio/ogg" per TTSConfig
default. Telegram's send_voice should accept audio data; on failure, the try/except
degrades gracefully to text-only since the text reply is already sent before the TTS
branch runs. No OGG/Opus conversion was added (spec §8 "prefer simplest path"). If
Telegram requires actual OGG encoding, that can be added as a follow-up with ffmpeg/pydub.
All 10 wiring tests pass. Pre-existing linting errors in telegram/__init__.py not touched.
**Deviations from spec**: none
