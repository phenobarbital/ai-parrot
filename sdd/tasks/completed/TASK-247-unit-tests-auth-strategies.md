# TASK-247: Unit Tests — Auth Strategies & Config

**Feature**: Telegram Integration OAuth2 Auth (FEAT-036)
**Spec**: `sdd/specs/telegram-integrations-auth.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-241, TASK-242, TASK-243, TASK-244
**Assigned-to**: claude-session

---

## Context

> Comprehensive unit tests for the auth strategy abstraction, OAuth2 provider registry, OAuth2 strategy, and config model updates.
> Implements spec Section 4 — Unit Tests.

---

## Scope

### Test Files
- `tests/integrations/telegram/test_auth_strategies.py` — strategy tests
- `tests/integrations/telegram/test_oauth2_providers.py` — provider registry tests
- `tests/integrations/telegram/test_telegram_config.py` — config model tests

### Tests to Implement

**Config Model Tests** (`test_telegram_config.py`):
- `test_config_auth_method_default` — default is `"basic"`
- `test_config_oauth2_env_fallback` — client_id/secret from env vars
- `test_config_from_dict_with_oauth2` — `from_dict()` parses OAuth2 fields
- `test_config_validate_oauth2_missing_client_id` — validation error

**Provider Registry Tests** (`test_oauth2_providers.py`):
- `test_oauth2_provider_google_config` — correct URLs and scopes
- `test_oauth2_provider_unknown_raises` — ValueError for unknown provider

**Auth Strategy Tests** (`test_auth_strategies.py`):
- `test_basic_strategy_login_keyboard` — returns WebApp keyboard
- `test_basic_strategy_handle_callback` — processes navigator data
- `test_oauth2_strategy_build_authorize_url` — correct URL with PKCE params
- `test_oauth2_strategy_exchange_code` — mocked POST to token_url
- `test_oauth2_strategy_exchange_code_failure` — handles HTTP errors
- `test_oauth2_strategy_fetch_userinfo` — mocked GET to userinfo_url
- `test_oauth2_strategy_state_validation` — mismatched state rejected
- `test_oauth2_strategy_pkce_challenge` — code_challenge is valid S256
- `test_session_oauth2_fields` — session stores OAuth2 tokens
- `test_session_clear_auth_clears_oauth2` — clear_auth resets OAuth2 fields

### Test Fixtures
Use fixtures from spec Section 4:
- `google_oauth2_config`
- `basic_auth_config`
- `mock_google_token_response`
- `mock_google_userinfo`

**NOT in scope**: Integration tests (TASK-248).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integrations/telegram/test_auth_strategies.py` | CREATE | Auth strategy unit tests |
| `tests/integrations/telegram/test_oauth2_providers.py` | CREATE | Provider registry tests |
| `tests/integrations/telegram/test_telegram_config.py` | CREATE or MODIFY | Config model tests |

---

## Implementation Notes

- Use `pytest-asyncio` for async test methods
- Mock `aiohttp.ClientSession` for HTTP calls in OAuth2 strategy tests
- Use `unittest.mock.patch` or `aioresponses` for mocking
- Ensure tests don't require network access

---

## Acceptance Criteria

- [ ] All 16 unit tests defined in spec Section 4 are implemented
- [ ] All tests pass: `pytest tests/integrations/telegram/ -v`
- [ ] No network calls in unit tests (all HTTP mocked)
- [ ] PKCE verification: code_challenge matches SHA256 of code_verifier

---

## Agent Instructions

When you pick up this task:

1. **Verify** TASK-241, TASK-242, TASK-243, TASK-244 are complete
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Implement** all test files
4. **Run** `pytest tests/integrations/telegram/ -v`
5. **Move this file** to `sdd/tasks/completed/`
6. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. All 16 spec-required unit tests verified across 5 test files (71 total tests, all passing):

- `test_auth_strategies.py` — 13 tests: BasicAuthStrategy keyboard/callback, OAuth2Strategy PKCE, authorize URL, exchange code (success/failure), fetch userinfo, state validation, session fields, clear_auth
- `test_oauth2_providers.py` — 8 tests: Google provider config, unknown provider raises, all required fields, default scopes
- `test_telegram_config.py` / `test_config_oauth2.py` — 16 tests: auth_method default, env fallback, from_dict parsing, OAuth2 validation
- `test_oauth2_strategy.py` — 28 tests: comprehensive OAuth2Strategy coverage (PKCE S256, state TTL, token exchange, userinfo, session expiry)
- `test_wrapper_strategy_factory.py` — 6 tests: strategy factory creates correct strategy based on config (BasicAuth, OAuth2, None, priority rules)

13 of the 16 spec tests already existed from TASK-242/243/244 implementations. Created `test_wrapper_strategy_factory.py` with the 3 remaining spec tests plus 3 edge cases. All tests run without network access (HTTP fully mocked).
