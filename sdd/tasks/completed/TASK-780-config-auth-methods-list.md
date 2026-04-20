# TASK-780: TelegramAgentConfig — auth_methods List Field

**Feature**: FEAT-109 — Telegram Multi-Auth Negotiation
**Spec**: `sdd/specs/FEAT-109-telegram-multi-auth-negotiation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

To express "offer basic AND azure on the chooser", admins need a
list form in YAML:
```yaml
auth_methods: [basic, azure]
```
Today the config only exposes `auth_method: str = "basic"`
(`models.py:81`). This task adds the list field, preserves the
singleton for back-compat, and centralizes the env-var derivation
that currently runs inside `auth_method == "azure"` / `"oauth2"`
branches so it fires for every listed method.

Implements **Module 4** of the spec.

---

## Scope

- Add to `TelegramAgentConfig` (`models.py`):
  ```python
  auth_methods: List[str] = field(default_factory=list)
  ```
- Extend `__post_init__`:
  1. If `auth_methods` is empty AND `auth_method` is set, normalize
     → `auth_methods = [auth_method]`.
  2. If `auth_methods` is empty AND `auth_method` is falsy, leave
     it empty (means "no auth configured").
  3. Validate every entry against `{"basic", "azure", "oauth2"}`.
     Raise `ValueError` (or append to the validator output — decide
     per consistency with existing behavior) on unknown.
  4. Run the existing env-var derivation for every method present
     in the normalized list (not just when `auth_method ==` matches).
     That means:
     - `"azure" in auth_methods` → resolve `azure_auth_url`
       (current logic at `models.py:122-135`).
     - `"oauth2" in auth_methods` → resolve `oauth2_client_id` /
       `oauth2_client_secret` (current logic at `models.py:110-120`).
- Extend `from_dict` (`models.py:143`) to accept `auth_methods`
  either as a list OR a string (string → list-of-one).
- Preserve back-compat: deployments that only set `auth_method:
  "basic"` / `"azure"` / `"oauth2"` continue to work identically.

**NOT in scope**:
- Wrapper strategy selection — TASK-781.
- `TelegramBotsConfig.validate()` rules (hard-error on
  `login_multi.html` mismatch) — TASK-784.
- YAML doc comments in `env/integrations_bots.yaml` — TASK-784.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/models.py` | MODIFY | Add `auth_methods` field; normalize in `__post_init__`; parse in `from_dict` |
| `packages/ai-parrot/tests/integrations/telegram/test_config_auth_methods.py` | CREATE | Unit tests for normalization + env-var resolution |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/integrations/telegram/models.py — present:
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from navconfig import config
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/integrations/telegram/models.py
@dataclass
class TelegramAgentConfig:
    auth_url: Optional[str]                                      # line 75
    login_page_url: Optional[str]                                # line 76
    enable_login: bool = True                                    # line 77
    auth_method: str = "basic"                                   # line 81
    oauth2_client_id: Optional[str] = None                       # line 84
    oauth2_client_secret: Optional[str] = None                   # line 85
    azure_auth_url: Optional[str] = None                         # line 89
    post_auth_actions: List[PostAuthAction] = field(...)         # line 93

    def __post_init__(self):                                     # line 95
        # Existing branches: auth_method == "oauth2" (lines 111-120),
        # auth_method == "azure" (lines 122-135). MUST be generalized.

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "TelegramAgentConfig":  # line 143
        # Existing construction at lines 168-195 — add auth_methods.
