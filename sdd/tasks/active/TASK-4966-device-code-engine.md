# TASK-4966: Generic RFC 8628 device-code client engine

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (G6, S8, AC-10): a typed, pure RFC 8628 client engine shared by `parrot login` (TASK-4968, against
navigator-auth's `Oauth2Provider`) and by the server-side provider device grant (TASK-4967). Today only the O365-bound
`O365DeviceCodeCredentialResolver` exists; there is no generic engine.

---

## Scope

- Create `packages/ai-parrot/src/parrot/auth/oauth2/device_code.py` with `DeviceAuthorization`, `DeviceCodeError`,
  `make_pkce_pair`, `discover_authorization_server`, `request_device_authorization`, `request_device_token`
  (one token-endpoint poll) and `poll_device_token` (the loop).
- Unit tests for the state machine: pending → slow_down (+5 s) → approved; `expired_token` / `access_denied` raise;
  timeout; cancellation propagates.

**NOT in scope**: the CLI `parrot login` command (TASK-4968); the manager's server-side device grant (TASK-4967); any change to `o365_devicecode_provider.py` (TASK-4967); exporting from `parrot/auth/oauth2/__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/device_code.py` | CREATE | RFC 8628 client engine |
| `packages/ai-parrot/tests/auth/test_device_code_engine.py` | CREATE | state-machine tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
import aiohttp                                   # core dependency
from pydantic import BaseModel                   # pydantic v2
# stdlib only otherwise: asyncio, base64, hashlib, logging, secrets, time, typing
```

### Existing Signatures to Use
```python
# navigator-auth 0.28.x (.venv/lib/python3.12/site-packages/navigator_auth/backends/oauth2/)
# metadata.py:42  WELL_KNOWN_AS_PATH = "/.well-known/oauth-authorization-server"
#   metadata document keys used: device_authorization_endpoint, token_endpoint, userinfo_endpoint, revocation_endpoint
# backend.py device_authorization (:2500): form fields client_id, scope, code_challenge, code_challenge_method=S256
#   (PKCE S256 REQUIRED for public clients, :2528-2540)
# backend.py _handle_device_code (:2105): grant_type=urn:ietf:params:oauth:grant-type:device_code, device_code,
#   client_id, code_verifier; error JSON {"error": authorization_pending|slow_down|expired_token|access_denied|invalid_grant}
# conf.py: OAUTH_DEVICE_POLL_INTERVAL=5 (:788), OAUTH_DEVICE_SLOW_DOWN_INCREMENT=5 (:791)
# Reference PKCE implementation: parrot/auth/oauth2_base.py:389-394 AbstractOAuth2Manager._new_pkce_pair (staticmethod)
```

### Does NOT Exist
- ~~`parrot.auth.oauth2.device_code`~~ — this task creates it; there is no generic engine on `dev`.
- ~~importing navconfig / `parrot.conf` in `device_code.py`~~ — must stay pure (used from stdio-adjacent CLI code, FEAT-485).
- ~~`navigator_auth` imports~~ — the engine is an HTTP client of navigator-auth, never imports it.
- ~~exporting these names from `parrot/auth/oauth2/__init__.py`~~ — out of scope (keeps the shared `__init__` untouched).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/device_code.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/auth/test_device_code_engine.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- **Task-level additions (do not change spec signatures):** `request_device_token(...)` (one poll; the server needs a
  single poll per CLI poll, TASK-4967) and an optional keyword `client_secret` on `request_device_authorization` /
  `request_device_token` / `poll_device_token` (confidential providers such as Google require it at the token endpoint).
- Importing `parrot.auth.oauth2.device_code` still executes the package `__init__` (descriptor → navconfig); that is
  pre-existing and acceptable for the CLI. The module itself must not import navconfig.
- `CancelledError` must propagate — never catch `BaseException`/bare `except`.
- Never log `device_code`, tokens or the verifier.
- Tests: `asyncio_mode = "auto"` is set for ai-parrot. Use a tiny stub session (an object whose `post()`/`get()` return an
  async context manager with `.status` and `async json()`), or `aiohttp.test_utils.TestServer` (pytest-aiohttp is
  installed). Monkeypatch `asyncio.sleep` to an `AsyncMock` so tests do not wait.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `device_code.py` from the block below — *why*: fixes the public names TASK-4967/4968 import.
2. Complete the FILL IN markers (HTTP error mapping, outcome classification) — *why*: RFC 8628 §3.5 error codes drive the state machine.
3. Write the tests in `test_device_code_engine.py` — *why*: AC-10 requires timeout and cancellation behaviour.
4. Run the validation command and `ruff check` on both files.

### `packages/ai-parrot/src/parrot/auth/oauth2/device_code.py` (CREATE)
```python
"""Generic RFC 8628 device-authorization client engine (FEAT-774 M8). Pure: aiohttp + pydantic, no navconfig."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import aiohttp
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
WELL_KNOWN_AS_PATH = "/.well-known/oauth-authorization-server"
SLOW_DOWN_INCREMENT_S = 5
_PENDING = {"authorization_pending", "slow_down"}


class DeviceAuthorization(BaseModel):
    """RFC 8628 §3.2 device authorization response."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: Optional[str] = None
    expires_in: int
    interval: int = 5


class DeviceCodeError(RuntimeError):
    """Terminal outcome: ``code`` in {expired_token, access_denied, invalid_grant, timeout, discovery_failed, <AS error>}."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def make_pkce_pair() -> Tuple[str, str]:
    """Return ``(code_verifier, S256 code_challenge)``."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def discover_authorization_server(session: aiohttp.ClientSession, issuer: str) -> Dict[str, Any]:
    """GET ``<issuer>/.well-known/oauth-authorization-server`` and return the metadata document."""
    url = issuer.rstrip("/") + WELL_KNOWN_AS_PATH
    # FILL IN: GET url; non-200 / non-JSON / non-dict → DeviceCodeError("discovery_failed", f"... {url} ...") — bounded by AC-2
    raise NotImplementedError


async def request_device_authorization(
    session: aiohttp.ClientSession, url: str, *, client_id: str, scopes: Sequence[str],
    code_challenge: Optional[str] = None, client_secret: Optional[str] = None,
) -> DeviceAuthorization:
    """POST the device authorization request (RFC 8628 §3.1)."""
    data: Dict[str, str] = {"client_id": client_id}
    if scopes:
        data["scope"] = " ".join(scopes)
    if code_challenge:
        data.update(code_challenge=code_challenge, code_challenge_method="S256")
    if client_secret:
        data["client_secret"] = client_secret
    # FILL IN: POST form `data`; an {"error": X} body or non-200 → DeviceCodeError(X or f"http_{status}") (e.g. invalid_client
    #          names a missing `parrot-cli` client, AC-2); else DeviceAuthorization.model_validate(body)
    raise NotImplementedError


async def request_device_token(
    session: aiohttp.ClientSession, token_url: str, *, client_id: str, device_code: str,
    code_verifier: Optional[str] = None, client_secret: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """One token poll. Returns ``("approved"|"authorization_pending"|"slow_down", payload)``; terminal errors raise."""
    data = {"grant_type": DEVICE_CODE_GRANT, "device_code": device_code, "client_id": client_id}
    if code_verifier:
        data["code_verifier"] = code_verifier
    if client_secret:
        data["client_secret"] = client_secret
    # FILL IN: POST; 200 with access_token → ("approved", body); error in _PENDING → (error, body);
    #          any other error (expired_token, access_denied, invalid_grant, ...) → DeviceCodeError(error) — RFC 8628 §3.5
    raise NotImplementedError


async def poll_device_token(
    session: aiohttp.ClientSession, token_url: str, *, client_id: str, authorization: DeviceAuthorization,
    code_verifier: Optional[str] = None, timeout_s: Optional[int] = None,
    on_wait: Optional[Callable[[int], None]] = None, client_secret: Optional[str] = None,
) -> Dict[str, Any]:
    """Poll until approved. slow_down → interval += 5; deadline = min(expires_in, timeout_s) → DeviceCodeError('timeout')."""
    interval = max(1, authorization.interval)
    budget = authorization.expires_in if timeout_s is None else min(authorization.expires_in, timeout_s)
    deadline = time.monotonic() + budget
    while True:
        if time.monotonic() >= deadline:
            raise DeviceCodeError("timeout", "device authorization timed out")
        outcome, payload = await request_device_token(
            session, token_url, client_id=client_id, device_code=authorization.device_code,
            code_verifier=code_verifier, client_secret=client_secret,
        )
        if outcome == "approved":
            return payload
        if outcome == "slow_down":
            interval += SLOW_DOWN_INCREMENT_S
        if on_wait is not None:
            on_wait(interval)
        await asyncio.sleep(interval)  # CancelledError propagates by design (AC-10)
```
**Why this shape**: the spec fixes the four public functions and both models (§2 New Public Interfaces); the extra
`request_device_token` lets the server do exactly one provider poll per CLI poll (§3 M8 `complete_device_authorization`).
Do not rename anything — TASK-4967 and TASK-4968 import these names verbatim.

### `packages/ai-parrot/tests/auth/test_device_code_engine.py` (CREATE)
```python
"""RFC 8628 engine state machine (FEAT-774 M8, AC-10)."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2.device_code import (
    DeviceAuthorization, DeviceCodeError, make_pkce_pair, poll_device_token, request_device_token,
)


def _authz(**kw) -> DeviceAuthorization:
    base = dict(device_code="dc", user_code="ABCD-EFGH", verification_uri="https://as/device", expires_in=600, interval=5)
    return DeviceAuthorization(**{**base, **kw})


async def test_device_code_engine_state_machine(monkeypatch):
    # FILL IN: script request_device_token → pending, slow_down, approved; assert the returned payload and that the
    #          intervals passed to asyncio.sleep were [5, 10] (slow_down adds 5) — monkeypatch asyncio.sleep with AsyncMock
    ...


@pytest.mark.parametrize("error", ["expired_token", "access_denied"])
async def test_terminal_errors_raise(monkeypatch, error):
    # FILL IN: scripted token endpoint returns {"error": error} → DeviceCodeError with .code == error
    ...


async def test_timeout_and_cancellation(monkeypatch):
    # FILL IN: timeout_s=0 → DeviceCodeError("timeout"); a cancelled poll task raises asyncio.CancelledError
    ...


def test_pkce_pair_is_s256():
    # FILL IN: challenge == urlsafe_b64(sha256(verifier)) without padding
    ...
```

### FILL IN checklist
- [ ] `discover_authorization_server` — status/JSON handling; bounded by AC-2 (message names the URL)
- [ ] `request_device_authorization` — error body mapping to `DeviceCodeError`; bounded by AC-2
- [ ] `request_device_token` — outcome classification; bounded by RFC 8628 §3.5
- [ ] test bodies — pending/slow_down/approved, terminal errors, timeout, cancellation; bounded by AC-10

---

## Acceptance Criteria

- [ ] `device_code.py` exists with exactly the names in the blueprint; no navconfig / `parrot.conf` import
- [ ] slow_down raises the interval by 5 s; expired_token / access_denied raise `DeviceCodeError`; timeout raises `DeviceCodeError('timeout')`; cancellation propagates (AC-10)
- [ ] `make_pkce_pair()` yields an S256 challenge
- [ ] `ruff check` clean on both files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_device_code_engine.py -q`

---

## Test Specification

```python
# see packages/ai-parrot/tests/auth/test_device_code_engine.py block in the blueprint
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug connections-cli-local-mcp --feature-id FEAT-774 --spec sdd/specs/connections-cli-local-mcp.spec.md --index sdd/tasks/index/connections-cli-local-mcp.json`)
2. **Read the spec** at the path listed above for full context (§2 Overview, §3 for this module, §7 gotchas)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-cli-local-mcp.json`
4. **Verify the Codebase Contract** — before writing ANY code re-run each `grep -c` in the blueprint;
   if a count differs, fix the anchor in this file first. Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker,
   never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (plus one entry per other
   changed package, e.g. `packages/ai-parrot-server/src`) and `ruff check` the touched files
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> connections-cli-local-mcp verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
