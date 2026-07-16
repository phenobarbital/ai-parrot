---
type: Wiki Overview
title: 'TASK-1591: FULL Mode Data Models'
id: doc:sdd-tasks-completed-task-1591-fullmode-data-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundational task for FEAT-248. The FULL mode session requires new Pydantic
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
---

# TASK-1591: FULL Mode Data Models

**Feature**: FEAT-248 — LiveAvatar FULL Mode speak_text Integration (Backend)
**Spec**: `sdd/specs/liveavatar-fullmode-speaktext.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundational task for FEAT-248. The FULL mode session requires new Pydantic
models that extend the existing LITE models: a config model with voice/language/
interactivity fields, a session handle with LiveKit room credentials, and a
per-tenant config override model. All subsequent tasks depend on these.

Implements spec §2 Data Models and §3 Module 1.

---

## Scope

- Add `FullModeConfig(LiveAvatarConfig)` with fields: `voice_id: Optional[str]`,
  `language: str = "en"`, `interactivity_type: str = "CONVERSATIONAL"`.
- Add `FullModeSessionHandle(AvatarSessionHandle)` with fields:
  `livekit_url: str = ""`, `livekit_client_token: str = ""`.
- Add `TenantAvatarConfig(BaseModel)` with fields: `tenant_id: str`,
  `avatar_id: Optional[str]`, `voice_id: Optional[str]`,
  `language: Optional[str]`, `interactivity_type: Optional[str]`,
  `api_key: Optional[str]`, `fullmode_enabled: bool = False`.
- Update `__init__.py` to re-export the three new models.
- Write unit tests for model validation, defaults, and inheritance.

**NOT in scope**: Client methods (TASK-1592), config resolver logic (TASK-1593),
handler endpoints (TASK-1594).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py` | MODIFY | Add `FullModeConfig`, `FullModeSessionHandle`, `TenantAvatarConfig` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` | MODIFY | Re-export new models |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_models.py` | MODIFY | Add tests for new models |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle,   # __init__.py:11
    LiveAvatarConfig,      # __init__.py:11
    LiveKitRoomTokens,     # __init__.py:11
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py
class LiveAvatarConfig(BaseModel):  # line 18
    api_key: str  # line 32
    avatar_id: str  # line 33
    base_url: str = "https://api.liveavatar.com"  # line 34
    is_sandbox: bool = True  # line 38
    max_session_duration: Optional[int] = None  # line 42
    quality: Optional[str] = None  # line 48
    encoding: Optional[str] = None  # line 52

class AvatarSessionHandle(BaseModel):  # line 86
    session_id: str  # line 101
    liveavatar_session_id: str  # line 104
    session_token: str  # line 107
    ws_url: str  # line 110
    tenant_id: Optional[str] = None  # line 117
    agent_name: str  # line 120
```

### Does NOT Exist
- ~~`FullModeConfig`~~ — does not exist yet; this task creates it
- ~~`FullModeSessionHandle`~~ — does not exist yet
- ~~`TenantAvatarConfig`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing Pydantic model pattern in models.py:
class FullModeConfig(LiveAvatarConfig):
    """FULL mode configuration (extends LITE config with voice/language)."""
    voice_id: Optional[str] = Field(
        default=None,
        description="Voice ID for the avatar persona.",
    )
    language: str = Field(
        default="en",
        description="BCP-47 language tag for the avatar.",
    )
    interactivity_type: str = Field(
        default="CONVERSATIONAL",
        description="CONVERSATIONAL or PUSH_TO_TALK.",
    )
```

### Key Constraints
- All fields must have `Field(...)` with descriptions (project convention)
- `FullModeSessionHandle.ws_url` is inherited from parent but unused in FULL mode —
  default it to `""` so it's always present but empty
- `TenantAvatarConfig.api_key` is a secret — add a note in the description that
  it must never be exposed to clients

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py` — extend these models
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` — add re-exports here

---

## Acceptance Criteria

- [ ] `FullModeConfig` inherits all `LiveAvatarConfig` fields and adds `voice_id`, `language`, `interactivity_type`
- [ ] `FullModeConfig(api_key="k", avatar_id="a")` creates a valid instance with defaults: `language="en"`, `interactivity_type="CONVERSATIONAL"`, `voice_id=None`
- [ ] `FullModeSessionHandle` inherits all `AvatarSessionHandle` fields and adds `livekit_url`, `livekit_client_token`
- [ ] `TenantAvatarConfig` validates correctly with all optional fields
- [ ] All three models importable from `parrot.integrations.liveavatar`
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_models.py -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_models.py
import pytest
from parrot.integrations.liveavatar.models import (
    FullModeConfig,
    FullModeSessionHandle,
    TenantAvatarConfig,
)


class TestFullModeConfig:
    def test_defaults(self):
        cfg = FullModeConfig(api_key="key", avatar_id="avatar")
        assert cfg.language == "en"
        assert cfg.interactivity_type == "CONVERSATIONAL"
        assert cfg.voice_id is None

    def test_inherits_lite_fields(self):
        cfg = FullModeConfig(api_key="key", avatar_id="avatar")
        assert cfg.base_url == "https://api.liveavatar.com"
        assert cfg.is_sandbox is True

    def test_custom_values(self):
        cfg = FullModeConfig(
            api_key="key", avatar_id="avatar",
            voice_id="v1", language="es",
            interactivity_type="PUSH_TO_TALK",
        )
        assert cfg.voice_id == "v1"
        assert cfg.language == "es"
        assert cfg.interactivity_type == "PUSH_TO_TALK"


class TestFullModeSessionHandle:
    def test_livekit_fields(self):
        handle = FullModeSessionHandle(
            session_id="s1", liveavatar_session_id="la1",
            session_token="tok", ws_url="", agent_name="agent",
            livekit_url="wss://test.livekit.cloud",
            livekit_client_token="eyJ...",
        )
        assert handle.livekit_url == "wss://test.livekit.cloud"
        assert handle.livekit_client_token == "eyJ..."

    def test_ws_url_empty_by_default(self):
        handle = FullModeSessionHandle(
            session_id="s1", liveavatar_session_id="la1",
            session_token="tok", ws_url="", agent_name="agent",
        )
        assert handle.livekit_url == ""
        assert handle.livekit_client_token == ""


class TestTenantAvatarConfig:
    def test_required_tenant_id(self):
        cfg = TenantAvatarConfig(tenant_id="acme")
        assert cfg.tenant_id == "acme"
        assert cfg.fullmode_enabled is False

    def test_all_optional_fields(self):
        cfg = TenantAvatarConfig(
            tenant_id="acme", avatar_id="av1",
            voice_id="v1", language="fr",
            fullmode_enabled=True,
        )
        assert cfg.avatar_id == "av1"
        assert cfg.fullmode_enabled is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/liveavatar-fullmode-speaktext.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm `LiveAvatarConfig` and `AvatarSessionHandle` still exist at their documented locations
4. **Implement** the three new Pydantic model classes at the end of `models.py`
5. **Update `__init__.py`** re-exports
6. **Run tests** to verify all acceptance criteria
7. **Update the per-spec index** status → `"in-progress"` / `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
