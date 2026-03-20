# TASK-245: Wrapper — Delegate Auth to Strategy

**Feature**: Telegram Integration OAuth2 Auth (FEAT-036)
**Spec**: `sdd/specs/telegram-integrations-auth.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-241, TASK-242, TASK-244
**Assigned-to**: claude-session

---

## Context

> Refactor `TelegramAgentWrapper` to delegate authentication to the configured auth strategy. The wrapper's `__init__` creates the correct strategy based on `config.auth_method`, and `handle_login` / `handle_web_app_data` delegate to it.
> Implements spec Module 5.

---

## Scope

### Strategy Factory in `__init__`
- Replace direct `NavigatorAuthClient` instantiation with strategy creation:
  ```python
  if config.auth_method == "oauth2":
      self._auth_strategy = OAuth2AuthStrategy(config)
  elif config.auth_url:
      self._auth_strategy = BasicAuthStrategy(config.auth_url, config.login_page_url)
  else:
      self._auth_strategy = None
  ```
- Remove `self._auth_client` field (replaced by `self._auth_strategy`)
- Add `self._pending_oauth_states: Dict[int, str]` for CSRF state tracking

### Refactor `handle_login` (wrapper.py:771)
- Check `session.authenticated` (unchanged)
- Check `self._auth_strategy` is not None
- Generate state via `secrets.token_urlsafe(32)`
- Store state: `self._pending_oauth_states[user.id] = state`
- Delegate keyboard creation: `keyboard = await self._auth_strategy.build_login_keyboard(self.config, state)`
- Send keyboard to user

### Refactor `handle_web_app_data` (wrapper.py:844)
- Parse JSON data from `message.web_app_data.data`
- Delegate to strategy: `success = await self._auth_strategy.handle_callback(data, session)`
- If success: send authenticated message
- If fail: send error message
- Clean up `_pending_oauth_states[user.id]`

### Refactor `handle_logout`
- Call `session.clear_auth()` (unchanged — already clears OAuth2 fields from TASK-242)

### Handler Registration
- Update the condition for registering `/login` and `/logout`:
  - Current: `if self.config.enable_login and self._auth_client`
  - New: `if self.config.enable_login and self._auth_strategy`

**NOT in scope**: OAuth2 callback endpoint (TASK-246), tests for full flow (TASK-248).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/wrapper.py` | MODIFY | Refactor auth initialization, `handle_login`, `handle_web_app_data` |

---

## Implementation Notes

- Import `BasicAuthStrategy`, `OAuth2AuthStrategy` from `.auth`
- Keep the same user-facing messages for Basic Auth (backward compat)
- For OAuth2, adjust messages: "Sign in with Google" instead of "Sign in to Navigator"
- The `state` parameter is generated in the wrapper (not the strategy) because the wrapper manages per-user state tracking
- Be careful not to break existing callback handler registration

---

## Acceptance Criteria

- [ ] `self._auth_client` replaced with `self._auth_strategy`
- [ ] Strategy factory creates `BasicAuthStrategy` for `auth_method="basic"` with `auth_url`
- [ ] Strategy factory creates `OAuth2AuthStrategy` for `auth_method="oauth2"`
- [ ] Strategy is `None` when no auth is configured (no `auth_url`, no `oauth2_client_id`)
- [ ] `handle_login` delegates to `_auth_strategy.build_login_keyboard()`
- [ ] `handle_web_app_data` delegates to `_auth_strategy.handle_callback()`
- [ ] Existing Basic Auth flow works identically
- [ ] Unit tests: `test_strategy_factory_basic`, `test_strategy_factory_oauth2`, `test_backward_compat_no_auth_method`

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/integrations/telegram/wrapper.py` fully (especially lines 65-100, 160-175, 771-882)
2. **Verify** TASK-241, TASK-242, TASK-244 are complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** wrapper refactoring
5. **Run** `pytest tests/integrations/telegram/ -v`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. Refactored `parrot/integrations/telegram/wrapper.py`:
- Replaced `self._auth_client` (NavigatorAuthClient) with `self._auth_strategy` (BasicAuthStrategy or OAuth2AuthStrategy)
- Strategy factory in `__init__`: creates OAuth2AuthStrategy when `auth_method="oauth2"`, BasicAuthStrategy when `auth_url` is set, None otherwise
- `handle_login` now delegates keyboard building to `_auth_strategy.build_login_keyboard()`
- `handle_web_app_data` now delegates callback processing to `_auth_strategy.handle_callback()`
- Updated handler registration, menu commands, and `/help` whoami to use `_auth_strategy`
- OAuth2 login shows "Sign in with Google" prompt; Basic Auth shows "Sign in to Navigator" (backward compat)
- Removed all references to `NavigatorAuthClient` from wrapper
- All 65 telegram integration tests pass (excluding WIP TASK-246 callback tests)
