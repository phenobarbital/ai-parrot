# TASK-5420: Concrete Navigator JWT browser-identity verifier

**Feature**: FEAT-854 — Telegram Auth Open Mode (webview | browser)
**Spec**: `sdd/specs/telegram-auth-open-mode.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5418
**Assigned-to**: unassigned

---

## Context

Spec §2 "Browser identity verification boundary" and §3 M5 item 4. The spec requires
the task decomposition to "identify the concrete deployed issuer's verification
contract; no guessed Navigator route". It was identified at `/sdd-task` time against
`../navigator-auth` (checkout) and the installed `navigator-auth 0.29.0` (byte-identical
for the files below):

- **Basic, Azure and Google all return a Navigator-signed session JWT.** Basic:
  `POST /api/v1/login` → `{"token": ..., **userdata}` (`navigator_auth/backends/basic.py:294`).
  Azure/Google: navigator-auth redirects back with `?token=<navigator JWT>`
  (`backends/azure.py:346-352`, `backends/google.py:166-167`, `backends/external.py:327-345`),
  never the provider token.
- The token is a **PyJWT** token minted by `IdentityProvider.create_token`
  (`backends/idp/__init__.py:379-436`): claims `exp, iat, iss, jti` + data; `iss` =
  `navigator_auth.conf.AUTH_TOKEN_ISSUER`; HS256 with `navigator_auth.conf.SECRET_KEY`
  (env `AUTH_SECRET_KEY`), or RS256/ES256 with a `kid` header when `OAUTH_JWT_KEYS` is set.
- `IdentityProvider.decode_token(code, issuer=None, audience=None) -> [tenant, payload]`
  (`backends/idp/__init__.py:438-505`) verifies signature + expiry (30 s leeway),
  dispatches on `kid`, splits an optional `tenant:` prefix, and checks `iss`/`aud`
  **only when passed**. Errors: `AuthExpired`, `FailedAuth`, `InvalidAuth`,
  `AuthException(status=501)` (`navigator_auth/exceptions.py`).
- Claims: basic → `user`, `username`, `user_id`, `session_id` (+ `auth_method` only if
  supplied, `basic.py:153,220-229`); Azure/Google → `user_id`, `user`, `username`,
  `email`, `id`, `session_id`, `auth_method` (= backend `_service_name`: `"azure"`,
  `"google"`; `external.py:1155`, `azure.py:94`, `google.py:59`). **No display name.**
- Verified in this venv at `/sdd-task` time: a real `create_token` → `decode_token`
  round trip works; forged signature, wrong issuer and `alg: none` are rejected; a
  token carrying `aud` (OAuth2 client/3LO tokens) **is accepted** when `audience` is
  not passed — this verifier must reject it explicitly.

This task implements `NavigatorJWTVerifier` (local signature verification through
navigator-auth's own `IdentityProvider`) and the default wiring helper used by
TASK-5423 at startup.

---

## Scope

- Create `browser_verifiers.py` with `NavigatorJWTVerifier`,
  `navigator_key_material_configured()` and `ensure_navigator_browser_verifiers(...)`.
- Create `test_browser_identity_verification.py` with **real-issuer contract tests**
  (tokens minted by `navigator_auth`'s `IdentityProvider.create_token` with a test key;
  no mock verifier).

**NOT in scope**: the wrapper verification boundary (TASK-5422), startup failure
wiring (TASK-5423), profile enrichment via `GET /api/v1/user/session` (follow-up — see
Implementation Notes), any change in `../navigator-auth`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_verifiers.py` | CREATE | `NavigatorJWTVerifier` + default wiring |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py` | CREATE | Real-issuer contract tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev @ `0083e04b62` and `.venv` navigator-auth 0.29.0 (2026-11-09).
> `navigator-auth` is a dependency of core `ai-parrot` (`packages/ai-parrot/pyproject.toml:116`),
> so it is importable from ai-parrot-integrations. **No new dependency.**

### Verified Imports
```python
from navigator_auth.backends.idp import IdentityProvider        # verified: .venv/.../navigator_auth/backends/idp/__init__.py (class, __init__ at :52)
from navigator_auth.conf import AUTH_TOKEN_ISSUER, OAUTH_JWT_KEYS  # verified: navigator_auth/conf.py:348, :903-909
from navigator_auth.exceptions import (                          # verified: navigator_auth/exceptions.py:3,26,42,47,57
    AuthException, ConfigError, InvalidAuth, FailedAuth, AuthExpired,
)
import jwt                                                       # PyJWT 2.15.1 (installed; used by navigator_auth)
from navconfig import config as navconfig_settings               # verified: telegram/auth.py:30
from navconfig.logging import logging                            # verified: telegram/auth.py:31
from parrot.integrations.telegram.browser_login import (         # created by TASK-5418
    PAGE_AUTH_METHODS, BrowserVerificationError, BrowserVerifierUnavailableError,
    VerifiedBrowserIdentity, get_browser_identity_verifier, register_browser_identity_verifier,
)
```

### Existing Signatures to Use
```python
# .venv/lib/python3.12/site-packages/navigator_auth/backends/idp/__init__.py
class IdentityProvider:
    def __init__(self):                                  # :52 — loads AUTH_USER_VIEW/AUTH_USER_MODEL classes; raises ConfigError
    def create_token(self, data: dict = None, issuer: str = None,
                     expiration: int = None, audience: str = None) -> tuple:   # :379 → (jwt, refresh, exp, scheme)
    def decode_token(self, code: str, issuer: str = None,
                     audience: Union[str, list[str], None] = None):            # :438 → [tenant, payload]
    #   module globals read at call time: SECRET_KEY, AUTH_JWT_ALGORITHM (patchable in tests:
    #   `monkeypatch.setattr("navigator_auth.backends.idp.SECRET_KEY", "<test key>")`)

