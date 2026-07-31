---
type: Wiki Overview
title: 'TASK-1618: GigSmart OAuth 2.1 Authentication'
id: doc:sdd-tasks-completed-task-1618-gigsmart-oauth-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: OAuth 2.1 token lifecycle management for GigSmart API. Supports both
relates_to:
- concept: mod:parrot_tools.interfaces.gigsmart.auth
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.config
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.exceptions
  rel: mentions
---

# TASK-1618: GigSmart OAuth 2.1 Authentication

**Feature**: FEAT-253 — GigSmart Interface Toolkit
**Spec**: `sdd/specs/gigsmart-interface-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1616, TASK-1617
**Assigned-to**: unassigned

---

## Context

OAuth 2.1 token lifecycle management for GigSmart API. Supports both
client_credentials (read-only, 15min tokens) and auth_code+PKCE (full access,
1h tokens). Implements Spec §2 and §7 (OAuth 2.1 Implementation Notes).

---

## Scope

- Implement `GigSmartAuth` class managing OAuth token lifecycle
- Client credentials grant: acquire token via HTTP Basic auth to `/oauth/token`
- Auth code + PKCE grant: generate code_verifier/code_challenge, exchange code for token
- Token caching in memory with proactive refresh (re-auth when <2min remaining)
- `build_headers()` method returning `Authorization: Bearer <token>` dict
- Scope validation: raise `GigSmartAuthError` on write ops with client_credentials token
- Support pre-configured refresh token via `GIGSMART_REFRESH_TOKEN` env var
- Write unit tests with mocked HTTP responses

**NOT in scope**: HTTP client setup (TASK-1621), actual API calls (TASK-1622).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/auth.py` | CREATE | OAuth authentication |
| `tests/tools/gigsmart/test_auth.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig  # TASK-1617
from parrot_tools.interfaces.gigsmart.exceptions import GigSmartAuthError, GigSmartError  # TASK-1616
import aiohttp  # CLAUDE.md mandates aiohttp, not httpx
```

### Does NOT Exist
- ~~`httpx`~~ — do NOT use; CLAUDE.md mandates aiohttp
- ~~`GigSmartCredentials`~~ — brainstorm SPEC name; use `GigSmartConfig`
- ~~Simple `Authorization: Bearer <api_key>` auth~~ — actual auth is OAuth 2.1 token exchange

---

## Implementation Notes

### OAuth Token Response (from GigSmart docs)
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_token": "dGhpcyBpcyBhIHJlZnJl...",
  "scope": "read:gigs read:engagements"
}
```

### Client Credentials Flow
```bash
curl -X POST https://api.gigsmart.com/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "$CLIENT_ID:$CLIENT_SECRET" \
  -d "grant_type=client_credentials&scope=read:gigs"
```

### Auth Code + PKCE Flow
1. Generate `code_verifier` (43-128 char random string)
2. Compute `code_challenge` = base64url(sha256(code_verifier))
3. Build authorize URL with `code_challenge_method=S256`
4. After user authorizes, exchange code at token endpoint with `code_verifier`

### Key Constraints
- Token caching: store `(access_token, expires_at, scopes, refresh_token)` in memory
- Proactive refresh: if `expires_at - now < 120 seconds`, refresh before returning
- Write scope enforcement: check that required scope is in token's scope string
- Use `aiohttp.ClientSession` for token endpoint calls (not httpx)
- Thread-safe: use `asyncio.Lock` to prevent concurrent token refreshes

### Write-Only Scopes (auth_code grant only)
`write:gigs`, `write:engagements`, `write:organizations`, `write:positions`,
`write:locations`, `write:messages`

---

## Acceptance Criteria

- [ ] `GigSmartAuth` acquires client_credentials token via mock endpoint
- [ ] Token caching works — second call returns cached token
- [ ] Proactive refresh triggers when token has <2min remaining
- [ ] `build_headers()` returns `{"Authorization": "Bearer <token>"}`
- [ ] Write scope validation raises `GigSmartAuthError` for client_credentials tokens
- [ ] PKCE code_verifier/code_challenge generation is correct (SHA-256, base64url)
- [ ] Pre-configured refresh token from env var works
- [ ] Tests pass: `pytest tests/tools/gigsmart/test_auth.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, patch
from parrot_tools.interfaces.gigsmart.auth import GigSmartAuth
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig
from parrot_tools.interfaces.gigsmart.exceptions import GigSmartAuthError

@pytest.fixture
def config():
    return GigSmartConfig(client_id="test-id", client_secret="test-secret")

class TestGigSmartAuth:
    async def test_client_credentials_token(self, config):
        auth = GigSmartAuth(config)
        # Mock aiohttp response
        token = await auth.get_token(scopes=["read:gigs"])
        assert token is not None

    async def test_build_headers(self, config):
        auth = GigSmartAuth(config)
        headers = await auth.build_headers()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

    async def test_write_scope_rejected_for_client_credentials(self, config):
        auth = GigSmartAuth(config)
        with pytest.raises(GigSmartAuthError, match="write.*scope"):
            await auth.ensure_scope("write:gigs")

    def test_pkce_challenge_generation(self):
        verifier, challenge = GigSmartAuth.generate_pkce_pair()
        assert len(verifier) >= 43
        assert len(challenge) > 0
```

---

## Completion Note

*(Agent fills this in when done)*
