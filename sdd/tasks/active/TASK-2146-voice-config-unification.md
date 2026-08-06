# TASK-2146: VoiceConfig Unification

**Feature**: FEAT-416 — Voice Agent Framework
**Spec**: `sdd/specs/voice-agent-framework.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Two `VoiceConfig` dataclasses exist with overlapping but inconsistent
fields:
- Core: `parrot.models.voice.VoiceConfig` (11 fields, `provider` is a
  plain `str`)
- Integrations: `parrot.voice.models.VoiceConfig` (17 fields, `provider`
  is a `VoiceProvider` enum, adds timeouts, VAD mode)

Users importing one get different behavior from the other. This task
merges both into a single unified class in core, promotes `VoiceProvider`
to core, and adds three new fields.

Implements spec §3 Module 2.

---

## Scope

- Promote `VoiceProvider` enum from `parrot.voice.models` to
  `parrot.models.voice`.
- Merge all fields from both `VoiceConfig` classes into one unified
  dataclass in `parrot.models.voice`, adding:
  - `top_p: float = 0.9`
  - `parallel_tool_execution: bool = False`
  - `reconnect_on_limit: bool = True`
  - `max_reconnects: int = 3`
  - `input_sample_rate: int = 16000`
  - `output_sample_rate: int = 24000`
  - `vad_mode: str = "server_vad"`
  - `enable_interruption: bool = True`
  - `session_timeout_seconds: int = 1800`
  - `silence_timeout_seconds: int = 30`
- Add `__post_init__` coercion so `provider` accepts both `str` and
  `VoiceProvider` enum values.
- Make `parrot.voice.models.VoiceConfig` (integrations) a deprecation-
  warning re-export of the core class.
- Write unit tests.

**NOT in scope**: modifying VoiceBot or any client (those are later tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/models/voice.py` | MODIFY | Unified VoiceConfig + VoiceProvider enum |
| `parrot/voice/models.py` (integrations) | MODIFY | Re-export shim with deprecation warning |
| `tests/models/test_voice_config.py` | CREATE | Unit tests for unified VoiceConfig |

Note: paths are relative to `packages/ai-parrot/src/` (core) and
`packages/ai-parrot-integrations/src/` (integrations).

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Core VoiceConfig — parrot/models/voice.py:20
from parrot.models.voice import VoiceConfig, AudioFormat

# Integrations VoiceProvider — parrot/voice/models.py:24
from parrot.voice.models import VoiceProvider

# GoogleVoiceModel — used as default for model field
from parrot.models.google import GoogleVoiceModel  # check this exists
```

### Existing Signatures to Use

```python
# parrot/models/voice.py:20 (core — WILL BE REPLACED)
@dataclass
class VoiceConfig:
    model: str = GoogleVoiceModel.DEFAULT             # line 23
    provider: str = "google_live"                      # line 38
    voice_name: str = "Puck"                           # line 41
    language: str = "en-US"                            # line 42
    input_format: AudioFormat = AudioFormat.PCM_16K    # line 45
    output_format: AudioFormat = AudioFormat.PCM_24K   # line 46
    temperature: float = 0.7                           # line 49
    max_tokens: int = 4096                             # line 50
    enable_vad: bool = True                            # line 53
    enable_input_transcription: bool = True            # line 56
    enable_output_transcription: bool = True           # line 57

class AudioFormat(Enum):                               # line 13
    PCM_16K = "audio/pcm;rate=16000"
    PCM_24K = "audio/pcm;rate=24000"

# parrot/voice/models.py:24 (integrations — BECOMES SHIM)
class VoiceProvider(Enum):
    GOOGLE_LIVE = "google_live"
    OPENAI_REALTIME = "openai_realtime"
    WHISPER_TTS = "whisper_tts"
    NOVA = "nova"