```

### Does NOT Exist

- ~~`TelegramAgentConfig.auth_methods`~~ — new in this task.
- ~~`auth_method: str = "basic"` being removed~~ — kept for compat.
- ~~`TelegramBotsConfig.validate()` enforcing `login_multi.html`~~ —
  TASK-784.

---

## Implementation Notes

### Normalization algorithm

```python
def __post_init__(self):
    # ... bot_token, auth_url resolution stays as-is ...

    # Normalize auth_methods: prefer explicit list; fall back to
    # the legacy single-value field; never silently dedupe.
    if not self.auth_methods:
        if self.auth_method:
            self.auth_methods = [self.auth_method]
        # else: no auth configured — leave empty
    else:
        # Allow YAML string form via from_dict; here we assume list.
        pass

    # Validate every entry.
    allowed = {"basic", "azure", "oauth2"}
    unknown = [m for m in self.auth_methods if m not in allowed]
    if unknown:
        raise ValueError(
            f"Agent '{self.name}': unknown auth_methods entries: "
            f"{unknown}. Allowed: {sorted(allowed)}"
        )

    # Resolve env vars for every active method.
    if "oauth2" in self.auth_methods:
        name_upper = self.name.upper()
        if not self.oauth2_client_id:
            self.oauth2_client_id = config.get(f"{name_upper}_OAUTH2_CLIENT_ID")
        if not self.oauth2_client_secret:
            self.oauth2_client_secret = config.get(f"{name_upper}_OAUTH2_CLIENT_SECRET")

    if "azure" in self.auth_methods:
        name_upper = self.name.upper()
        if not self.azure_auth_url:
            self.azure_auth_url = config.get(f"{name_upper}_AZURE_AUTH_URL")
        if not self.azure_auth_url and self.auth_url:
            base = self.auth_url.rstrip("/")
            if base.endswith("/login"):
                base = base.rsplit("/", 1)[0]
            self.azure_auth_url = f"{base}/azure/"
```

### from_dict — accept string or list

```python
raw = data.get("auth_methods")
if isinstance(raw, str):
    auth_methods = [raw]
elif isinstance(raw, list):
    auth_methods = list(raw)
else:
    auth_methods = []
```

---

## Acceptance Criteria

- [ ] `TelegramAgentConfig` has `auth_methods: List[str]` field.
- [ ] `auth_method: basic` YAML (no `auth_methods`) normalizes to
      `auth_methods == ["basic"]`.
- [ ] `auth_methods: [basic, azure]` YAML stays as-is.
- [ ] `auth_methods: azure` YAML (string form) normalizes to
      `["azure"]`.
- [ ] Env-var derivation for Azure and OAuth2 runs when the method
      is present, not only when `auth_method` matches.
- [ ] Unknown method → clear `ValueError`.
- [ ] Existing tests for Azure derivation still pass.
- [ ] New tests cover the normalization matrix.

---

## Test Specification (sketch)

```python
# tests/integrations/telegram/test_config_auth_methods.py
import pytest
from parrot.integrations.telegram.models import TelegramAgentConfig


def test_legacy_single_method_normalizes_to_list():
    cfg = TelegramAgentConfig(name="bot", chatbot_id="b", bot_token="t",
                              auth_method="azure",
                              auth_url="https://h/api/v1/login")
    assert cfg.auth_methods == ["azure"]


def test_explicit_list_preserved():
    cfg = TelegramAgentConfig(name="bot", chatbot_id="b", bot_token="t",
                              auth_methods=["basic", "azure"],
                              auth_url="https://h/api/v1/login")
    assert cfg.auth_methods == ["basic", "azure"]


def test_unknown_method_raises():
    with pytest.raises(ValueError, match="unknown"):
        TelegramAgentConfig(name="bot", chatbot_id="b", bot_token="t",
                            auth_methods=["linkedin"],
                            auth_url="https://h/api/v1/login")


def test_azure_env_derivation_fires_with_list():
    cfg = TelegramAgentConfig(name="bot", chatbot_id="b", bot_token="t",
                              auth_methods=["basic", "azure"],
                              auth_url="https://h/api/v1/login")
    # azure_auth_url derived even though auth_method (singleton) is "basic"
    assert cfg.azure_auth_url == "https://h/api/v1/azure/"


def test_from_dict_accepts_list():
    cfg = TelegramAgentConfig.from_dict(
        "bot",
        {"chatbot_id": "b", "bot_token": "t",
         "auth_methods": ["basic", "azure"],
         "auth_url": "https://h/api/v1/login"},
    )
    assert cfg.auth_methods == ["basic", "azure"]


def test_from_dict_accepts_string():
    cfg = TelegramAgentConfig.from_dict(
        "bot",
        {"chatbot_id": "b", "bot_token": "t",
         "auth_methods": "azure",
         "auth_url": "https://h/api/v1/login"},
    )
    assert cfg.auth_methods == ["azure"]
```

---

## Agent Instructions

1. Read the spec + `models.py` lines 75-195.
2. Generalize env-var derivation as shown above.
3. Keep the existing `auth_method` branches working (back-compat).
4. Implement tests; ensure all existing `test_*config*` tests pass.

---

## Completion Note

*(Agent fills this in when done)*
