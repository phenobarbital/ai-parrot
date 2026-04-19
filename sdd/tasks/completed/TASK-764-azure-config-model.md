# TASK-764: Add azure_auth_url to TelegramAgentConfig

**Feature**: FEAT-109 — Telegram Integration Azure SSO via Navigator
**Spec**: `sdd/specs/telegram-integration-basicauth.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements Module 1 from the spec. Before any strategy or HTML can work,
> the configuration model must know about the `azure_auth_url` field and
> recognize `auth_method: "azure"` as a valid value.

---

## Scope

- Add `azure_auth_url: Optional[str] = None` field to `TelegramAgentConfig` dataclass
- Update `__post_init__()` to resolve `azure_auth_url` from env var `{NAME}_AZURE_AUTH_URL`
- When `auth_method == "azure"` and `azure_auth_url` is not set, derive it from `auth_url`:
  - Strip trailing path component if it looks like an endpoint (e.g., `/login`), then append `/azure/`
  - Example: `auth_url="https://nav.example.com/api/v1/auth/login"` → `azure_auth_url="https://nav.example.com/api/v1/auth/azure/"`
- Update `from_dict()` to read `azure_auth_url` from YAML dict
- Update `validate()` in `TelegramBotsConfig` to check that `auth_method: "azure"` has either `azure_auth_url` or `auth_url` set
- Write unit tests for all config changes

**NOT in scope**: AzureAuthStrategy implementation, wrapper changes, HTML page

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/models.py` | MODIFY | Add `azure_auth_url` field, update `__post_init__`, `from_dict`, `validate` |
| `packages/ai-parrot/tests/integrations/telegram/test_azure_config.py` | CREATE | Unit tests for config model changes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from dataclasses import dataclass, field  # verified: models.py:4
from typing import TYPE_CHECKING, Dict, List, Optional, Any  # verified: models.py:5
from navconfig import config  # verified: models.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/models.py

@dataclass
class TelegramAgentConfig:  # line 12
    name: str                           # line 34
    chatbot_id: str                     # line 35
    bot_token: Optional[str] = None     # line 36
    auth_url: Optional[str] = None      # line 49
    login_page_url: Optional[str] = None  # line 50
    enable_login: bool = True           # line 51
    force_authentication: bool = False  # line 53
    auth_method: str = "basic"          # line 55
    oauth2_provider: str = "google"     # line 57
    oauth2_client_id: Optional[str] = None  # line 58
    oauth2_client_secret: Optional[str] = None  # line 59
    oauth2_scopes: Optional[List[str]] = None  # line 60
    oauth2_redirect_uri: Optional[str] = None  # line 61
    voice_config: Optional["VoiceTranscriberConfig"] = None  # line 63

    def __post_init__(self):  # line 65
        # Resolves bot_token from env, auth_url from env, oauth2 creds from env
        ...

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'TelegramAgentConfig':  # line 94
        # Returns cls(...) with all fields from dict
        ...

@dataclass
class TelegramBotsConfig:  # line 134
    agents: Dict[str, TelegramAgentConfig] = field(default_factory=dict)  # line 148

    def validate(self) -> List[str]:  # line 159
        # Returns list of error strings
        # Already checks auth_method=="oauth2" requires client_id/secret (lines 175-187)
        ...
```

### Does NOT Exist
- ~~`TelegramAgentConfig.azure_auth_url`~~ — does not exist yet; this task creates it
- ~~`TelegramAgentConfig.azure_tenant_id`~~ — not needed; Navigator manages Azure config
- ~~`TelegramAgentConfig.azure_client_id`~~ — not needed; Navigator manages Azure config

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing OAuth2 env var resolution pattern in __post_init__ (lines 77-87):
if self.auth_method == "oauth2":
    name_upper = self.name.upper()
    if not self.oauth2_client_id:
        self.oauth2_client_id = config.get(f"{name_upper}_OAUTH2_CLIENT_ID")

# Apply the same pattern for azure_auth_url:
if self.auth_method == "azure":
    name_upper = self.name.upper()
    if not self.azure_auth_url:
        self.azure_auth_url = config.get(f"{name_upper}_AZURE_AUTH_URL")
    # Derive from auth_url if still not set
    if not self.azure_auth_url and self.auth_url:
        base = self.auth_url.rstrip("/")
        if base.endswith(("/login", "/auth")):
            base = base.rsplit("/", 1)[0]
        self.azure_auth_url = f"{base}/azure/"
```

### Key Constraints
- New field must go AFTER `oauth2_redirect_uri` and BEFORE `voice_config` in the dataclass
- `from_dict()` must pass `azure_auth_url=data.get('azure_auth_url')` to constructor
- `validate()` must add error if `auth_method=="azure"` and neither `azure_auth_url` nor `auth_url` is set
- All existing tests must continue to pass

