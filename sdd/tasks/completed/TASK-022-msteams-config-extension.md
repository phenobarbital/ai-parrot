# TASK-022: MSTeamsAgentConfig Voice Extension

**Feature**: MS Teams Voice Note Support
**Spec**: `sdd/specs/msteams-voice-support.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-016
**Assigned-to**: claude-session

---

## Context

This task extends `MSTeamsAgentConfig` to include voice transcription settings. This allows users to configure voice support when creating their MS Teams bot wrapper.

Reference: Spec Section 3 "Module 7: Config Extension"

---

## Scope

- Add `voice_config: Optional[VoiceTranscriberConfig]` field to `MSTeamsAgentConfig`
- Ensure backward compatibility (voice_config defaults to None/disabled)
- Update any config documentation/examples
- Write tests for config validation with voice settings

**NOT in scope**:
- VoiceTranscriberConfig implementation (TASK-016)
- Wrapper integration (TASK-021)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/msteams/models.py` | MODIFY | Add voice_config field |
| `tests/integrations/msteams/test_msteams_models.py` | MODIFY | Add voice config tests |

---

## Implementation Notes

### Pattern to Follow
```python
# In parrot/integrations/msteams/models.py

from typing import Optional
from pydantic import BaseModel, Field

# Import from the new voice module
from .voice.models import VoiceTranscriberConfig

class MSTeamsAgentConfig(BaseModel):
    """Configuration for MS Teams Agent Wrapper."""

    # ... existing fields ...
    name: str = Field(..., description="Bot display name")
    chatbot_id: str = Field(..., description="Unique chatbot identifier")
    app_id: str = Field(..., description="Azure Bot App ID")
    app_password: str = Field(..., description="Azure Bot App Password")
    # ... other existing fields ...

    # NEW: Voice transcription config
    voice_config: Optional[VoiceTranscriberConfig] = Field(
        default=None,
        description="Voice transcription configuration. None = disabled."
    )

    @property
    def voice_enabled(self) -> bool:
        """Check if voice transcription is enabled."""
        return self.voice_config is not None and self.voice_config.enabled
```

### Key Constraints
- Must be backward compatible — existing configs without voice_config should work
- Default to None (disabled) for voice_config
- Use Optional type hint
- Add helper property for checking if voice is enabled

### References in Codebase
- `parrot/integrations/msteams/models.py` — existing MSTeamsAgentConfig
- `parrot/integrations/slack/models.py` — similar config pattern

---

## Acceptance Criteria

- [x] `MSTeamsAgentConfig` has `voice_config: Optional[VoiceTranscriberConfig]` field
- [x] Default value is `None` (voice disabled)
- [x] `voice_enabled` property returns correct boolean
- [x] Existing configs without voice_config still work (backward compatible)
- [x] Config with voice settings validates correctly
- [x] All tests pass: `pytest tests/integrations/msteams/test_msteams_models.py -v` (10 tests)
- [x] Import works: `from parrot.integrations.msteams import MSTeamsAgentConfig`

---

## Test Specification

```python
# tests/integrations/msteams/test_msteams_models.py
import pytest
from parrot.integrations.msteams.models import MSTeamsAgentConfig
from parrot.integrations.msteams.voice.models import (
    VoiceTranscriberConfig,
    TranscriberBackend,
)


class TestMSTeamsAgentConfigVoice:
    def test_voice_config_optional(self):
        """voice_config is optional and defaults to None."""
        config = MSTeamsAgentConfig(
            name="TestBot",
            chatbot_id="test-bot",
            app_id="app-123",
            app_password="secret",
        )
        assert config.voice_config is None
        assert config.voice_enabled is False

    def test_voice_enabled_property(self):
        """voice_enabled returns True when voice is configured."""
        config = MSTeamsAgentConfig(
            name="TestBot",
            chatbot_id="test-bot",
            app_id="app-123",
            app_password="secret",
            voice_config=VoiceTranscriberConfig(enabled=True),
        )
        assert config.voice_enabled is True

    def test_voice_disabled_explicitly(self):
        """voice_enabled returns False when enabled=False."""
        config = MSTeamsAgentConfig(
            name="TestBot",
            chatbot_id="test-bot",
            app_id="app-123",
            app_password="secret",
            voice_config=VoiceTranscriberConfig(enabled=False),
        )
        assert config.voice_enabled is False

    def test_voice_config_full_settings(self):
        """Full voice config with all settings."""
        config = MSTeamsAgentConfig(
            name="TestBot",
            chatbot_id="test-bot",
            app_id="app-123",
            app_password="secret",
            voice_config=VoiceTranscriberConfig(
                enabled=True,
                backend=TranscriberBackend.OPENAI_WHISPER,
                openai_api_key="sk-test",
                model_size="medium",
                language="es",
                show_transcription=True,
                max_audio_duration_seconds=120,
            ),
        )
        assert config.voice_config.backend == TranscriberBackend.OPENAI_WHISPER
        assert config.voice_config.language == "es"

    def test_backward_compatibility(self):
        """Existing code without voice_config still works."""
        # Simulate loading old config
        config_dict = {
            "name": "OldBot",
            "chatbot_id": "old-bot",
            "app_id": "app-old",
            "app_password": "secret",
            # No voice_config
        }
        config = MSTeamsAgentConfig(**config_dict)
        assert config.voice_config is None
        assert config.voice_enabled is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/msteams-voice-support.spec.md`
2. **Check dependencies** — TASK-016 must be in `tasks/completed/`
3. **Read existing models** at `parrot/integrations/msteams/models.py`
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Verify** backward compatibility with existing tests
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-022-msteams-config-extension.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**:
- Added `voice_config: Optional[VoiceTranscriberConfig]` field to MSTeamsAgentConfig dataclass
- Added `voice_enabled` property that checks both voice_config presence and enabled flag
- Updated `from_dict()` classmethod to parse voice_config from dict or accept VoiceTranscriberConfig object
- Added export to `parrot/integrations/msteams/__init__.py`
- Created comprehensive test suite with 10 tests covering all acceptance criteria
- All tests pass, no linting errors

**Deviations from spec**:
- Used TYPE_CHECKING import to avoid circular imports (spec showed direct import)
- MSTeamsAgentConfig is a dataclass (not Pydantic BaseModel as shown in spec example) - kept consistent with existing implementation
