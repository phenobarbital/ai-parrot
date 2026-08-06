# TASK-2164: VoiceStreamOptions + VoiceCapabilities contract types

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel-safe**: no — Foundation for every other task in this feature — nothing can start before it.

---

## Context

FEAT-416 unified `VoiceConfig` but left three divergent paths for turning
that config into per-call arguments: `VoiceBot.ask_stream()` builds an ad-hoc
dict (`bots/voice.py:539-545`), `VoiceSession._run_turn()` builds nothing at
all (`voice/session.py:182-186`), and the integrations handler goes through
`VoiceBot`. This task creates the single projection every caller will use, plus
the capability descriptor the rest of the feature depends on.

This is the foundation task — Modules 2-12 all build on these two types.

Implements: **Spec §3 Module 1**.

---

## Scope

- Add a frozen `VoiceStreamOptions` dataclass to `parrot/models/voice.py` with
  exactly the 9 fields listed in spec §2 Data Models and the documented defaults.
- Add a frozen `VoiceCapabilities` dataclass with the behavioral, session,
  inference, audio-format and synthesis fields from spec §2 Data Models.
- Add `VoiceConfig.to_stream_options(**overrides) -> VoiceStreamOptions`, where
  explicit `overrides` beat config-derived values — preserving the precedence
  `VoiceBot.ask_stream()` implements today at `bots/voice.py:539-545`.
- Export both new names from the module.
- Write unit tests for defaults, projection, override precedence, frozen-ness,
  and that the audio-format sets are populated.

**NOT in scope**: touching `VoiceCapable` (TASK-2165), any client
(TASK-2166/2169), `VoiceSession` (TASK-2171), or `VoiceBot` (TASK-2173).
Do NOT change any existing `VoiceConfig` field or default.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/voice.py` | MODIFY | Add both dataclasses + `to_stream_options()` |
| `packages/ai-parrot/tests/models/test_voice_contract.py` | CREATE | Unit tests for the new types |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.models.voice import VoiceConfig, VoiceProvider, AudioFormat  # models/voice.py:49, :30, :24
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/voice.py
class AudioFormat(Enum):                                  # line 24
    PCM_16K = "audio/pcm;rate=16000"                      # line 26
    PCM_24K = "audio/pcm;rate=24000"                      # line 27

class VoiceProvider(str, Enum):                           # line 30
    GOOGLE_LIVE = "google_live"                           # line 40
    OPENAI_REALTIME = "openai_realtime"                   # line 41
    WHISPER_TTS = "whisper_tts"                           # line 42
    NOVA = "nova"                                         # line 46

@dataclass
class VoiceConfig:                                        # line 49
    provider: VoiceProvider = VoiceProvider.GOOGLE_LIVE   # line 60
    input_format: AudioFormat = AudioFormat.PCM_16K       # line 63
    output_format: AudioFormat = AudioFormat.PCM_24K      # line 64
    input_sample_rate: int = 16000                        # line 65
    output_sample_rate: int = 24000                       # line 66
    model: Optional[str] = None                           # line 72
    voice_name: str = "Puck"                              # line 73
    language: str = "en-US"                               # line 74
    temperature: float = 0.7                              # line 77
    max_tokens: int = 4096                                # line 78
    top_p: float = 0.9                                    # line 79
    enable_input_transcription: bool = True               # line 87
    enable_output_transcription: bool = True              # line 88
    reconnect_on_limit: bool = True                       # line 93
    max_reconnects: int = 3                               # line 94
    parallel_tool_execution: bool = False                 # line 97
    def __post_init__(self):                              # line 99 — coerces str -> VoiceProvider
    def get_model(self) -> str:                           # line 107 — the ONLY other method
```

### Does NOT Exist

- ~~`VoiceStreamOptions`~~ / ~~`VoiceCapabilities`~~ — created by THIS task; they do not exist yet.
- ~~`VoiceConfig.to_stream_options()`~~ — created by THIS task. `get_model()` (`models/voice.py:107`) is currently the only method besides `__post_init__`.
- ~~Pydantic in this module~~ — `models/voice.py` uses stdlib `dataclasses` + `Enum` only. Do NOT introduce `BaseModel` here.
- ~~`AudioFormat.OPUS`~~ / any format beyond `PCM_16K`/`PCM_24K` — only those two exist (`models/voice.py:26-27`).

