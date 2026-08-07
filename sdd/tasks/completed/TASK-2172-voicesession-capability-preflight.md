# TASK-2172: VoiceSession: capability preflight + capability_notice frames

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2171
**Assigned-to**: unassigned
**Parallel-safe**: no — Builds directly on TASK-2171's threading in the same file.

---

## Context

With `VoiceCapabilities` in place (TASK-2165) the session can stop letting
unsupported requests fail silently or mysteriously. Two checks are wanted:

1. **Audio-format preflight** — compare `VoiceConfig.input_format`/
   `output_format` and sample rates against what the client declares, and fail
   at construction. Today both providers happen to agree (16 kHz PCM in /
   24 kHz PCM out), so this is descriptive — but it is what makes a future
   non-PCM provider a declarable difference rather than garbled audio.
2. **Knob notices** — when the caller requests something the provider does not
   natively support (the canonical case: `stt_only=True` on Nova), log once and
   emit a `capability_notice` frame so the UI can be honest. Never raise.

Implements: **Spec §3 Module 6 (preflight)**.

---

## Scope

- Add a construction-time preflight in `VoiceSession.__init__` comparing the
  configured formats/sample rates against `client.voice_capabilities`; raise a
  clear `ValueError` naming both sides on mismatch.
- Add a per-session check of the projected options against the descriptor; for
  each unsupported-but-requested knob, log once at `warning` and emit one
  `capability_notice` frame (fields: `type`, `session_id`, `capability`,
  `provider`, `message`).
- Emit each notice at most once per session, not per turn and not per frame.
- Tests per spec §4.

