# TASK-784: Validation Rules + YAML Docs for Multi-Auth

**Feature**: FEAT-109 — Telegram Multi-Auth Negotiation
**Spec**: `sdd/specs/FEAT-109-telegram-multi-auth-negotiation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-780, TASK-783
**Assigned-to**: unassigned

---

## Context

`TelegramBotsConfig.validate()` at `models.py:223` today checks
OAuth2 and Azure per-method requirements based on the singleton
`auth_method`. After TASK-780 introduces `auth_methods: List[str]`,
validation needs to run per entry. It also needs to enforce that
multi-method configs point at `login_multi.html`, otherwise admins
silently get the BasicAuth-single-method HTML with a broken
`azure_auth_url` query param.

Also: update the YAML reference at
`env/integrations_bots.yaml` to show the new form.

Implements **Module 8** of the spec.

---

## Scope

- Extend `TelegramBotsConfig.validate()` (`models.py:223`):
  - For each `agent_config`, iterate over `auth_methods` and apply:
    - `"azure"` present → require `azure_auth_url` (or successful
      derivation from `auth_url`). Same rule as today's
      `auth_method == "azure"` branch, generalized.
    - `"oauth2"` present → require `oauth2_client_id` AND
      `oauth2_client_secret`. Same rule as today's
      `auth_method == "oauth2"` branch, generalized.
  - If `len(auth_methods) >= 2`:
    - `login_page_url` MUST be set.
    - `login_page_url` must reference `login_multi.html`
      (case-insensitive substring match). Otherwise error:
      `Agent '<name>': auth_methods has {n} methods but
      login_page_url does not reference 'login_multi.html'. Multi-
      auth bots must use the shared chooser page.`
- Update `env/integrations_bots.yaml`:
  - Update the existing `JiraTroc` block's comments to show the
    multi-auth form as an opt-in:
    ```yaml
    # Multi-auth example (offers basic + azure on the same page):
    # auth_methods: [basic, azure]
    # login_page_url: https://<host>/static/telegram/login_multi.html
    ```
  - DO NOT change the current live config — keep the user's
    working `auth_method: basic` untouched.

**NOT in scope**:
- Adding runtime validation for `supports_post_auth_chain`
  compatibility with `post_auth_actions` — future work. Today the
  composite's AND semantics handles it transparently.
- Changing `auth_method` field itself — TASK-780 kept it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/models.py` | MODIFY | Extend `validate()` with per-method rules + multi-auth login page check |
| `env/integrations_bots.yaml` | MODIFY | Add commented multi-auth example alongside existing `JiraTroc` |
| `packages/ai-parrot/tests/integrations/telegram/test_config_validation_multi_auth.py` | CREATE | Tests for every new validation branch |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# models.py imports already in place: dataclass, field, List, Optional,
# navconfig.config, logging (logger variable).
```

### Existing Signatures to Use

```python
# models.py
@dataclass
class TelegramBotsConfig:
    agents: Dict[str, TelegramAgentConfig]
    def validate(self) -> List[str]:                    # line 223
        # Today iterates agents; branches on auth_method == "oauth2"
        # (line 239) and auth_method == "azure" (line 252).
```

### Does NOT Exist

- ~~A hard-error on `login_multi.html` mismatch~~ — introduced here.
- ~~Per-entry validation of `auth_methods`~~ — introduced here.

---

## Implementation Notes

### Generalization

Take the existing `auth_method ==` branches and migrate them to
iterate over `auth_methods`:

```python
def validate(self) -> List[str]:
    errors: List[str] = []
    for name, cfg in self.agents.items():
        if not cfg.chatbot_id:
            errors.append(f"Agent '{name}': missing 'chatbot_id'")
        if not cfg.bot_token:
            errors.append(f"Agent '{name}': missing bot_token (…)")
        for method in cfg.auth_methods:
            if method == "oauth2":
                if not cfg.oauth2_client_id:
                    errors.append(f"Agent '{name}': auth_method 'oauth2' requires oauth2_client_id")
                if not cfg.oauth2_client_secret:
                    errors.append(f"Agent '{name}': auth_method 'oauth2' requires oauth2_client_secret")
            elif method == "azure":
                if not cfg.azure_auth_url and not cfg.auth_url:
                    errors.append(
                        f"Agent '{name}': auth_method 'azure' requires "
                        f"azure_auth_url or a derivable auth_url"
                    )
        if len(cfg.auth_methods) >= 2:
            if not cfg.login_page_url:
                errors.append(
                    f"Agent '{name}': auth_methods has {len(cfg.auth_methods)} "
                    f"entries but login_page_url is unset"
                )
            elif "login_multi.html" not in cfg.login_page_url.lower():
                errors.append(
                    f"Agent '{name}': auth_methods has {len(cfg.auth_methods)} "
                    f"entries but login_page_url does not reference "
                    f"'login_multi.html'. Multi-auth bots must use the shared "
                    f"chooser page."
                )
        # Unknown post_auth providers (preserve existing warning)
        for action in cfg.post_auth_actions:
            if action.provider not in _KNOWN_POST_AUTH_PROVIDERS:
                logger.warning("…")
    return errors