# navigator_auth/conf.py
SECRET_KEY = config.get("AUTH_SECRET_KEY")   # :305 — when unset, a RANDOM per-process Fernet key (:306-308)
AUTH_JWT_ALGORITHM = config.get("JWT_ALGORITHM", fallback="HS256")   # :318
AUTH_TOKEN_ISSUER = config.get("AUTH_TOKEN_ISSUER", fallback="urn:Navigator")  # :348
OAUTH_JWT_KEYS: list                                                  # :903-909
```

### Does NOT Exist
- ~~A Navigator "verify token" HTTP endpoint at `auth_url`~~ — not assumed; this verifier is local.
- ~~`NavigatorAuthClient.validate_token` as verification~~ — it returns `bool(token)` (`telegram/auth.py:292-295`).
- ~~`AzureAuthStrategy._decode_jwt_payload` as verification~~ — base64 decode only, no signature (`telegram/auth.py:761`).
- ~~`name` / `display_name` claim in Navigator session JWTs~~ — absent; `display_name` is `None` unless a `name` claim exists.
- ~~`email` claim in basic tokens~~ — only SSO tokens carry `email`.
- ~~`IdentityProvider.verify` / `.validate_token`~~ — use `decode_token`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_verifiers.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Decided verification rules (do not relax)
1. Empty/non-string token → `BrowserVerificationError`.
2. Unverified header `alg` must be in `{"HS256","HS384","HS512","RS256","ES256"}`
   (explicit allowlist; rejects `none`) — check with `jwt.get_unverified_header` on the
   part after an optional `tenant:` prefix.
3. `decode_token(token, issuer=self._issuer or AUTH_TOKEN_ISSUER)` — always pass the issuer.
4. Reject any payload carrying `aud`: Navigator **session** tokens never carry it; OAuth2
   client/3LO tokens do (`create_token(audience='user'|'app')`), and must not log a user in.
5. `user_id` claim required (stringified).
6. Tenant binding: if the token has a `tenant:` prefix it must equal the bound tenant
   (`self._tenant_id or tenant_id`); a prefixed token for a bot without a tenant is rejected.
7. Method binding: for `azure`/`google`, claim `auth_method` must equal the method; for
   `basic`, claim `auth_method` must be absent or `"basic"`.
8. Result: `user_id=str(claims["user_id"])`, `display_name=claims.get("name") or None`,
   `email=claims.get("email") or None`. Never fall back to `username` for `display_name`
   — TASK-5422 compares a page-supplied `display_name` against this value.
9. Error mapping: `AuthExpired`, `FailedAuth`, `InvalidAuth`, `jwt` decode errors →
   `BrowserVerificationError`; `ImportError`, `ConfigError`, other `AuthException` →
   `BrowserVerifierUnavailableError`.

`decode_token` is CPU-only (no I/O), so calling it inside `async def verify` does not
block the loop.

### Key material
`navigator_key_material_configured()` is True only when `AUTH_SECRET_KEY` is set in
navconfig **or** `OAUTH_JWT_KEYS` is non-empty. Without it navigator-auth signs with a
random per-process key and verification would always fail, so
`ensure_navigator_browser_verifiers` wires nothing and reports the methods as missing
(TASK-5423 turns that into a startup error).

### Follow-up (documented, not implemented)
Revocation (`jti`) and profile fields (display name, basic-login email) are only
available from `GET /api/v1/user/session` with `Authorization: Bearer`
(`navigator_auth/auth.py:580-628`). A second adapter can add that later.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module — *why*: TASK-5422 consumes the verifier through the TASK-5418 protocol; TASK-5423 calls the wiring helper.
2. Write the contract tests with tokens minted by `IdentityProvider.create_token` — *why*: the spec forbids a mock for the verifier contract test.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_verifiers.py` (CREATE)
```python
"""Concrete browser-identity verifiers for Navigator session JWTs (FEAT-854)."""
from __future__ import annotations

from typing import Any, Iterable, List, MutableMapping, Optional

import jwt
from navconfig import config as navconfig_settings
from navconfig.logging import logging

from parrot.integrations.telegram.browser_login import (
    PAGE_AUTH_METHODS,
    BrowserVerificationError,
    BrowserVerifierUnavailableError,
    VerifiedBrowserIdentity,
    get_browser_identity_verifier,
    register_browser_identity_verifier,
)

logger = logging.getLogger(__name__)

_ALLOWED_ALGORITHMS = frozenset({"HS256", "HS384", "HS512", "RS256", "ES256"})


class NavigatorJWTVerifier:
    """Verify Navigator-issued session JWTs with navigator-auth's own IdentityProvider."""

    def __init__(self, *, issuer: Optional[str] = None, tenant_id: Optional[str] = None,
                 idp: Optional[Any] = None) -> None:
        self._issuer = issuer
        self._tenant_id = tenant_id
        self._idp = idp

    def _provider(self) -> Any:
        if self._idp is None:
            try:
                from navigator_auth.backends.idp import IdentityProvider
                self._idp = IdentityProvider()
            except Exception as exc:  # noqa: BLE001 - ImportError / ConfigError -> 503
                raise BrowserVerifierUnavailableError("Navigator identity provider unavailable") from exc
        return self._idp

    async def verify(self, token: str, *, auth_method: str, bot_id: str,
                     tenant_id: Optional[str]) -> VerifiedBrowserIdentity:
        """Return the verified identity or raise BrowserVerificationError / ...UnavailableError."""
        from navigator_auth.conf import AUTH_TOKEN_ISSUER
        from navigator_auth.exceptions import AuthException, AuthExpired, FailedAuth, InvalidAuth

        # FILL IN: rules 1-2 (empty token; header alg allowlist on the part after an optional
        # "tenant:" prefix; jwt.exceptions.DecodeError -> BrowserVerificationError).
        try:
            tenant, claims = self._provider().decode_token(token, issuer=self._issuer or AUTH_TOKEN_ISSUER)
        except (AuthExpired, FailedAuth, InvalidAuth) as exc:
            raise BrowserVerificationError("invalid Navigator token") from exc
        except AuthException as exc:
            raise BrowserVerifierUnavailableError("Navigator token verification failed") from exc
        # FILL IN: rules 4-8 — reject None claims, `aud`, missing user_id, tenant mismatch,
        # method mismatch; build VerifiedBrowserIdentity. Log rejections at warning WITHOUT the token.
        logger.debug("Verified browser identity for bot %s via %s", bot_id, auth_method)


def navigator_key_material_configured() -> bool:
    """True when the bot shares the Navigator issuer's signing material."""
    if navconfig_settings.get("AUTH_SECRET_KEY"):
        return True
    try:
        from navigator_auth.conf import OAUTH_JWT_KEYS
    except ImportError:
        return False
    return bool(OAUTH_JWT_KEYS)


def ensure_navigator_browser_verifiers(app: MutableMapping[str, Any], *, bot_id: str,
                                       methods: Iterable[str], tenant_id: Optional[str]) -> List[str]:
    """Wire a NavigatorJWTVerifier for each page method lacking a host verifier.

    Host-registered verifiers are never replaced. Returns the methods that still have
    no verifier (empty list = ready).
    """
    # FILL IN: for m in methods ∩ PAGE_AUTH_METHODS without get_browser_identity_verifier(...):
    # register NavigatorJWTVerifier(tenant_id=tenant_id) only if navigator_key_material_configured();
    # return the sorted list of methods still missing a verifier.
```
**Why**: Encodes the contract found in navigator-auth (see Context). `IdentityProvider`
is constructed lazily so a misconfigured deployment surfaces as 503 at login, while
missing key material is caught earlier, at startup, through the wiring helper.

