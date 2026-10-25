# TASK-4660: TokenExchangeClient — the first caller of TokenExchangeAuth

**Feature**: FEAT-729 — MS Teams user authentication lane
**Spec**: `sdd/specs/msteams-user-auth-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 2**. This is the piece the proof of concept already
proved end to end: `POST /api/v1/login` with `X-Auth-Method: TokenExchangeAuth`
returned `HTTP 200` and a live Navigator session whose `provider_user_id` equals
the Entra `oid` that Teams activities carry. The recorded run is at
`sdd/state/FEAT-729/poc/exchange_run.transcript.md` — **read it before
implementing**; it is the reference for both the request shape and the failure
modes.

The client lives in **core** (`parrot/auth/`), not in the Teams package, because
it is channel-agnostic: Telegram and Slack can adopt it later. The spec's §6
confirms there is currently **no caller of `TokenExchangeAuth` anywhere in
`packages/`** — this task writes the first one.

---

## Scope

- Implement `TokenExchangeClient` in a new `parrot/auth/token_exchange.py`.
- Send the exact request the PoC proved: `X-Auth-Method: TokenExchangeAuth` plus
  the body keys `provider`, `token`, `token_type` and, when available, `id_token`.
- Map failures to **distinguishable reasons** rather than one generic error —
  the PoC met three of them for real.
- Honour `NAVIGATOR_SSL_VERIFY` the way `NavigatorAuthClient` does.
- Write unit tests that stub the `aiohttp` boundary; no live credential.

**NOT in scope**: acquiring the Azure token (TASK-4661); session storage
(TASK-4659); any Teams-specific code — nothing in this module may import from
`parrot.integrations`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/token_exchange.py` | CREATE | `TokenExchangeClient`, `ExchangeResult` |
| `packages/ai-parrot/tests/unit/test_token_exchange_client.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp                                               # installed
from navconfig import config as navconfig_settings           # pattern: packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py:240
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py:227 — the client pattern to mirror, including SSL handling
class NavigatorAuthClient:
    def __init__(self, auth_url: str, timeout: int = 15) -> None:   # line 237
        # reads NAVIGATOR_SSL_VERIFY; self._ssl = None (verify) or False (skip)
    async def login(self, username: str, password: str) -> Optional[Dict]:  # line 249
        # headers: {"Content-Type": "application/json", "x-auth-method": "BasicAuth"}
        # returns the parsed JSON on 200, None otherwise; catches aiohttp.ClientError

# .venv navigator_auth 0.28.8 — the server side this client talks to
class TokenExchangeAuth(BasicAuth):          # navigator_auth/backends/exchange.py:31
@dataclass
class ExchangeRequest:                       # navigator_auth/backends/exchange.py:22
    provider: str
    token: str
    token_type: str = "Bearer"
    id_token: Optional[str] = None
```

### Does NOT Exist
- ~~any caller of `TokenExchangeAuth` in `packages/`~~ — 0 hits. This is the first.
- ~~`X-Auth-Method: TokenExchange…` sent anywhere in `packages/`~~ — 0 hits.
- ~~`NavigatorAuthClient.exchange` / `.exchange_token`~~ — it has `login` and
  `validate_token` only. Do not extend it; write the new client.
- ~~a `requests`/`httpx` HTTP helper in core~~ — `aiohttp` only, enforced by TID251.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/token_exchange.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_token_exchange_client.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#NavigatorAuthClient"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `aiohttp` only. Never `requests`/`httpx` (TID251 is the merge gate).
- **Never log the token**, not even truncated — the PoC redacts to
  `<redacted len=N>`; do the same, and apply it to `id_token` too.
- The reason strings are part of the contract: TASK-4662's `/login` reply text
  and TASK-4663's gate both branch on them. Do not rename them.

### Why the reasons matter
The PoC hit three of these for real against a live deployment:

| Observed | Reason to return |
|---|---|
| `401 {"reason": "Unacceptable Auth Method: TokenExchangeAuth"}` | `backend_not_loaded` |
| 401 after Graph `/me` rejected the token | `invalid_token` |
| token `exp` already past | `expired` |
| 401 because no `auth.users` row matched | `user_not_found` |