---

## Implementation Notes

### Pattern to Follow
Match the existing file exactly: stdlib `@dataclass`, `Enum`, Google-style
docstrings. Both new classes are `@dataclass(frozen=True)` — `VoiceConfig`
itself stays mutable (the provider-switch test at
`tests/bots/test_voicebot_provider_switch.py:101` relies on mutating it).

### Key Constraints
- `VoiceStreamOptions` defaults MUST match `VoiceConfig`'s: `temperature=0.7`,
  `max_tokens=4096`, `top_p=0.9`, `language="en-US"`, transcription flags
  `True`, `stt_only=False`, `parallel_tool_execution=False`, `voice=None`.
- `voice=None` means "provider default" — do NOT default it to `"Puck"`; that
  string is Gemini-specific and leaking it into Nova is the bug this feature
  fixes (`bots/voice.py:198`).
- Use `frozenset` for the collection fields so the descriptor stays hashable.
- `max_output_tokens` in `VoiceCapabilities` is an `int`; spec §8 leaves Nova's
  real ceiling open — use `4096` as a documented placeholder and add a TODO
  pointing at spec §8, do not invent a number.

---

## Acceptance Criteria

- [ ] `VoiceStreamOptions` exists, is frozen, has the 9 documented fields with the documented defaults
- [ ] `VoiceCapabilities` exists, is frozen, and includes `input_formats`/`output_formats`/sample-rate sets
- [ ] `VoiceConfig.to_stream_options()` projects all shared fields; `**overrides` win
- [ ] No existing `VoiceConfig` field or default changed
- [ ] Tests pass: `pytest packages/ai-parrot/tests/models/test_voice_contract.py -v`
- [ ] Existing voice tests still pass: `pytest packages/ai-parrot/tests/voice/ packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/voice.py`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# packages/ai-parrot/tests/models/test_voice_contract.py
import dataclasses
import pytest
from parrot.models.voice import (
    AudioFormat, VoiceCapabilities, VoiceConfig, VoiceProvider, VoiceStreamOptions,
)


class TestVoiceStreamOptions:
    def test_defaults_match_voice_config(self):
        opts, cfg = VoiceStreamOptions(), VoiceConfig()
        assert (opts.temperature, opts.max_tokens, opts.top_p) == (
            cfg.temperature, cfg.max_tokens, cfg.top_p)

    def test_voice_defaults_to_none_not_puck(self):
        """'Puck' is Gemini-specific; leaking it into Nova is the bug we fix."""
        assert VoiceStreamOptions().voice is None

    def test_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            VoiceStreamOptions().temperature = 0.1


class TestProjection:
    def test_projects_config_values(self):
        cfg = VoiceConfig(temperature=0.2, max_tokens=8192, top_p=0.5)
        opts = cfg.to_stream_options()
        assert (opts.temperature, opts.max_tokens, opts.top_p) == (0.2, 8192, 0.5)

    def test_overrides_win(self):
        cfg = VoiceConfig(temperature=0.2)
        assert cfg.to_stream_options(temperature=0.9).temperature == 0.9


class TestVoiceCapabilities:
    def test_declares_audio_formats(self):
        caps = VoiceCapabilities(
            provider=VoiceProvider.NOVA, native_stt_only=False, supports_top_p=True,
            supports_per_call_voice=True, supports_per_call_inference=True,
            parallel_tool_execution=True, emits_reconnect_signal=True,
            supports_session_resumption=False, max_session_seconds=465.0,
            max_output_tokens=4096,
            input_formats=frozenset({AudioFormat.PCM_16K}),
            output_formats=frozenset({AudioFormat.PCM_24K}),
            input_sample_rates=frozenset({16000}), output_sample_rates=frozenset({24000}),
            voice_catalog=frozenset({"matthew"}), default_voice="matthew",
        )
        assert caps.input_formats and caps.output_formats
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
