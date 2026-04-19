# TASK-763: Wrapper Orchestration (handle_web_app_data Extension)

**Feature**: FEAT-108 — Jira OAuth2 3LO Authentication from Telegram WebApp
**Spec**: `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-756, TASK-757, TASK-758, TASK-759, TASK-760, TASK-761, TASK-762
**Assigned-to**: unassigned

---

## Context

This is the final integration task that ties all components together. It extends
the `TelegramAgentWrapper` to:
1. Initialize the `PostAuthRegistry` with configured providers at startup.
2. Modify `BasicAuthStrategy.build_login_keyboard()` to include `next_auth_url`
   in the login page URL when `post_auth_actions` are configured.
3. Extend `handle_web_app_data()` to detect combined auth payloads and dispatch
   secondary auth processing.
4. Handle success/failure scenarios including rollback for required secondary auth.

Implements Spec Module 8 — the orchestration layer.

---

## Scope

- **Extend `TelegramAgentWrapper.__init__()`**:
  - Initialize `PostAuthRegistry` from `config.post_auth_actions`.
  - Register `JiraPostAuthProvider` if "jira" is in `post_auth_actions`.
  - Pass `JiraOAuthManager` (from `config.jira_oauth_manager`), `IdentityMappingService`,
    and `VaultTokenSync` to the provider.

- **Extend `BasicAuthStrategy.build_login_keyboard()`** (or override in wrapper):
  - When `post_auth_actions` are configured, build the Jira authorization URL
    via the provider's `build_auth_url()` and append it as `next_auth_url` query
    param to the login page URL.
  - Also append `next_auth_required` based on the action's `required` flag.

- **Extend `handle_web_app_data()`**:
  - Detect combined payload: check for `jira` key (or other provider keys).
  - If combined payload:
    1. Process BasicAuth first via existing `handle_callback()`.
    2. If BasicAuth succeeds, dispatch to `PostAuthProvider.handle_result()`.
    3. On secondary success: send combined success message.
    4. On secondary failure + `required=true`: rollback via `session.clear_auth()`,
       send failure message.
    5. On secondary failure + `required=false`: send partial success message
       ("Logged in, but Jira not connected").
  - If standard BasicAuth payload (no provider keys): process as before (backward compat).

- **Wire up combined callback route** in the app startup.

- **Write integration-level unit tests** covering all scenarios.

**NOT in scope**: Modifying the login page JS (TASK-762), implementing new providers
beyond Jira.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Extend `__init__`, `handle_web_app_data`, add post-auth dispatch |
| `packages/ai-parrot/src/parrot/integrations/telegram/auth.py` | MODIFY | Extend `BasicAuthStrategy.build_login_keyboard` for `next_auth_url` |
| `packages/ai-parrot/src/parrot/autonomous/orchestrator.py` | MODIFY | Wire combined callback route |
| `packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py` | CREATE | Integration-level unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing imports in wrapper.py context:
from parrot.integrations.telegram.auth import BasicAuthStrategy, TelegramUserSession  # auth.py
from parrot.integrations.telegram.models import TelegramAgentConfig  # models.py:13
from parrot.auth.jira_oauth import JiraOAuthManager  # jira_oauth.py:85

# New imports (from prior tasks):
from parrot.integrations.telegram.models import PostAuthAction  # TASK-756
from parrot.integrations.telegram.post_auth import PostAuthProvider, PostAuthRegistry  # TASK-757
from parrot.integrations.telegram.post_auth_jira import JiraPostAuthProvider  # TASK-758
from parrot.integrations.telegram.combined_callback import setup_combined_auth_routes  # TASK-759
from parrot.services.identity_mapping import IdentityMappingService  # TASK-760
from parrot.services.vault_token_sync import VaultTokenSync  # TASK-761
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:                                         # line 50
    def __init__(self, agent, bot, config: TelegramAgentConfig,
                 agent_commands=None): ...                           # line 68
    _auth_strategy: Optional[AbstractAuthStrategy]                  # line 88-94
    _user_sessions: Dict[int, TelegramUserSession]                  # line 85
    config: TelegramAgentConfig                                     # line 77
    bot: Bot                                                        # line 76
    async def handle_web_app_data(self, message: Message) -> None:  # line 907
        # line 919: data = json.loads(message.web_app_data.data)
        # line 924: session = self._get_user_session(message)
        # line 926: success = await self._auth_strategy.handle_callback(data, session)
        # line 928-937: send success/failure message
    def _register_jira_commands(self) -> None: ...                  # line 282
        # line 290: oauth_manager = getattr(self.config, "jira_oauth_manager", None)

# packages/ai-parrot/src/parrot/integrations/telegram/auth.py
class BasicAuthStrategy(AbstractAuthStrategy):                      # line 237
    login_page_url: Optional[str]                                   # line 256
    async def build_login_keyboard(self, config: Any, state: str) -> ReplyKeyboardMarkup:  # line 260
        # line 278: page_url = self.login_page_url or getattr(config, "login_page_url", None)
        # line 284: full_url = f"{page_url}?{urlencode({'auth_url': self.auth_url})}"
        # line 286-295: return ReplyKeyboardMarkup(...)

class TelegramUserSession:                                          # line 36
    def set_authenticated(...): ...                                 # line 84
    def clear_auth(self) -> None: ...                               # line 102

# packages/ai-parrot/src/parrot/autonomous/orchestrator.py
# line 272: if 'jira_oauth_manager' in app:
# line 273:     from ..auth.routes import setup_jira_oauth_routes
# line 274:     setup_jira_oauth_routes(app)
```