### `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py` (CREATE)
```python
"""FEAT-854: browser identity verification — real Navigator-issuer contract tests."""
import time

import jwt
import pytest

from parrot.integrations.telegram.browser_login import (
    BrowserVerificationError, BrowserVerifierUnavailableError, get_browser_identity_verifier,
)
from parrot.integrations.telegram.browser_verifiers import (
    NavigatorJWTVerifier, ensure_navigator_browser_verifiers,
)

TEST_KEY = "feat-854-contract-test-key-0123456789abcdef"


@pytest.fixture
def issuer(monkeypatch):
    """Real navigator-auth IdentityProvider signing with a known test key."""
    monkeypatch.setattr("navigator_auth.backends.idp.SECRET_KEY", TEST_KEY)
    from navigator_auth.backends.idp import IdentityProvider
    return IdentityProvider()


def _mint(idp, **claims) -> str:
    token, _refresh, _exp, _scheme = idp.create_token(data={"session_id": "s-1", **claims})
    return token


async def test_browser_mode_real_verifier_contract(issuer):
    """Issuer-produced basic and SSO tokens verify to authoritative identity."""
    verifier = NavigatorJWTVerifier(idp=issuer)
    ident = await verifier.verify(_mint(issuer, user_id=42, username="alice"),
                                  auth_method="basic", bot_id="7001", tenant_id=None)
    assert ident.user_id == "42" and ident.display_name is None and ident.email is None
    # FILL IN: azure token (auth_method="azure", email=...) verifies with email set.


async def test_browser_sso_rejects_invalid_tokens(issuer):
    # FILL IN: each raises BrowserVerificationError —
    #  forged key (jwt.encode with another key), alg none, tampered payload segment,
    #  expired (jwt.encode with TEST_KEY and exp=time.time()-120, iss=AUTH_TOKEN_ISSUER),
    #  wrong issuer (create_token(issuer="urn:Other")), aud-bearing (create_token(audience="app")),
    #  missing user_id, wrong tenant ("other:" + token with tenant_id="acme"),
    #  method mismatch (auth_method="google" claim verified as "azure"; "azure" claim as "basic"),
    #  empty token.


async def test_browser_verifier_unavailable_maps_to_503():
    # FILL IN: an idp double whose decode_token raises AuthException(status=501) -> BrowserVerifierUnavailableError


def test_ensure_verifiers_respects_host_and_key_material(monkeypatch):
    # FILL IN: host-registered verifier is kept; with AUTH_SECRET_KEY absent (monkeypatch
    # navigator_key_material_configured -> False) the helper returns the missing methods;
    # with it present, every page method gets a NavigatorJWTVerifier; "oauth2" is ignored.
```