**NOT in scope**: changing any client's behavior; making unsupported knobs
raise (they must not — spec §7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/voice/session.py` | MODIFY | Preflight + notice emission |
| `packages/ai-parrot/tests/voice/test_voice_session_capabilities.py` | CREATE | Preflight + notice tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.voice.session import VoiceSession                        # voice/session.py:36
from parrot.models.voice import (                                    # models/voice.py
    AudioFormat, VoiceCapabilities, VoiceConfig, VoiceStreamOptions,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/voice/session.py
class VoiceSession:
    def __init__(self, client, send_fn, system_prompt,        # line 53
                 voice_config=None, session_id=None) -> None:
        self.voice_config = voice_config or VoiceConfig()     # line 64
        self.session_id = session_id or str(uuid.uuid4())     # line 65
        self.logger = logger.getChild("session")              # line 66

    async def _send(self, payload: dict) -> None:             # line 318

# packages/ai-parrot/src/parrot/models/voice.py
input_format: AudioFormat = AudioFormat.PCM_16K               # line 63
output_format: AudioFormat = AudioFormat.PCM_24K              # line 64
input_sample_rate: int = 16000                                # line 65
output_sample_rate: int = 24000                               # line 66
```

### Does NOT Exist

- ~~`UnsupportedVoiceCapability`~~ — no such exception exists. Use a plain `ValueError` for the format mismatch; do not introduce a new exception type unless the spec asks for one (it does not).
- ~~Any format negotiation in the codebase~~ — none exists; sample rates are hardcoded assumptions today.
- ~~A `capability_notice` frame type~~ — new; no frontend consumes it yet, so it must be additive and ignorable.
- ~~Raising on an unsupported knob~~ — explicitly forbidden by spec §7: `stt_only=True` on Nova must proceed.

---

## Implementation Notes

### Key Constraints
- The format preflight raises; the knob check does not. Getting this backwards
  breaks the resolved Nova STT-only decision.
- Emit notices from a single place with a `set` of already-notified capability
  names on the session, so re-entry per turn cannot duplicate them.
- `capability_notice` is informational and additive — existing frontends must be
  able to ignore an unknown frame type without breaking.
- Keep `_send()`'s `ConnectionResetError` suppression semantics
  (`voice/session.py:318-326`) for notice frames too.

---

## Acceptance Criteria

- [ ] Mismatched `AudioFormat` raises at construction with both sides named
- [ ] Matching formats construct normally (both current providers)
- [ ] `stt_only=True` against Nova emits one `capability_notice` and does NOT raise
- [ ] A notice is emitted at most once per session across multiple turns
- [ ] Supported knobs emit no notice
- [ ] Tests pass: `pytest packages/ai-parrot/tests/voice/ -v`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# packages/ai-parrot/tests/voice/test_voice_session_capabilities.py
import pytest
from parrot.models.voice import AudioFormat, VoiceConfig
from parrot.voice.session import VoiceSession


class TestFormatPreflight:
    def test_mismatch_raises_at_construction(self, pcm24_only_client):
        with pytest.raises(ValueError, match="format"):
            VoiceSession(pcm24_only_client, send_fn=..., system_prompt="x",
                         voice_config=VoiceConfig(input_format=AudioFormat.PCM_16K))

    def test_matching_formats_ok(self, standard_client):
        VoiceSession(standard_client, send_fn=..., system_prompt="x")


class TestCapabilityNotices:
    async def test_stt_only_on_nova_notifies_not_raises(self, nova_like_client, frames):
        session = VoiceSession(nova_like_client, send_fn=..., system_prompt="x",
                               voice_config=VoiceConfig(provider="nova"))
        await session.start_turn()
        assert any(f["type"] == "capability_notice" for f in frames)

    async def test_notice_emitted_once_per_session(self, nova_like_client, frames):
        ...
        assert len([f for f in frames if f["type"] == "capability_notice"]) == 1

    async def test_supported_knob_silent(self, standard_client, frames):
        assert not [f for f in frames if f["type"] == "capability_notice"]
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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-07
**Notes**: Added `_preflight_audio_formats()`, called from `__init__`
(after `self.voice_config`/`self.client` are set) — compares
`input_format`/`output_format`/`input_sample_rate`/`output_sample_rate`
against `client.voice_capabilities`'s declared sets, raising a `ValueError`
naming both the requested and supported side on any mismatch. Added
`_check_capability_notices(options)`, called once per `_run_turn()` loop
iteration (including reconnects) right after projecting `options` and
right before `stream_voice()` — currently implements the one concrete
mismatch case that exists today (`stt_only=True` requested against a
provider with `native_stt_only=False`, i.e. Nova), tracked via a
`self._notified_capabilities: set` so it fires at most once per session
regardless of turn count. Structured as an extensible per-knob check
(one `if` block per capability) rather than a generic loop, since only
`stt_only` has an actual unsupported case among the 9
`VoiceStreamOptions` fields today (both providers now support voice
override, per-call inference, and top_p post TASK-2166-2170) — adding
the next knob-mismatch case is a few lines, not a refactor.

**Deviation from the task's literal scope, needed to make it testable**:
neither `VoiceConfig` nor `VoiceSession` had any existing way to request
`stt_only=True` for a turn — `VoiceConfig.to_stream_options()` always
projects `stt_only=False` unless overridden by an explicit kwarg, and
`VoiceSession._run_turn()` called `to_stream_options()` with zero
overrides. The task's own test scaffold assumes this already works
(`VoiceSession(nova_like_client, ..., voice_config=VoiceConfig(provider="nova"))`
with no other stt_only signal, yet expects a notice). Since TASK-2172's
file table authorizes ONLY `voice/session.py` (not `models/voice.py`),
I added `stt_only: bool = False` as a new optional `VoiceSession.__init__`
keyword parameter (backward compatible — verified the integrations
handler's only call site uses keyword args) and thread it into
`to_stream_options(stt_only=self.stt_only)` in `_run_turn()`. This is a
minimal, additive constructor surface entirely within the authorized
file, not a redesign — flagging it explicitly since it's an addition the
task text didn't spell out verbatim.

While running the full `tests/voice/` suite, found that TASK-2172's own
preflight breaks EVERY pre-existing `VoiceCapable` test double across
`test_voice_session.py`, `test_voice_reconnection.py`, and
`test_voice_session_options.py` (from TASK-2171) — none of them defined
`voice_capabilities`. Fixed in a separate preceding commit (adds a
PCM-16k/24k `VoiceCapabilities` double to each mock class matching
`VoiceConfig()`'s defaults; no assertions changed). 11 new tests in
`tests/voice/test_voice_session_capabilities.py`. Full voice-domain
regression green (30 tests in `tests/voice/`, plus the broader
`tests/clients/`/`tests/bots/` voice suites) except the already-documented
pre-existing failures (`test_no_aiohttp_import`,
`test_nova_protocol_frames.py::TestOpeningSequence` ×4,
`test_parallel_tool_execution.py::test_parallel_error_isolation`,
3 unrelated prompt/preset tests) — all independently confirmed to
reproduce on `dev`.

**Deviations from spec**: the `VoiceSession.__init__(stt_only=...)`
addition described above — needed to make the task's own acceptance
criteria and test scaffold actually exercisable, entirely within the
one file this task authorizes.
