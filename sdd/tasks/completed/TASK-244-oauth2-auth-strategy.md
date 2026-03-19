# TASK-244: OAuth2 Auth Strategy with PKCE Support

**Feature**: Telegram Integration OAuth2 Auth (FEAT-036)
**Spec**: `sdd/specs/telegram-integrations-auth.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-6h)
**Depends-on**: TASK-242, TASK-243
**Assigned-to**: claude-session

---

## Context

> Implement `OAuth2AuthStrategy` that handles the full OAuth2 Authorization Code flow with PKCE. Builds the authorize URL, exchanges the authorization code for tokens, and fetches user profile from the provider's userinfo endpoint.
> Implements spec Module 3. Incorporates Open Question answers: PKCE=Yes, Token TTL=7 days.

---

## Scope

### OAuth2AuthStrategy class (in `parrot/integrations/telegram/auth.py`)

- Extends `AbstractAuthStrategy`
- Constructor: `__init__(self, config: TelegramAgentConfig)`
  - Resolves provider via `get_provider(config.oauth2_provider)`
  - Stores `client_id`, `client_secret`, `redirect_uri`, scopes
- `build_login_keyboard(config, state)`:
  - Generates PKCE `code_verifier` and `code_challenge` (S256)
  - Stores `{state: code_verifier}` in `_pending_states` dict
  - Builds authorization URL with params: `client_id`, `redirect_uri`, `scope`, `state`, `code_challenge`, `code_challenge_method=S256`, `response_type=code`, `access_type=offline`
  - Returns `ReplyKeyboardMarkup` with WebApp button pointing to authorize URL
- `handle_callback(data, session)`:
  - Validates `state` against `_pending_states`
  - Extracts `code` from callback data
  - Calls `exchange_code(code, code_verifier)` to get tokens
  - Calls `fetch_userinfo(access_token)` to get profile
  - Populates session: `set_authenticated(user_id=sub, token=access_token, ...)`
  - Sets `session.oauth2_access_token`, `session.oauth2_id_token`, `session.oauth2_provider`
  - Returns `True` on success
- `exchange_code(code, code_verifier)`:
  - POST to `token_url` with `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id`, `client_secret`, `code_verifier`
  - Returns token response dict
- `fetch_userinfo(access_token)`:
  - GET `userinfo_url` with `Authorization: Bearer {access_token}`
  - Returns userinfo dict
- `validate_token(token)`:
  - Check token is non-empty and session hasn't expired (7-day TTL from `authenticated_at`)

### PKCE Implementation
```python
import hashlib, base64, secrets

code_verifier = secrets.token_urlsafe(64)
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode()).digest()
).rstrip(b"=").decode()
```

### State Management
- `_pending_states: Dict[str, str]` — maps `state` → `code_verifier`
- States are consumed (deleted) after use
- States expire after 10 minutes (cleanup on access)

**NOT in scope**: Wrapper integration (TASK-245), callback endpoint (TASK-246).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/auth.py` | MODIFY | Add `OAuth2AuthStrategy` class |

---

## Implementation Notes

- Use `aiohttp.ClientSession` for HTTP calls (token exchange, userinfo)
- Never log `client_secret`, `code_verifier`, or `access_token` values
- Handle HTTP errors gracefully — log warnings and return `False` / `None`
- Token TTL: 7 days (from Open Question 4)
- PKCE is mandatory (from Open Question 2)
- Use `secrets.token_urlsafe(32)` for state parameter

---

## Acceptance Criteria

- [ ] `OAuth2AuthStrategy` implements all 3 `AbstractAuthStrategy` methods
- [ ] PKCE code_verifier and code_challenge are generated correctly (S256)
- [ ] Authorization URL includes all required params (client_id, scope, state, code_challenge, etc.)
- [ ] `exchange_code()` POSTs to token_url with correct payload including `code_verifier`
- [ ] `fetch_userinfo()` GETs userinfo_url with Bearer token
- [ ] State validation: mismatched state returns `False`
- [ ] Token validation checks 7-day TTL
- [ ] Session is populated with OAuth2-specific fields
- [ ] Unit tests: `test_oauth2_strategy_build_authorize_url`, `test_oauth2_strategy_exchange_code`, `test_oauth2_strategy_exchange_code_failure`, `test_oauth2_strategy_fetch_userinfo`

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/integrations/telegram/auth.py` (with TASK-242 changes applied)
2. **Read** `parrot/integrations/telegram/oauth2_providers.py` (TASK-243)
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** `OAuth2AuthStrategy` with PKCE
5. **Write tests** — mock aiohttp responses for token exchange and userinfo
6. **Run** `pytest tests/integrations/telegram/ -v`
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. Implemented `OAuth2AuthStrategy` in `parrot/integrations/telegram/auth.py`:
- Full OAuth2 Authorization Code flow with PKCE (S256)
- `build_login_keyboard()` — generates code_verifier/challenge, builds Google authorize URL with all params
- `handle_callback()` — validates state, exchanges code for tokens, fetches userinfo, populates session
- `exchange_code()` — POST to token_url with PKCE code_verifier
- `fetch_userinfo()` — GET userinfo_url with Bearer token
- `is_session_expired()` — 7-day TTL validation
- State management with 10-minute expiry and auto-cleanup
- 28 unit tests pass in `tests/integrations/telegram/test_oauth2_strategy.py`
- All 65 telegram integration tests pass.
