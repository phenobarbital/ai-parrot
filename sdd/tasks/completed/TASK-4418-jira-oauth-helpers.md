# TASK-4418: Extract 3LO OAuth Helpers

**Feature**: FEAT-696 — JiraToolkit upgrades
**Spec**: `sdd/specs/jiratoolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements spec Module 2 — extract the HTTP token-exchange, refresh,
> accessible-resources and /myself calls from `JiraOAuthManager` private
> methods into module-level async functions. The manager delegates to them,
> preserving its behaviour. This is a root task; TASK-4419 (local store) and
> TASK-4422 (CLI) depend on it.

---

## Scope

- Extract `build_authorization_url()`, `exchange_code()`, `refresh_access_token()`,
  `fetch_accessible_resources()`, `fetch_myself()` as module-level functions
  in `jira_oauth.py`.
- Refactor `JiraOAuthManager._exchange_code`, `_fetch_accessible_resources`,
  `_fetch_myself` to delegate to the new helpers.
- Ensure existing `test_jiratoolkit_oauth.py` still passes (AC6).
- Write unit tests for the new helpers.

**NOT in scope**: the local token store (TASK-4419), toolkit wiring (TASK-4421),
or any `jiratoolkit.py` changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | Add module-level helpers; delegate from manager |
| `packages/ai-parrot/tests/unit/test_jira_oauth_helpers.py` | CREATE | Tests for the new helpers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp                                                   # verified: used throughout jira_oauth.py
from parrot.auth.jira_oauth import (                             # verified: jira_oauth.py:31-58
    JiraTokenSet, DEFAULT_SCOPES, AUTHORIZATION_URL,
    TOKEN_URL, ACCESSIBLE_RESOURCES_URL,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/jira_oauth.py
AUTHORIZATION_URL = "https://auth.atlassian.com/authorize"        # L32
TOKEN_URL = "https://auth.atlassian.com/oauth/token"              # L33
ACCESSIBLE_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"  # L34

class JiraTokenSet(BaseModel):                                    # L59
    access_token: str; refresh_token: str; expires_at: float
    cloud_id: str; site_url: str; account_id: str; display_name: str
    email: Optional[str] = None
    # ... more fields

class JiraOAuthManager:                                           # L93
    async def _exchange_code(self, code: str) -> Dict[str, Any]:  # L600
    async def _fetch_accessible_resources(self, access_token: str) -> List[Dict[str, Any]]:  # L619
    async def _fetch_myself(self, access_token: str, cloud_id: str) -> Dict[str, Any]:  # L635
    async def _get_session(self) -> aiohttp.ClientSession:         # (owns session lifecycle)
```

### Does NOT Exist
- ~~module-level `exchange_code()` function~~ — does not exist yet; this task creates it
- ~~module-level `build_authorization_url()` function~~ — does not exist yet
- ~~`python-dotenv`~~ — not a declared dependency

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/jira_oauth.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_jira_oauth_helpers.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/jira_oauth.py#JiraOAuthManager",
    "sym:packages/ai-parrot/src/parrot/auth/jira_oauth.py#JiraTokenSet"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
The new helpers take an explicit `aiohttp.ClientSession` instead of calling
`self._get_session()`. The manager methods become thin wrappers:
```python
async def _exchange_code(self, code):
    session = await self._get_session()
    return await exchange_code(session, client_id=self.client_id, ...)
```

### Key Constraints
- `build_authorization_url` is synchronous (string formatting only).
- `refresh_access_token` mirrors the token-exchange POST with `grant_type=refresh_token`.
- All helpers are pure functions — no state, no Redis, no `self`.

---

## Implementation Blueprint

### Steps (in order)
1. Add module-level helpers before the `JiraOAuthManager` class — *why*: they must be importable without the manager.
2. Refactor manager's three private HTTP methods to delegate — *why*: preserves behaviour (AC6).
3. Write `test_jira_oauth_helpers.py` — *why*: validates helpers independently of Redis/manager.

### `packages/ai-parrot/src/parrot/auth/jira_oauth.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def _exchange_code' packages/ai-parrot/src/parrot/auth/jira_oauth.py)
# BEFORE — insert above `    async def _exchange_code(self, code: str) -> Dict[str, Any]:` (verified: jira_oauth.py:600)
# Place these MODULE-LEVEL functions after the logger and before class JiraOAuthManager.
# Actually, insert them AFTER the JiraTokenSet class and BEFORE JiraOAuthManager.

# --- Insert after line ~90 (after JiraTokenSet class, before JiraOAuthManager) ---