# parrot/voice/models.py:156 (integrations VoiceConfig — TO BE REPLACED BY SHIM)
@dataclass
class VoiceConfig:
    provider: VoiceProvider = VoiceProvider.GOOGLE_LIVE  # line 163
    input_format: AudioFormat = AudioFormat.PCM_16K
    output_format: AudioFormat = AudioFormat.PCM_24K
    input_sample_rate: int = 16000
    output_sample_rate: int = 24000
    voice_name: str = "Puck"
    language: str = "en-US"
    enable_vad: bool = True
    vad_mode: str = "server_vad"
    enable_interruption: bool = True
    enable_input_transcription: bool = True
    enable_output_transcription: bool = True
    session_timeout_seconds: int = 1800
    silence_timeout_seconds: int = 30
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
```

### Does NOT Exist

- ~~`VoiceConfig.top_p`~~ — does not exist on either class
- ~~`VoiceConfig.parallel_tool_execution`~~ — does not exist
- ~~`VoiceConfig.reconnect_on_limit`~~ — does not exist
- ~~`VoiceConfig.max_reconnects`~~ — does not exist
- ~~`VoiceProvider` in `parrot.models.voice`~~ — only in integrations package

---

## Implementation Notes

### Pattern to Follow

The unified VoiceConfig should be a `@dataclass` (matching existing style)
with a `__post_init__` that coerces `provider` from string to enum:

```python
def __post_init__(self):
    if isinstance(self.provider, str):
        self.provider = VoiceProvider(self.provider)
```

### Deprecation Shim Pattern

```python
# parrot/voice/models.py (integrations) — add __getattr__
import warnings
from parrot.models.voice import VoiceConfig as _VoiceConfig

def __getattr__(name):
    if name == "VoiceConfig":
        warnings.warn(
            "Import VoiceConfig from parrot.models.voice instead",
            DeprecationWarning, stacklevel=2,
        )
        return _VoiceConfig
    raise AttributeError(name)
```

### Key Constraints

- `AudioFormat` enum stays in `parrot.models.voice` (already there).
- `VoiceProvider` enum moves to `parrot.models.voice`; integrations
  re-exports it (NO deprecation warning for VoiceProvider — it's a move,
  not a rename).
- The `model` field default should be `None` (not `GoogleVoiceModel.DEFAULT`)
  so the unified config is provider-agnostic. The Google-specific default is
  applied downstream in `GeminiLiveClient`.

---

## Acceptance Criteria

- [ ] `VoiceConfig` has all 22+ fields with correct defaults
- [ ] `VoiceProvider` enum is importable from `parrot.models.voice`
- [ ] `VoiceConfig(provider="google_live")` works (string coercion)
- [ ] `VoiceConfig(provider=VoiceProvider.NOVA)` works (enum direct)
- [ ] `from parrot.voice.models import VoiceConfig` still works (with deprecation warning)
- [ ] `from parrot.voice.models import VoiceProvider` still works (re-export)
- [ ] All tests pass: `pytest tests/models/test_voice_config.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/models/test_voice_config.py
import pytest
import warnings
from parrot.models.voice import VoiceConfig, VoiceProvider, AudioFormat


class TestVoiceConfigUnified:
    def test_all_fields_exist(self):
        config = VoiceConfig()
        assert hasattr(config, 'provider')
        assert hasattr(config, 'top_p')
        assert hasattr(config, 'parallel_tool_execution')
        assert hasattr(config, 'reconnect_on_limit')
        assert hasattr(config, 'max_reconnects')
        assert hasattr(config, 'vad_mode')

    def test_provider_string_coercion(self):
        config = VoiceConfig(provider="nova")
        assert config.provider == VoiceProvider.NOVA

    def test_provider_enum_direct(self):
        config = VoiceConfig(provider=VoiceProvider.GOOGLE_LIVE)
        assert config.provider == VoiceProvider.GOOGLE_LIVE

    def test_defaults(self):
        config = VoiceConfig()
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.top_p == 0.9
        assert config.max_reconnects == 3
        assert config.parallel_tool_execution is False
        assert config.reconnect_on_limit is True

    def test_backward_compat_import(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from parrot.voice.models import VoiceConfig as IntegVoiceConfig
            assert issubclass(IntegVoiceConfig, type(VoiceConfig()))
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/voice-agent-framework.spec.md` §3 Module 2
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm existing VoiceConfig fields
4. **Modify** `parrot/models/voice.py` — add VoiceProvider + unified VoiceConfig
5. **Modify** integrations `parrot/voice/models.py` — deprecation shim
6. **Write tests** in `tests/models/test_voice_config.py`
7. **Run tests** and verify all pass

---

## Completion Note

*(Agent fills this in when done)*
