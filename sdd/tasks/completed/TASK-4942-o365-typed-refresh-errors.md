# TASK-4942: O365OAuthManager: typed refresh-error classification

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4941
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (O365 paragraph), S7, AC-4, AC-10. `O365OAuthManager._refresh_request` today turns every 400/401
into `PermissionError` (which the base treats as "grant dead") and every other non-200 into `aiohttp.ClientError`.
It must parse the OAuth error code: only `invalid_grant` is `InvalidGrantError`; network failures, 429 and 5xx are
`RefreshTransientError`; other OAuth errors (`invalid_client`, malformed responses, non-grant 400/401) surface as
operational errors that neither delete the grant nor emit `refresh_failed`. No token values in errors.

---

## Scope

- Rewrite `O365OAuthManager._refresh_request` classification (keep endpoint, body and success path).
- Keep `refresh_access_token` (public, used by `O365DeviceCodeCredentialResolver`) delegating to the same code path.
- Test `test_o365_refresh_error_classification` with an aiohttp test server or a stub session.

**NOT in scope**: moving O365 to a descriptor (it keeps its subclass, AC-4); device-code resolver changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/o365_oauth.py` | MODIFY | typed refresh errors |
| `packages/ai-parrot/tests/unit/auth/test_o365_refresh_errors.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.oauth2_base import InvalidGrantError, RefreshTransientError   # created by TASK-4940
import aiohttp
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/o365_oauth.py
class O365OAuthManager(AbstractOAuth2Manager):                                  # :55
    def __init__(self, client_id, client_secret, redirect_uri, *, tenant_id="common", **kwargs)   # :73
    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:     # :140 (anchor) — 400/401 → PermissionError,
                                                                                #   other non-200 → aiohttp.ClientError (:155-164)
    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]  # :167 public, stateless
# packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py:160-166 — catches PermissionError only
#   (InvalidGrantError is a PermissionError subclass, so invalid_grant still falls back to the device flow)
```

### Does NOT Exist
- ~~`O365OAuthManager` descriptor~~ — O365 keeps its hand-written subclass (AC-4).
- ~~an `OAuth2ProtocolError` class~~ — not in the spec; operational errors are plain `RuntimeError` with a sanitized message.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/o365_oauth.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_o365_refresh_errors.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/o365_oauth.py#O365OAuthManager._refresh_request"
  ]
}
```

---

## Implementation Notes

- Parse the body as JSON when possible (`error` field); never echo the body into the exception (it can contain
  correlation ids only, but keep messages to status + error code).
- `aiohttp.ClientError` / `asyncio.TimeoutError` from the request itself → `RefreshTransientError`.
- Behaviour change to record in the Completion Note: `invalid_client` previously fell back to device flow via
  `PermissionError`; now it surfaces as an operational `RuntimeError` (spec AC-10 wants it visible).

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Replace the status handling in `_refresh_request` (block) — *why*: S7 / AC-10.
2. Tests covering invalid_grant, 429, 500, network error, invalid_client, malformed JSON — *why*: spec §4 row.

### `packages/ai-parrot/src/parrot/auth/o365_oauth.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:' o365_oauth.py)
# REPLACE the body of _refresh_request (verified: o365_oauth.py:140-165) WITH:
    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh against Entra; typed outcomes per S7 (no token material in errors)."""
        data = {"grant_type": "refresh_token", "client_id": self.client_id, "client_secret": self.client_secret,
                "refresh_token": refresh_token, "scope": " ".join(self.scopes)}
        session = await self._get_session()
        try:
            async with session.post(self.token_url, data=urlencode(data),
                                    headers={"Content-Type": "application/x-www-form-urlencoded"}) as response:
                if response.status == 200:
                    return await response.json()
                error_code = await self._oauth_error_code(response)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise RefreshTransientError(f"O365 refresh network error: {type(exc).__name__}") from None
        # FILL IN: error_code == "invalid_grant" → InvalidGrantError(f"O365 refresh token rejected (HTTP {status})");
        #          status == 429 or status >= 500 → RefreshTransientError(f"O365 refresh unavailable (HTTP {status})");
        #          anything else → RuntimeError(f"O365 token refresh failed (HTTP {status}, error={error_code or 'unknown'})")
        #          — bounded by AC-10 (only invalid_grant revokes)
        raise NotImplementedError

    @staticmethod
    async def _oauth_error_code(response: aiohttp.ClientResponse) -> Optional[str]:
        """Return the OAuth ``error`` field, or None for a non-JSON / malformed body."""
        # FILL IN: try await response.json(content_type=None) → dict.get("error") if str; except (ValueError,
        #          aiohttp.ContentTypeError) → None
        raise NotImplementedError
```
**Why**: keep the request exactly as today (same endpoint/body) and change only the outcome mapping; the status
code must be captured inside the `async with` (FILL IN: keep `status = response.status` before leaving it).

### FILL IN checklist
- [ ] `o365_oauth.py::O365OAuthManager._refresh_request` — mapping; bounded by AC-10
- [ ] `o365_oauth.py::O365OAuthManager._oauth_error_code` — tolerant parsing
- [ ] imports: `asyncio`, `Optional`, `InvalidGrantError`, `RefreshTransientError` if missing
- [ ] `test_o365_refresh_error_classification` — parametrized cases

---

## Acceptance Criteria

- [ ] AC-10: invalid_grant → `InvalidGrantError`; network/429/5xx → `RefreshTransientError`; invalid_client, other 400/401, malformed body → `RuntimeError`
- [ ] No refresh/access token text appears in any raised message
- [ ] O365 public API and endpoints unchanged (AC-4)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_o365_refresh_errors.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_o365_refresh_errors.py
import pytest
from parrot.auth.oauth2_base import InvalidGrantError, RefreshTransientError

@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,exc", [
    (400, {"error": "invalid_grant"}, InvalidGrantError),
    (429, {}, RefreshTransientError),
    (503, "<html>", RefreshTransientError),
    (401, {"error": "invalid_client"}, RuntimeError),
    (400, "not-json", RuntimeError),
])
async def test_o365_refresh_error_classification(status, body, exc):
    ...  # FILL IN: aiohttp.test_utils server on token_url (or a stub session); assert type is exactly `exc`
         #          (InvalidGrantError is not RuntimeError) and "REFRESH-SECRET" not in str(error)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-terra (codex)
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Merge-tier validation: only red is pre-existing test_invalid_state_returns_400 (issue:e7b7e5906b6e).