`backend_not_loaded` is an **operator** error, not a user error: it means
`AUTHENTICATION_BACKENDS` lacks `navigator_auth.backends.exchange.TokenExchangeAuth`
(spec §7, Ops prerequisite 1). `user_not_found` is the most likely production
failure — the exchange never provisions users.

---

## Implementation Blueprint

### Steps (in order)
1. Write `ExchangeResult` first — *why*: both the client and its two consumers
   branch on its `reason`, so the shape must exist before the logic.
2. Copy the SSL block from `NavigatorAuthClient.__init__` verbatim — *why*: this
   deployment uses self-signed certs and the behaviour must match the existing client.
3. Build the body with `id_token` **omitted when None**, not sent as null —
   *why*: `ExchangeRequest.id_token` defaults to None server-side and a null
   would be sent as a provided value.
4. Classify the 401s by body text before falling back to `invalid_token` —
   *why*: AC-3/AC-4 assert the distinction, and a generic failure sends an
   operator chasing a user problem.

### `packages/ai-parrot/src/parrot/auth/token_exchange.py` (CREATE)
```python
"""Exchange an external provider token for a Navigator session."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import aiohttp
from navconfig import config as navconfig_settings

logger = logging.getLogger(__name__)

#: Returned in ExchangeResult.reason. TASK-4662 and TASK-4663 branch on these.
REASON_OK = "ok"
REASON_USER_NOT_FOUND = "user_not_found"
REASON_BACKEND_NOT_LOADED = "backend_not_loaded"
REASON_INVALID_TOKEN = "invalid_token"
REASON_EXPIRED = "expired"
REASON_TRANSPORT = "transport_error"


@dataclass
class ExchangeResult:
    """Outcome of one exchange attempt."""

    ok: bool
    reason: str = REASON_OK
    nav_user_id: Optional[str] = None
    session_token: Optional[str] = None
    email: Optional[str] = None
    display_name: Optional[str] = None
    provider_user_id: Optional[str] = None
    expires_at: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


class TokenExchangeClient:
    """POSTs an external token to Navigator's TokenExchangeAuth backend.

    Proven end to end in sdd/state/FEAT-729/poc/exchange_run.transcript.md.
    """

    def __init__(self, auth_url: str, timeout: int = 15,
                 prefer_id_token: bool = True) -> None:
        self.auth_url = auth_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.prefer_id_token = prefer_id_token
        raw = navconfig_settings.get("NAVIGATOR_SSL_VERIFY", fallback="true")
        if isinstance(raw, bool):
            ssl_verify = raw
        else:
            ssl_verify = str(raw).lower() not in ("false", "0", "no")
        self._ssl: Optional[bool] = None if ssl_verify else False

    async def exchange(self, token: str, *, provider: str = "azure",
                       id_token: Optional[str] = None,
                       token_type: str = "Bearer") -> ExchangeResult:
        """Exchange an external token for a Navigator session.

        Never raises: transport problems come back as
        ``ExchangeResult(ok=False, reason="transport_error")``.
        """
        payload: Dict[str, Any] = {
            "provider": provider,
            "token": token,
            "token_type": token_type,
        }
        if id_token and self.prefer_id_token:
            payload["id_token"] = id_token
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Method": "TokenExchangeAuth",
        }
        # FILL IN: POST to self.auth_url with ssl=self._ssl; on 200 map the body
        # through _result_from_body; on any other status return
        # _classify_failure(status, body_text). Catch aiohttp.ClientError ->
        # REASON_TRANSPORT. Log the status and the reason, NEVER the token.
        # Bounded by AC-1..AC-5.
        raise NotImplementedError

    @staticmethod
    def _classify_failure(status: int, body: str) -> ExchangeResult:
        """Map an error response to a distinguishable reason."""
        # FILL IN: "unacceptable auth method" (case-insensitive) in body ->
        # REASON_BACKEND_NOT_LOADED; "user_not_found"/"not found" ->
        # REASON_USER_NOT_FOUND; "expired" -> REASON_EXPIRED; else
        # REASON_INVALID_TOKEN. Bounded by AC-3, AC-4.
        raise NotImplementedError

    @staticmethod
    def _result_from_body(body: Dict[str, Any]) -> ExchangeResult:
        """Build a success result from the login response."""
        # FILL IN: read user_id / token / email / provider_user_id out of the
        # 200 body. Its real shape is in the PoC transcript — match THAT, not a
        # guess. Bounded by AC-1, AC-2.
        raise NotImplementedError
```
**Why this shape**: `exchange()` never raising is what lets TASK-4663 fail
*open* when `auth_required=False` without wrapping every call in try/except. The
reason constants are module-level because two other tasks import them. The SSL
block is copied, not reinvented, so the two clients cannot drift.