```

### YAML example

Add ABOVE or BELOW the existing `JiraTroc:` block a commented
example (mirror the header comment style already in the file):

```yaml
  # Multi-auth example — offers BOTH basic and Azure on the same chooser page.
  # JiraTrocMulti:
  #   chatbot_id: jira_specialist
  #   kind: telegram
  #   bot_token: ${JIRATROC_TELEGRAM_TOKEN}
  #   auth_methods: [basic, azure]
  #   auth_url: https://<host>/api/v1/login
  #   azure_auth_url: https://<host>/api/v1/auth/azure/
  #   login_page_url: https://<host>/static/telegram/login_multi.html
  #   enable_login: true
  #   force_authentication: true
  #   post_auth_actions:
  #     - provider: jira
  #       required: true
```

---

## Acceptance Criteria

- [ ] `validate()` catches `auth_methods: [basic, azure]` with
      missing `azure_auth_url` (no `auth_url` fallback).
- [ ] `validate()` catches `auth_methods: [basic, oauth2]` with
      missing `oauth2_client_id` / `oauth2_client_secret`.
- [ ] `validate()` catches multi-auth configs whose
      `login_page_url` doesn't reference `login_multi.html`.
- [ ] Legacy single-method YAMLs still pass validation.
- [ ] `env/integrations_bots.yaml` has the commented multi-auth
      example; the live config is untouched.
- [ ] New tests cover every branch.

---

## Test Specification (sketch)

```python
# tests/integrations/telegram/test_config_validation_multi_auth.py
from parrot.integrations.telegram.models import (
    TelegramAgentConfig, TelegramBotsConfig,
)


def _cfg(**overrides):
    base = dict(
        name="bot", chatbot_id="b", bot_token="t",
        auth_url="https://h/api/v1/login",
        login_page_url="https://h/static/telegram/login_multi.html",
        auth_methods=["basic", "azure"],
        azure_auth_url="https://h/api/v1/auth/azure/",
    )
    base.update(overrides)
    return TelegramAgentConfig(**base)


def test_multi_auth_valid_passes():
    bots = TelegramBotsConfig(agents={"b": _cfg()})
    assert bots.validate() == []


def test_multi_auth_missing_login_multi_html_errors():
    cfg = _cfg(login_page_url="https://h/static/telegram/login.html")
    bots = TelegramBotsConfig(agents={"b": cfg})
    errors = bots.validate()
    assert any("login_multi.html" in e for e in errors)


def test_multi_auth_missing_azure_url_errors():
    # Construct a config that somehow lacks azure_auth_url
    # (requires bypassing __post_init__ derivation).
    ...


def test_legacy_single_method_still_valid():
    cfg = TelegramAgentConfig(
        name="bot", chatbot_id="b", bot_token="t",
        auth_method="basic",
        auth_url="https://h/api/v1/login",
        login_page_url="https://h/static/telegram/login.html",
    )
    bots = TelegramBotsConfig(agents={"b": cfg})
    assert bots.validate() == []


def test_oauth2_in_multi_missing_creds_errors():
    cfg = _cfg(
        auth_methods=["basic", "oauth2"],
        oauth2_client_id=None, oauth2_client_secret=None,
    )
    bots = TelegramBotsConfig(agents={"b": cfg})
    errors = bots.validate()
    assert any("oauth2_client_id" in e for e in errors)
```

---

## Agent Instructions

1. Read `models.py:223-271` before editing.
2. Preserve the existing post_auth warning logic.
3. Commit the YAML example as part of this task (same commit).

---

## Completion Note

*(Agent fills this in when done)*
