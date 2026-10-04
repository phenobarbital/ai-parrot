# TASK-3621: Google WAV output and Telegram MIME-aware conversion

**Feature**: FEAT-591 — speech_report pluggable TTS backends (fast-path)
**Spec**: `sdd/specs/speech-report-models.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implement spec §3 M3 as an independent compatibility change: Gemini PCM becomes truthful WAV and Telegram decodes by source MIME before OGG/Opus encoding.

## Scope

- Wrap Google raw PCM in 24 kHz mono s16le WAV without double wrapping.
- Replace Telegram’s raw-PCM-only converter with MIME-aware conversion.
- Update the focused backend and voice-reply tests.

**NOT in scope**: backend routing, shared cache, or Polly.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py` | MODIFY | PCM-to-WAV result |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | MIME-aware OGG converter |
| `packages/ai-parrot-integrations/tests/voice/tts/test_google_backend.py` | MODIFY | WAV assertions |
| `packages/ai-parrot-integrations/tests/test_telegram_voice_reply.py` | MODIFY | MIME conversion tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .backend import AbstractTTSBackend  # verified: google_backend.py:18
from .models import SynthesisResult  # verified: google_backend.py:19
```

### Existing Signatures to Use
```python
# google_backend.py:97
async def GoogleTTSBackend.synthesize(self, text: str, *, voice: Optional[str] = None, mime_format: str = "audio/ogg", language: Optional[str] = None) -> SynthesisResult: ...
# telegram/wrapper.py:3458
def _convert_pcm_to_ogg(raw_pcm: bytes) -> bytes: ...
```

### Does NOT Exist
- `GoogleTTSBackend._pcm_to_wav` and `TelegramAgentWrapper._tts_audio_to_ogg` do not exist.
- Supertonic’s instance WAV helper is not reusable by Google.

## Complexity Contract
```json
{"schema_version":1,"targets":[{"path":"packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py","action":"MODIFY"},{"path":"packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py","action":"MODIFY"},{"path":"packages/ai-parrot-integrations/tests/voice/tts/test_google_backend.py","action":"MODIFY"},{"path":"packages/ai-parrot-integrations/tests/test_telegram_voice_reply.py","action":"MODIFY"}],"contract_symbols":["sym:packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py#GoogleTTSBackend"]}
```

## Implementation Blueprint

### Steps (in order)
1. Add stdlib `wave`/`io` helper returning RIFF WAV with rate 24000, one channel, sample width two — *why*: output bytes and MIME must agree.
2. In `synthesize`, preserve an already-RIFF response and otherwise return WAV with `audio/wav` — *why*: prevents double container headers.
3. Replace raw-only Telegram conversion with `AudioSegment.from_file` for WAV/MP3/OGG and raw PCM fallback — *why*: existing output formats remain supported.
4. Add tests for WAV metadata/double wrapping and every MIME branch.

### MODIFY anchors
```text
google_backend.py: `return SynthesisResult(audio=audio_bytes, mime_format=mime_format)` (occurrences: 1): replace result construction.
wrapper.py: `def _convert_pcm_to_ogg(raw_pcm: bytes) -> bytes:` (occurrences: 1): replace nested converter and call site.
test_google_backend.py: `async def test_google_backend_returns_correct_mime_format():` (occurrences: 1): update and extend tests.
test_telegram_voice_reply.py: `return_value=SynthesisResult(audio=audio, mime_format="audio/ogg")` (occurrences: 1): add parametrized MIME fixtures.
```

### FILL IN checklist
- [ ] OGG output is still exported with `libopus`.
- [ ] Unknown MIME remains legacy raw PCM at 24 kHz mono s16le.

## Acceptance Criteria

- [ ] AC5, AC11, and AC12 of FEAT-591 pass.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/voice/tts/test_google_backend.py -v`
- `pytest packages/ai-parrot-integrations/tests/test_telegram_voice_reply.py -v`

### Completion Note

Implemented by a prior interrupted sdd-worker/parrot-sdd-coder session and merged into
the feature branch at commit `537110c0d` (+lint autofix `7eab199f3`, merge commit
`0c0ab2b00`); this session resumed the feature, found the code already merged with the
per-spec index stuck at `in-progress`, and finalized SDD bookkeeping only — no
implementation changes were made here.

Verified before closing:
- File fidelity: `git show --stat 537110c0d` matches the task's file contract exactly
  (4 files, all listed MODIFY targets, no unlisted files).
- Task's own Validation Commands (`PYTHONPATH=packages/ai-parrot-integrations/src`,
  matching this distribution only): `test_google_backend.py` and
  `test_telegram_voice_reply.py` both pass clean.
- The `coder_run_validation(tier="merge")` gate could not settle for the same reason
  documented on TASK-3619's Completion Note: the full `packages/ai-parrot-integrations/
  tests` merge-tier sweep hangs deterministically, unrelated to this task's diff —
  filed as `issue:312c1988479b` [critical].

Feedback/review recording: none — this execution did not dispatch or observe this
attempt (it ran under a prior, now-lost execution id), so no `attempt_uid` is
available to attribute `coder_record_feedback`/`coder_record_review` to. No confirmed
defect was found in the delivered code.