### References in Codebase
- `packages/ai-parrot/src/parrot/integrations/telegram/models.py` — the file to modify
- `packages/ai-parrot/tests/integrations/telegram/test_config_oauth2.py` — pattern for config tests

---

## Acceptance Criteria

- [ ] `TelegramAgentConfig` has `azure_auth_url: Optional[str] = None` field
- [ ] `__post_init__` resolves `azure_auth_url` from `{NAME}_AZURE_AUTH_URL` env var
- [ ] `__post_init__` derives `azure_auth_url` from `auth_url` when not explicitly set
- [ ] `from_dict()` reads `azure_auth_url` from YAML dict
- [ ] `validate()` reports error when `auth_method="azure"` has no URL source
- [ ] Existing configs without `azure_auth_url` continue to work (backward compat)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/integrations/telegram/test_azure_config.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/integrations/telegram/test_azure_config.py
import pytest
from parrot.integrations.telegram.models import TelegramAgentConfig, TelegramBotsConfig


class TestAzureConfigField:
    def test_default_azure_auth_url_is_none(self):
        """Default azure_auth_url is None."""
        cfg = TelegramAgentConfig(name="Test", chatbot_id="test", bot_token="t:k")
        assert cfg.azure_auth_url is None

    def test_explicit_azure_auth_url(self):
        """azure_auth_url can be set explicitly."""
        cfg = TelegramAgentConfig(
            name="Test", chatbot_id="test", bot_token="t:k",
            auth_method="azure",
            azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        )
        assert cfg.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"

    def test_azure_url_derived_from_auth_url(self):
        """azure_auth_url derived from auth_url when not set."""
        cfg = TelegramAgentConfig(
            name="Test", chatbot_id="test", bot_token="t:k",
            auth_method="azure",
            auth_url="https://nav.example.com/api/v1/auth/login",
        )
        assert cfg.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"

    def test_azure_url_derived_without_login_suffix(self):
        """azure_auth_url derived from auth_url without /login."""
        cfg = TelegramAgentConfig(
            name="Test", chatbot_id="test", bot_token="t:k",
            auth_method="azure",
            auth_url="https://nav.example.com/api/v1/auth",
        )
        assert cfg.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"


class TestAzureFromDict:
    def test_from_dict_with_azure(self):
        """from_dict reads azure_auth_url."""
        cfg = TelegramAgentConfig.from_dict("Bot", {
            "chatbot_id": "bot",
            "bot_token": "t:k",
            "auth_method": "azure",
            "azure_auth_url": "https://nav.example.com/api/v1/auth/azure/",
        })
        assert cfg.auth_method == "azure"
        assert cfg.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"


class TestAzureValidation:
    def test_validate_azure_no_urls(self):
        """Validation error when azure has no URL source."""
        bots = TelegramBotsConfig(agents={
            "Bad": TelegramAgentConfig(
                name="Bad", chatbot_id="bad", bot_token="t:k",
                auth_method="azure",
            ),
        })
        errors = bots.validate()
        assert any("azure" in e.lower() for e in errors)

    def test_validate_azure_with_url(self):
        """No validation error when azure_auth_url is set."""
        bots = TelegramBotsConfig(agents={
            "Good": TelegramAgentConfig(
                name="Good", chatbot_id="good", bot_token="t:k",
                auth_method="azure",
                azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
            ),
        })
        errors = bots.validate()
        assert not any("azure" in e.lower() for e in errors)


class TestBackwardCompat:
    def test_basic_auth_config_unchanged(self):
        """BasicAuth config works without azure_auth_url."""
        cfg = TelegramAgentConfig(
            name="Legacy", chatbot_id="legacy", bot_token="t:k",
            auth_url="https://nav.example.com/api/v1/auth/login",
            login_page_url="https://static.example.com/login.html",
        )
        assert cfg.auth_method == "basic"
        assert cfg.azure_auth_url is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-integration-basicauth.spec.md` for full context
2. **Check dependencies** — none; this is the first task
3. **Verify the Codebase Contract** — `read` models.py to confirm field order and signatures
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** the changes to models.py
6. **Write tests** in test_azure_config.py
7. **Run**: `pytest packages/ai-parrot/tests/integrations/telegram/test_azure_config.py -v`
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-04-19
**Notes**: Added azure_auth_url field to TelegramAgentConfig dataclass with env var resolution and derivation from auth_url. Updated from_dict() and validate(). 15 unit tests pass.

**Deviations from spec**: Derivation logic strips only /login suffix (not /auth) to preserve /auth as a path prefix — test case confirmed this is correct behavior.
