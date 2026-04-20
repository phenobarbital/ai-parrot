# TASK-756: PostAuthAction Config Model & YAML Parsing

**Feature**: FEAT-108 — Jira OAuth2 3LO Authentication from Telegram WebApp
**Spec**: `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-108. It adds the `PostAuthAction` dataclass
and extends `TelegramAgentConfig` with a new `post_auth_actions` field so the
YAML configuration can declare secondary auth providers to chain after primary
BasicAuth. All subsequent tasks depend on this configuration model.

Implements Spec Module 1.

---

## Scope

- Define a `PostAuthAction` dataclass with fields `provider: str` and
  `required: bool = False`.
- Add a `post_auth_actions: List[PostAuthAction]` field to `TelegramAgentConfig`
  (default: empty list).
- Update `TelegramAgentConfig.from_dict()` to parse `post_auth_actions` from the
  YAML dict, converting each entry into a `PostAuthAction` instance.
- Update `TelegramBotsConfig.validate()` to warn if `post_auth_actions` references
  an unknown provider (soft warning, not error — providers are registered at runtime).
- Write unit tests verifying config parsing with and without `post_auth_actions`.

**NOT in scope**: The `PostAuthProvider` protocol or registry (TASK-757), any
runtime behavior, or actual provider implementations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/models.py` | MODIFY | Add `PostAuthAction` dataclass and `post_auth_actions` field to `TelegramAgentConfig` |
| `packages/ai-parrot/tests/unit/test_telegram_config_post_auth.py` | CREATE | Unit tests for config parsing |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.telegram.models import TelegramAgentConfig  # models.py:13
from parrot.integrations.telegram.models import TelegramBotsConfig   # models.py:134
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/models.py
@dataclass
class TelegramAgentConfig:                                          # line 13
    name: str                                                       # line 34
    chatbot_id: str                                                 # line 35
    auth_method: str = "basic"                                      # line 55
    # ... (many fields) ...
    voice_config: Optional["VoiceTranscriberConfig"] = None         # line 63
    # Add post_auth_actions AFTER voice_config

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'TelegramAgentConfig':  # line 95
        # Returns cls(...) with all fields parsed from dict
        # Last kwarg is voice_config=voice_config at line 130
        # Add post_auth_actions parsing here

@dataclass
class TelegramBotsConfig:                                           # line 134
    agents: Dict[str, TelegramAgentConfig]                          # line 148
    def validate(self) -> List[str]:                                # line 159
        # Returns list of error strings
```

### Does NOT Exist
- ~~`parrot.integrations.telegram.models.PostAuthAction`~~ — does not exist yet (this task creates it)
- ~~`TelegramAgentConfig.post_auth_actions`~~ — does not exist yet (this task creates it)

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing dataclass pattern in models.py
# PostAuthAction is a simple dataclass like TelegramAgentConfig itself
@dataclass
class PostAuthAction:
    provider: str
    required: bool = False
```

### Key Constraints
- Place `PostAuthAction` class BEFORE `TelegramAgentConfig` in models.py
- The `post_auth_actions` field must default to `field(default_factory=list)`
- `from_dict()` must handle both present and absent `post_auth_actions` in the YAML
- Backward compatible: existing configs without `post_auth_actions` must work unchanged

### References in Codebase
- `packages/ai-parrot/src/parrot/integrations/telegram/models.py` — target file
- `packages/ai-parrot/src/parrot/integrations/telegram/models.py:95-131` — `from_dict` to extend

### YAML Config Example
```yaml
agents:
  MyBot:
    chatbot_id: my_bot
    auth_method: basic
    post_auth_actions:
      - provider: jira
        required: true
      - provider: confluence
        required: false
```

---

## Acceptance Criteria

- [ ] `PostAuthAction` dataclass exists in `models.py` with `provider` and `required` fields
- [ ] `TelegramAgentConfig` has `post_auth_actions: List[PostAuthAction]` field
- [ ] `from_dict()` correctly parses `post_auth_actions` from YAML dict
- [ ] Config without `post_auth_actions` defaults to empty list (backward compat)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_telegram_config_post_auth.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/integrations/telegram/models.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_telegram_config_post_auth.py
import pytest
from parrot.integrations.telegram.models import (
    PostAuthAction,
    TelegramAgentConfig,
    TelegramBotsConfig,
)


class TestPostAuthAction:
    def test_defaults(self):
        action = PostAuthAction(provider="jira")
        assert action.provider == "jira"
        assert action.required is False

    def test_required_true(self):
        action = PostAuthAction(provider="jira", required=True)
        assert action.required is True


class TestTelegramAgentConfigPostAuth:
    def test_from_dict_with_post_auth_actions(self):
        data = {
            "chatbot_id": "test",
            "auth_method": "basic",
            "post_auth_actions": [
                {"provider": "jira", "required": True},
                {"provider": "confluence"},
            ],
        }
        config = TelegramAgentConfig.from_dict("test_bot", data)
        assert len(config.post_auth_actions) == 2
        assert config.post_auth_actions[0].provider == "jira"
        assert config.post_auth_actions[0].required is True
        assert config.post_auth_actions[1].provider == "confluence"
        assert config.post_auth_actions[1].required is False

    def test_from_dict_without_post_auth_actions(self):
        data = {"chatbot_id": "test"}
        config = TelegramAgentConfig.from_dict("test_bot", data)
        assert config.post_auth_actions == []

    def test_from_dict_empty_post_auth_actions(self):
        data = {"chatbot_id": "test", "post_auth_actions": []}
        config = TelegramAgentConfig.from_dict("test_bot", data)
        assert config.post_auth_actions == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm `TelegramAgentConfig` still has the listed fields and `from_dict` at the listed lines
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** the `PostAuthAction` dataclass and config extensions
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-756-post-auth-config-model.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-19
**Notes**:

- Added `PostAuthAction` dataclass immediately before `TelegramAgentConfig` in
  `packages/ai-parrot/src/parrot/integrations/telegram/models.py`.
- Added `post_auth_actions: List[PostAuthAction] = field(default_factory=list)`
  to `TelegramAgentConfig` after `voice_config`.
- Extended `TelegramAgentConfig.from_dict()` to parse a list of dicts (or
  pass-through existing `PostAuthAction` instances) into `PostAuthAction`
  instances.
- Added a soft warning in `TelegramBotsConfig.validate()` for unknown
  providers (known set currently contains only `"jira"`), emitted via
  `logger.warning` — does NOT add an error string, as the runtime registry
  of providers is populated later.
- Created `packages/ai-parrot/tests/unit/test_telegram_config_post_auth.py`
  with 12 tests covering dataclass defaults, YAML parsing with/without
  entries, mutable-default safety, and known-vs-unknown provider warning.
- All 12 tests pass. Backward compatible — existing configs without
  `post_auth_actions` continue to work.

**Deviations from spec**: none