### FILL IN checklist
- [ ] `TokenExchangeClient.exchange` — the POST and its dispatch; bounded by AC-1..AC-5
- [ ] `TokenExchangeClient._classify_failure` — the four-way 401 split; bounded by AC-3, AC-4
- [ ] `TokenExchangeClient._result_from_body` — field mapping from the PoC's real 200 body; bounded by AC-2

---

## Acceptance Criteria

- [ ] AC-1 the POST carries `X-Auth-Method: TokenExchangeAuth` and the body keys
      `provider`, `token`, `token_type`
- [ ] AC-2 a 200 yields `ok=True` with `nav_user_id`, `session_token`, `email`
      and `provider_user_id` populated from the body
- [ ] AC-3 a 401 whose body says *Unacceptable Auth Method* yields
      `reason="backend_not_loaded"` — **not** `invalid_token`
- [ ] AC-4 a 401 for a user absent from `auth.users` yields
      `reason="user_not_found"`
- [ ] AC-5 with `prefer_id_token=True` and an `id_token` given, `id_token` is in
      the body; with it None the key is **absent**, not null
- [ ] AC-6 `aiohttp.ClientError` yields `ok=False, reason="transport_error"` and
      no exception escapes
- [ ] No token value appears in any log record (assert on `caplog`)
- [ ] `ruff check` clean; no `requests`/`httpx`
- [ ] `pytest packages/ai-parrot/tests/unit/test_token_exchange_client.py -q` passes

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_token_exchange_client.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_token_exchange_client.py
import pytest

from parrot.auth.token_exchange import (
    REASON_BACKEND_NOT_LOADED, REASON_USER_NOT_FOUND,
    ExchangeResult, TokenExchangeClient,
)


class TestExchangeRequest:
    async def test_sends_token_exchange_header(self):
        """The POST carries X-Auth-Method: TokenExchangeAuth."""
        # FILL IN: stub aiohttp at the ClientSession boundary; assert the header

    async def test_omits_id_token_when_absent(self):
        """id_token is absent from the body, not null."""
        # FILL IN


class TestFailureClassification:
    def test_unacceptable_auth_method_maps_to_backend_not_loaded(self):
        """The live-deployment failure is an operator error, not a bad token."""
        # FILL IN: body text from the PoC transcript

    def test_missing_user_maps_to_user_not_found(self):
        """The exchange never provisions, so this is its own reason."""
        # FILL IN

    async def test_never_logs_the_token(self, caplog):
        """No log record contains the token value."""
        # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug msteams-user-auth-lane --feature-id FEAT-729`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/msteams-user-auth-lane.json`
4. **Verify the Codebase Contract** before writing ANY code. Re-grep every
   anchor: this task was written on `dev @ 0eb59926a` and the spec's §6 was
   verified on `37dc1da44`, so two anchors had already drifted once (see
   Context where noted). If anything moved, fix the contract FIRST.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every
   `# FILL IN:` marker, never change a signature or path it fixes
7. **Verify** the Acceptance Criteria — run the Validation Commands with
   `PYTHONPATH` set per changed package (the shared `.venv` is editable-installed
   against the MAIN checkout, so a bare `pytest` in a worktree imports the wrong
   branch)
8. **Commit the code** — stage only the files this task lists (never `git add .`)
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4660 msteams-user-auth-lane verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed**: TokenExchangeClient/ExchangeResult in auth/token_exchange.py; merge-tier validation 41 passed; reviewed against AC-1..6, no corrections.
Seat: gpt-5.6-sol · Backend: codex · Attempts: 1 · Duration: 234s
**Deviations from scope**: none
**Ambiguities found in the spec**: none
**Follow-up needed**: Minor: _classify_failure treats any body containing 'not found' as user_not_found; consider tightening if Navigator wording changes.
