---
type: Wiki Overview
title: 'TASK-993: End-to-End Integration Tests'
id: doc:sdd-tasks-completed-task-993-e2e-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'End-to-end integration tests that validate the full backend flow: connect
  →'
relates_to:
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
---

# TASK-993: End-to-End Integration Tests

**Feature**: FEAT-144 — Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)
**Spec**: `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-983, TASK-984, TASK-985, TASK-986, TASK-987, TASK-988, TASK-989
**Assigned-to**: unassigned

---

## Context

End-to-end integration tests that validate the full backend flow: connect →
enable → chat (with toolkit) → disconnect, plus regression guards for the
Telegram path. These tests use mocked Atlassian endpoints but exercise real
handler → service → persistence → callback chains.

Implements spec §4 Integration Tests.

---

## Scope

- Create `tests/integration/oauth2/` test package.
- Implement the five integration tests from spec §4:
  1. `test_e2e_web_connect_jira_happy_path` — full connect → enable → chat flow.
  2. `test_e2e_auth_required_envelope_when_not_connected` — chat without credential
     returns `auth_required` envelope.
  3. `test_e2e_disconnect_removes_credential_and_enablement` — disconnect cascades.
  4. `test_e2e_cold_session_rehydration` — wipe Redis, verify hydration from DocumentDB.
  5. `test_e2e_telegram_unaffected` — Telegram flow regression guard.
- Create `conftest.py` with shared fixtures (from spec §4 Test Data).

**NOT in scope**: Frontend E2E tests (separate repo, separate test framework).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/oauth2/__init__.py` | CREATE | Test package |
| `tests/integration/oauth2/conftest.py` | CREATE | Shared fixtures |
| `tests/integration/oauth2/test_e2e_web_connect.py` | CREATE | Happy path + disconnect tests |
| `tests/integration/oauth2/test_e2e_auth_envelope.py` | CREATE | Auth envelope test |
| `tests/integration/oauth2/test_e2e_cold_session.py` | CREATE | Cold session rehydration |
| `tests/integration/oauth2/test_e2e_telegram_regression.py` | CREATE | Telegram regression |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All modules from TASK-983 through TASK-989:
from parrot.integrations.oauth2.models import (
    IntegrationDescriptor, ConnectInitResponse, AuthRequiredEnvelope,
    UsersIntegrationRow, UserAgentToolkitRow,
)
from parrot.integrations.oauth2.registry import OAuth2ProviderRegistry
from parrot.integrations.oauth2.service import IntegrationsService
from parrot.integrations.oauth2.persistence import (
    get_users_integration, list_user_agent_toolkits,
)
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet
from parrot.auth.exceptions import AuthorizationRequired
```

### Test Fixtures from Spec
```python
@pytest.fixture
def web_user_id() -> str:
    return "user-test-1234"

@pytest.fixture
def jira_token_set_factory():
    from parrot.auth.jira_oauth import JiraTokenSet
    import time
    def _make(**overrides):
        base = dict(
            access_token="at-XYZ", refresh_token="rt-XYZ",
            expires_at=time.time() + 3600,
            cloud_id="cloud-1", site_url="https://example.atlassian.net",
            account_id="acct-1", display_name="Test User",
            email="test@example.com",
            scopes=["read:jira-work", "write:jira-work", "offline_access"],
            granted_at=time.time(), last_refreshed_at=time.time(),
            available_sites=[],
        )
        base.update(overrides)
        return JiraTokenSet(**base)
    return _make

@pytest.fixture
def allowed_origins(monkeypatch):
    monkeypatch.setenv("WEB_OAUTH_ALLOWED_ORIGINS", "https://app.example.com")
    yield ["https://app.example.com"]
```

### Does NOT Exist
- ~~`tests/integration/oauth2/`~~ — does not exist; this task creates it.
- ~~A running Atlassian OAuth server in tests~~ — all Atlassian interactions must
  be mocked (mock `JiraOAuthManager.create_authorization_url` and `handle_callback`).
- ~~A running DocumentDB in CI~~ — check whether integration tests use a real
  DocumentDB or mock it. Follow the pattern in existing integration tests.

---

## Implementation Notes

### Test Structure
Each E2E test should:
1. Set up fixtures (user, agent, mocked Atlassian, mocked/real DocumentDB).
2. Exercise the full chain through the handler layer (use `aiohttp.test_utils`).
3. Assert on both the HTTP response AND the persistence state.

### Key Constraints
- Mock Atlassian OAuth endpoints, NOT the service layer (test the full stack).
- Use `aiohttp.test_utils.AioHTTPTestCase` or `pytest-aiohttp` for handler tests.
- Clean up DocumentDB state between tests (drop/clear test collections).
- Telegram regression test must NOT modify any Telegram-specific code paths.

---

## Acceptance Criteria

- [ ] All five E2E tests from spec §4 pass.
- [ ] Tests run in isolation (no cross-test state leakage).
- [ ] Telegram regression test verifies the callback path is unchanged.
- [ ] Cold-session rehydration test simulates Redis miss + DocumentDB read.
- [ ] All tests pass: `pytest tests/integration/oauth2/ -v`
- [ ] No lint errors.

---

## Agent Instructions

When you pick up this task:

1. **Check ALL dependencies** — TASK-983 through TASK-989 must be complete.
2. **Read** existing integration test patterns in `tests/integration/` for conventions.
3. **Determine** whether integration tests use real DocumentDB or mocks.
4. **Implement** tests following the spec §4 descriptions exactly.
5. **Verify** all five tests pass.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
