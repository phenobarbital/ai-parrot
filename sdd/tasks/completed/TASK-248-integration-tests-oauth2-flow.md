# TASK-248: Integration Tests — OAuth2 Full Flow

**Feature**: Telegram Integration OAuth2 Auth (FEAT-036)
**Spec**: `sdd/specs/telegram-integrations-auth.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-245, TASK-246, TASK-247
**Assigned-to**: claude-session

---

## Context

> End-to-end integration tests that verify the complete OAuth2 flow through the wrapper, including the aiohttp callback endpoint. Also verifies backward compatibility with existing Basic Auth.
> Implements spec Section 4 — Integration Tests.

---

## Scope

### Tests to Implement (`tests/integrations/telegram/test_oauth2_integration.py`)

- `test_oauth2_full_flow_google`:
  Simulate the complete flow: `/login` → authorize URL generated → callback with code → token exchange (mocked) → userinfo (mocked) → session authenticated with Google profile
- `test_basic_auth_unchanged`:
  Existing Basic Auth config → `/login` → Navigator WebApp keyboard → WebApp data callback → session authenticated (identical to pre-refactor behavior)
- `test_handle_login_delegates_to_strategy`:
  Config with `auth_method="oauth2"` → `/login` produces OAuth2 keyboard; config with `auth_method="basic"` → produces Navigator keyboard
- `test_handle_web_app_data_routes_to_strategy`:
  OAuth2 callback data `{provider, code, state}` → routed to `OAuth2AuthStrategy`; Navigator data `{user_id, token}` → routed to `BasicAuthStrategy`
- `test_force_auth_with_oauth2`:
  `force_authentication=True` + `auth_method="oauth2"` → unauthenticated message blocked → OAuth2 login prompt shown
- `test_oauth2_callback_endpoint`:
  GET `/oauth2/callback?code=abc&state=xyz` → returns HTML with `sendData` call
- `test_oauth2_state_mismatch_rejected`:
  Callback with wrong state → authentication fails gracefully
- `test_logout_clears_oauth2_session`:
  Authenticated OAuth2 session → `/logout` → session cleared including OAuth2 tokens

**NOT in scope**: Live Google API calls (all provider HTTP calls are mocked).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integrations/telegram/test_oauth2_integration.py` | CREATE | Integration tests |

---

## Implementation Notes

- Use `aiohttp.test_utils.TestServer` for testing the callback endpoint
- Mock aiogram `Bot` and `Message` objects
- Mock `aiohttp.ClientSession` for Google token/userinfo endpoints
- Test the wrapper end-to-end by calling handler methods directly with mock messages

---

## Acceptance Criteria

- [ ] All 8 integration tests implemented and passing
- [ ] Full OAuth2 flow test covers: login → callback → token exchange → userinfo → session
- [ ] Basic Auth backward compatibility verified
- [ ] Force authentication with OAuth2 tested
- [ ] Callback endpoint tested via aiohttp test client
- [ ] `pytest tests/integrations/telegram/test_oauth2_integration.py -v` passes

---

## Agent Instructions

When you pick up this task:

1. **Verify** all dependency tasks (TASK-245, TASK-246, TASK-247) are complete
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Implement** integration test file
4. **Run** `pytest tests/integrations/telegram/ -v`
5. **Move this file** to `sdd/tasks/completed/`
6. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. Created `tests/integrations/telegram/test_oauth2_integration.py` with all 8 integration tests:

1. `test_oauth2_full_flow_google` — Complete flow: /login → authorize URL → callback with code+state → token exchange (mocked) → userinfo (mocked) → session authenticated with Google profile
2. `test_basic_auth_unchanged` — Navigator WebApp keyboard + callback handling identical to pre-refactor
3. `test_handle_login_delegates_to_strategy` — OAuth2 config → "Sign in with Google"; Basic config → "Sign in to Navigator"
4. `test_handle_web_app_data_routes_to_strategy` — OAuth2 data routed to OAuth2AuthStrategy; Navigator data to BasicAuthStrategy
5. `test_force_auth_with_oauth2` — Unauthenticated user blocked, after auth passes through
6. `test_oauth2_callback_endpoint` — GET /oauth2/callback returns HTML with sendData via aiohttp TestClient
7. `test_oauth2_state_mismatch_rejected` — Wrong state rejected gracefully
8. `test_logout_clears_oauth2_session` — All OAuth2 fields cleared on logout

All 79 telegram tests pass (71 unit + 8 integration). No network calls in any test.