### Does NOT Exist
- ~~`TelegramAgentWrapper._post_auth_registry`~~ — does not exist yet (this task creates it)
- ~~`TelegramAgentWrapper._dispatch_post_auth()`~~ — does not exist yet
- ~~`BasicAuthStrategy.next_auth_url`~~ — attribute does not exist
- ~~`handle_web_app_data` detecting `jira` key~~ — no such logic exists yet

---

## Implementation Notes

### Extending `handle_web_app_data()`
```python
async def handle_web_app_data(self, message: Message) -> None:
    # ... existing code until line 919 ...
    data = json.loads(message.web_app_data.data)
    session = self._get_user_session(message)

    # NEW: Detect combined payload
    has_secondary = any(
        action.provider in data
        for action in self.config.post_auth_actions
    )

    if has_secondary:
        # Combined flow: BasicAuth data might be in data["basic_auth"]
        # or reconstructed from the session (if pre-stashed)
        basic_data = data.get("basic_auth", data)  # fallback for compat
        success = await self._auth_strategy.handle_callback(basic_data, session)
        if success:
            for action in self.config.post_auth_actions:
                if action.provider in data:
                    provider = self._post_auth_registry.get(action.provider)
                    if provider:
                        sec_success = await provider.handle_result(
                            data[action.provider], session, basic_data
                        )
                        if not sec_success and action.required:
                            session.clear_auth()
                            await message.answer("❌ Login requires Jira authorization. Please try again.")
                            return
                        elif not sec_success:
                            await message.answer(
                                f"✅ Logged in as *{session.display_name}*.\n"
                                "⚠️ Jira not connected — use /connect_jira anytime.",
                                parse_mode="Markdown",
                            )
                            return
            # All secondary auths succeeded
            await message.answer(
                f"✅ Authenticated as *{session.display_name}*.\n"
                "Jira connected successfully.",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await message.answer("❌ Login failed. Please try again with /login.")
    else:
        # Original flow (unchanged)
        success = await self._auth_strategy.handle_callback(data, session)
        # ... existing success/failure handling ...
```

### Extending `build_login_keyboard()`
The cleanest approach is to modify `BasicAuthStrategy.build_login_keyboard()` to
accept an optional `next_auth_url` parameter, OR have the wrapper build the URL
and pass it through the config.

### Key Constraints
- Backward compatibility is CRITICAL — bots without `post_auth_actions` must be unaffected
- The `jira_oauth_manager` is accessed via `getattr(config, "jira_oauth_manager", None)` at line 290
- `IdentityMappingService` and `VaultTokenSync` need `db_pool` and `redis` — obtain
  from the app context (the wrapper has access to `self.bot` but may need the app ref)
- The combined callback route must be registered alongside the existing Jira callback route

### References in Codebase
- `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:907-937` — current `handle_web_app_data`
- `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:68-115` — `__init__`
- `packages/ai-parrot/src/parrot/integrations/telegram/auth.py:260-295` — `build_login_keyboard`
- `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:282-299` — `_register_jira_commands`

---

## Acceptance Criteria

- [ ] Combined auth payload processed: BasicAuth + Jira in single WebApp interaction
- [ ] `PostAuthRegistry` initialized from config at wrapper startup
- [ ] `build_login_keyboard` includes `next_auth_url` when `post_auth_actions` configured
- [ ] `handle_web_app_data` dispatches to secondary auth providers
- [ ] Required secondary auth failure → session rollback + error message
- [ ] Optional secondary auth failure → partial success message
- [ ] Standard BasicAuth payload still works (backward compatible)
- [ ] Combined callback route registered in app startup
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py -v`
- [ ] Existing `/connect_jira` flow still works

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestHandleWebAppDataCombined:
    async def test_combined_payload_both_succeed(self):
        """BasicAuth + Jira both succeed → combined success message."""
        ...

    async def test_combined_payload_jira_fails_required(self):
        """BasicAuth ok, Jira fails, required=true → session rolled back."""
        ...

    async def test_combined_payload_jira_fails_optional(self):
        """BasicAuth ok, Jira fails, required=false → partial success."""
        ...

    async def test_standard_payload_unchanged(self):
        """Standard BasicAuth payload (no jira key) → original behavior."""
        ...

    async def test_no_post_auth_actions_configured(self):
        """Config without post_auth_actions → original behavior always."""
        ...


class TestBuildLoginKeyboardWithPostAuth:
    async def test_keyboard_includes_next_auth_url(self):
        """When post_auth_actions has jira, login URL includes next_auth_url."""
        ...

    async def test_keyboard_without_post_auth_actions(self):
        """Without post_auth_actions, login URL is unchanged."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** thoroughly — this is the integration task
2. **Check ALL dependencies** — TASK-756 through TASK-762 must be completed
3. **Read `wrapper.py` lines 68-115 and 907-937** — understand the current flow
4. **Read `auth.py` lines 260-295** — understand keyboard URL construction
5. **Verify all codebase contract entries** — code may have changed during prior tasks
6. **Implement incrementally**: init changes first, then handle_web_app_data, then keyboard
7. **Test each change** before proceeding to the next
8. **Verify backward compatibility** — run existing tests
9. **Move this file** to `sdd/tasks/completed/`
10. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