def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: Sequence[str] = DEFAULT_SCOPES,
) -> str:
    """Build the Atlassian 3LO authorization URL."""
    from urllib.parse import urlencode
    params = {
        "audience": "api.atlassian.com",
        "client_id": client_id,
        "scope": " ".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    return f"{AUTHORIZATION_URL}?{urlencode(params)}"


async def exchange_code(
    session: aiohttp.ClientSession,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    """Exchange an authorization code for tokens."""
    async with session.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise ValueError(f"Token exchange failed with status {response.status}: {text}")
        return await response.json()


async def refresh_access_token(
    session: aiohttp.ClientSession,
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> Dict[str, Any]:
    """Refresh an access token using the rotating refresh token."""
    async with session.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise ValueError(f"Token refresh failed with status {response.status}: {text}")
        return await response.json()


async def fetch_accessible_resources(
    session: aiohttp.ClientSession, access_token: str
) -> List[Dict[str, Any]]:
    """Fetch the list of Atlassian sites the token can access."""
    async with session.get(
        ACCESSIBLE_RESOURCES_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise ValueError(f"accessible-resources failed with status {response.status}: {text}")
        data = await response.json()
        if not isinstance(data, list):
            raise ValueError("accessible-resources returned a non-list payload.")
        return data


async def fetch_myself(
    session: aiohttp.ClientSession, access_token: str, cloud_id: str
) -> Dict[str, Any]:
    """Fetch the authenticated user's profile."""
    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself"
    async with session.get(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise ValueError(f"/myself failed with status {response.status}: {text}")
        return await response.json()
```
**Why this shape**: spec §3 M2 interface skeleton; each helper takes an explicit session, no `self`.
Manager delegation is a thin wrapper — keeps existing behaviour unchanged (AC6).

```python
# Refactor _exchange_code (L600) to delegate:
# REPLACE the body of _exchange_code, _fetch_accessible_resources, _fetch_myself
# with calls to the module-level helpers.
```

### `packages/ai-parrot/tests/unit/test_jira_oauth_helpers.py` (CREATE)
```python
"""Tests for module-level 3LO helpers (FEAT-696 M2)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.auth.jira_oauth import (
    build_authorization_url,
    exchange_code,
    refresh_access_token,
    fetch_accessible_resources,
    fetch_myself,
    DEFAULT_SCOPES,
)


class TestBuildAuthorizationUrl:
    def test_contains_required_params(self):
        url = build_authorization_url("cid", "http://localhost/cb", "state123")
        assert "client_id=cid" in url
        assert "state=state123" in url
        assert "prompt=consent" in url
        assert "response_type=code" in url

    def test_custom_scopes(self):
        url = build_authorization_url("cid", "http://x", "s", scopes=["read:jira-work"])
        assert "read%3Ajira-work" in url


# FILL IN: TestExchangeCode, TestRefreshAccessToken, TestFetchAccessibleResources,
#          TestFetchMyself — mock aiohttp.ClientSession, verify payloads and error handling
#          — bounded by spec §4 M2 test rows
```
**Why this shape**: spec §4 says helpers are tested with aiohttp mocked.

### FILL IN checklist
- [ ] `jira_oauth.py` — refactor `_exchange_code`, `_fetch_accessible_resources`, `_fetch_myself` to delegate; bounded by AC6
- [ ] `jira_oauth.py` — add `Sequence` import for `build_authorization_url` signature
- [ ] `test_jira_oauth_helpers.py` — exchange/refresh/resources/myself tests with mocked session; bounded by spec §4 M2

---

## Acceptance Criteria

- [ ] `build_authorization_url()` returns a URL with all required params including `prompt=consent`
- [ ] `exchange_code()`, `refresh_access_token()`, `fetch_accessible_resources()`, `fetch_myself()` post the right payloads (mocked)
- [ ] `JiraOAuthManager._exchange_code` delegates to the new helper (AC6)
- [ ] Existing `test_jiratoolkit_oauth.py` passes unchanged (AC6)
- [ ] `ruff check` clean
- [ ] No new dependency

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_jira_oauth_helpers.py -q`

---

## Test Specification

See `test_jira_oauth_helpers.py` in the blueprint above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug jiratoolkit-upgrades --feature-id FEAT-696`
2. **Read the spec** at `sdd/specs/jiratoolkit-upgrades.spec.md`
3. **Check dependencies** — none; proceed immediately
4. **Verify the Codebase Contract** — read `jira_oauth.py` L600-648, confirm signatures
5. **Update status** in `sdd/tasks/index/jiratoolkit-upgrades.json` → `"in-progress"`
6. **Implement** — add module-level helpers, refactor manager methods
7. **Verify** — run existing `test_jiratoolkit_oauth.py` to confirm AC6
8. **Commit** — stage only `jira_oauth.py` and `test_jira_oauth_helpers.py`
9. **Close** with `scripts/sdd/close_task.sh TASK-4418 jiratoolkit-upgrades verified`

---

## Completion Note


- Task: TASK-4418
- Feature: jiratoolkit-upgrades
- Implementation SHA: 13419a97e4b6f2d358e5c80f1ddee3b1e38d8f05
- Closed at (UTC): 2026-10-16T20:02:16+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: ~84s · Tokens: n/a |
| validation_note | Merge-tier run exit 5/failed: 16 failures, all pre-existing (the two Jira OAuth callback ones reproduce on dev baseline; rest in dataset_guard/pbac/slack/wrappers unrelated). Helper+manager tests 48 passed. |