### FILL IN checklist
- [ ] `NavigatorJWTVerifier.verify` — rules 1-8; bounded by spec §2 (signature, alg allowlist, expiry, issuer, audience, tenant)
- [ ] `ensure_navigator_browser_verifiers` — host wiring wins; no key material → reported missing
- [ ] Contract tests — real `IdentityProvider` tokens only; no mock verifier

---

## Acceptance Criteria

- [ ] Issuer-produced tokens verify; forged, `alg:none`, tampered, expired, wrong-issuer, `aud`-bearing, wrong-tenant and wrong-method tokens raise `BrowserVerificationError`.
- [ ] Provider/config failures raise `BrowserVerifierUnavailableError`.
- [ ] Identity comes only from verified claims; no token is logged.
- [ ] No new dependency; `ruff check` clean.
- [ ] Completion Note records the contract-test run (no skips).

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py -q`

---

## Test Specification

See the test block above (spec §4 rows `test_browser_mode_real_verifier_contract`,
`test_browser_sso_rejects_invalid_tokens`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug telegram-auth-open-mode --feature-id FEAT-854`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/telegram-auth-open-mode.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5420 telegram-auth-open-mode verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-sol (codex), attempt 1, 268s
**Date**: 2026-11-09
**Notes**: Created browser_verifiers.py (NavigatorJWTVerifier + default wiring) and real-issuer contract tests. Merge-tier validation green (50 passed, 4 skipped, chunk 1). File list matches the task; no review fixes.

**Deviations from spec**: none
