# TASK-242: Auth Strategy Abstraction & BasicAuthStrategy

**Feature**: Telegram Integration OAuth2 Auth (FEAT-036)
**Spec**: `sdd/specs/telegram-integrations-auth.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-241
**Assigned-to**: claude-session

---

## Context

> Define `AbstractAuthStrategy` ABC and refactor the existing `NavigatorAuthClient` into `BasicAuthStrategy`. This establishes the strategy pattern that `OAuth2AuthStrategy` (TASK-244) will implement.
> Implements spec Module 1 and Module 7 (session model updates).

---

## Scope

### AbstractAuthStrategy ABC
- Define in `parrot/integrations/telegram/auth.py`:
  ```python
  class AbstractAuthStrategy(ABC):
      async def build_login_keyboard(self, config, state: str) -> ReplyKeyboardMarkup
      async def handle_callback(self, data: dict, session: TelegramUserSession) -> bool
      async def validate_token(self, token: str) -> bool
  ```

### BasicAuthStrategy
- Wraps existing `NavigatorAuthClient` logic
- `build_login_keyboard()` — returns the WebApp keyboard with `login_page_url` + `auth_url` (current `handle_login` logic)
- `handle_callback()` — parses `{user_id, token, display_name}` from WebApp data (current `handle_web_app_data` logic)
- `validate_token()` — delegates to `NavigatorAuthClient.validate_token()`

### TelegramUserSession Updates
- Add fields: `oauth2_access_token`, `oauth2_id_token`, `oauth2_provider`
- Update `clear_auth()` to also clear OAuth2 fields

### Keep `NavigatorAuthClient` as-is
- Don't delete it — `BasicAuthStrategy` wraps it internally

**NOT in scope**: `OAuth2AuthStrategy` (TASK-244), wrapper refactor (TASK-245).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/auth.py` | MODIFY | Add `AbstractAuthStrategy` ABC, `BasicAuthStrategy`, update `TelegramUserSession` |

---

## Implementation Notes

- `BasicAuthStrategy.__init__` should accept `auth_url: str` and `login_page_url: Optional[str]`
- The `build_login_keyboard` method needs `from urllib.parse import urlencode` and aiogram keyboard imports
- Follow existing error handling patterns from `NavigatorAuthClient`
- Use `self.logger` for logging

---

## Acceptance Criteria

- [ ] `AbstractAuthStrategy` is defined with 3 abstract async methods
- [ ] `BasicAuthStrategy` wraps `NavigatorAuthClient` and implements all 3 methods
- [ ] `BasicAuthStrategy.build_login_keyboard()` produces same WebApp keyboard as current `handle_login`
- [ ] `BasicAuthStrategy.handle_callback()` handles same data format as current `handle_web_app_data`
- [ ] `TelegramUserSession` has `oauth2_access_token`, `oauth2_id_token`, `oauth2_provider` fields
- [ ] `clear_auth()` clears OAuth2 fields
- [ ] Unit tests: `test_basic_strategy_login_keyboard`, `test_basic_strategy_handle_callback`, `test_session_oauth2_fields`

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/integrations/telegram/auth.py` and wrapper.py (login handlers) fully
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Implement** the strategy abstraction and BasicAuthStrategy
4. **Run** `pytest tests/integrations/telegram/ -v`
5. **Move this file** to `sdd/tasks/completed/`
6. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. Refactored `parrot/integrations/telegram/auth.py`:
- Added `AbstractAuthStrategy` ABC with 3 abstract async methods (`build_login_keyboard`, `handle_callback`, `validate_token`)
- Added `BasicAuthStrategy` wrapping existing `NavigatorAuthClient` — produces identical WebApp keyboard and callback handling
- Extended `TelegramUserSession` with `oauth2_access_token`, `oauth2_id_token`, `oauth2_provider` fields
- Updated `clear_auth()` to clear OAuth2 fields
- `NavigatorAuthClient` preserved unchanged (used internally by `BasicAuthStrategy`)
- 13 unit tests pass in `tests/integrations/telegram/test_auth_strategies.py`
- All 37 telegram integration tests pass.
