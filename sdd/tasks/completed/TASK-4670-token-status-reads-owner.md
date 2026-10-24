# TASK-4670: The integrations badge reads the owner, not the write-once vault copy

**Feature**: FEAT-735 — One owner for the Jira credential
**Spec**: `sdd/specs/services-vault-token-sync-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4668
**Assigned-to**: unassigned
**Discovered-from**: `issue:2e85cce93cab`

---

## Context

Implements **spec §3 Module 2**. `IntegrationsService._token_status`
(`service.py:173`) decides the integrations UI badge — `connected` vs
`needs_reconnect` — from `VaultTokenSync.read_tokens_result`
(`service.py:190`), i.e. from the **Session Vault**: the one copy of the Jira
credential that is written once at link time and that **no refresh ever
updates**.

So the badge is computed from the stalest copy in the system. A user whose
grant was revoked upstream can still read "connected", and a user whose token
merely rotated is judged on evidence that is out of date by construction.
Q1 (spec §8) named the Identity Vault the owner; this task moves the probe
onto it.

### Jira only — this method is generic

`_token_status` takes `provider_id` and serves **every** OAuth2 provider in the
integrations list (fireflies, workiq, entra, o365 …). Only the **Jira**
credential has an owner in `auth.user_identities`; for every other provider the
Session Vault is still the only store there is. Switching the whole method to
the Identity Vault would break those providers' badges.

The probe therefore branches on the provider: identity-backed for the one the
Identity Vault owns, `read_tokens_result` for the rest. Keep the branch
explicit and data-driven (a module-level frozenset), not a string literal
buried in an `if`.

---

## Scope

- Add an `IdentityStore` accessor to `IntegrationsService`, mirroring the existing
  lazy, guarded `_vault_sync` (`service.py:151`).
- Branch `_token_status` on the provider: the owner for Jira, the vault for
  everyone else.
- Preserve the method's contract exactly: the `connected` / `needs_reconnect`
  vocabulary, and **fail-open** on any probe error.
- Map `IdentityCredentialError` to `needs_reconnect` — it is the owner's
  equivalent of the vault's `unreadable`.

### NOT in scope

- Any write path (TASK-4668 / TASK-4669) or the removal of any writer
  (TASK-4671).
- Changing what the UI does with the two status strings.
- Moving any other provider off `VaultTokenSync`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | `_identity_store` accessor + the provider branch in `_token_status` |
| `packages/ai-parrot/tests/unit/test_oauth2_service_token_status.py` | CREATE | Status matrix for both branches |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `52f1ccd2e`, 2026-10-23.

### Verified Imports

```python
from navigator_auth.identity.store import IdentityStore, IdentityCredentialError  # store.py:151, :44
from navigator_auth.identity.types import TokenResponse                            # identity/types.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/oauth2/service.py
class IntegrationsService:
    def _vault_sync(self, request: Any) -> Any:                      # line 151
        # the pattern to copy: returns a cached instance, else builds one from
        # app.get("authdb"); returns None when the app or the pool is missing,
        # and swallows ImportError when the server package is not installed.
    async def _token_status(self, user_id: str, provider_id: str,
                            request: Any) -> str:                    # line 173 — THE EDIT SITE
        sync = self._vault_sync(request)                             # line 186
        if sync is None:
            return "connected"                                       # fail-open #1
        try:
            result = await sync.read_tokens_result(user_id, provider_id)   # line 190
        except Exception:                                            # fail-open #2
            logger.warning(...); return "connected"
        if result.status in ("missing", "unreadable"):               # line 198
            logger.info(...); return "needs_reconnect"
        return "connected"

# module-level logger, already imported in this file
logger = logging.getLogger(__name__)

# navigator-auth 0.28.8 — verified by introspection on the installed package
class IdentityStore:                                                 # store.py:151
    def __init__(self, db_pool: Any, cipher: Optional[IdentityCipher] = None)   # :153
    async def get_by_provider(self, user_id: Any, provider: str) -> Optional[UserIdentity]
    def decrypt_credential(self, identity) -> TokenResponse          # :444 — SYNCHRONOUS
```

### Edit Sites

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `service.py` | MODIFY | `    async def _token_status(self, user_id: str, provider_id: str, request: Any) -> str:` | `service.py:173` | 1 (`grep -c`, 2026-10-23) |
| `service.py` | MODIFY | `            result = await sync.read_tokens_result(user_id, provider_id)` | `service.py:190` | 1 (`grep -c`, 2026-10-23) |

### Does NOT Exist

- ~~a class named `OAuth2Service`~~ — the class in this module is
  **`IntegrationsService`** (`service.py:73`). The spec's §6 said `OAuth2Service`;
  the method anchor was correct, the class name was not.
- ~~a test file for it~~ — `grep -rln "_token_status\|IntegrationsService"
  packages/*/tests/` returns nothing, 2026-10-23. This task creates the first
  one; there is no existing fixture to reuse.
- ~~`await store.decrypt_credential(...)`~~ — **synchronous** (`store.py:444`).
  Awaiting it raises `TypeError`.
- ~~`IdentityStore.get_identity` / `read_tokens` / `token_status`~~ — the read
  API used here is `get_by_provider` + `decrypt_credential`.
- ~~a third status string~~ — the method returns exactly `"connected"` or
  `"needs_reconnect"`; the UI switches on those two and nothing else.
- ~~`VaultTokenSync` becoming unused by this file~~ — every non-Jira provider
  still probes it. Do not delete `_vault_sync`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_oauth2_service_token_status.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService"
  ]
}
```

---

## Implementation Notes

- **Fail-open is a feature, not an oversight.** Both existing `return
  "connected"` escapes stay: a store outage must never hide a working
  integration behind a re-connect prompt. The only error that means
  `needs_reconnect` is one that proves the credential is unusable —
  `IdentityCredentialError`, or no row at all.
- The accessor caches like `_vault_sync` does (one instance per service), and
  returns `None` when `request.app` or `app["authdb"]` is missing, so tests and
  non-HTTP contexts degrade to fail-open instead of raising.
- `ai-parrot` may import `navigator_auth` directly — it already does elsewhere
  in `parrot/auth/`. The import-direction rule that constrains TASK-4668 is
  about `parrot.services.*` (the server distribution), which is not used here.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/auth/oauth2/service.py` (MODIFY)

```python
# BEFORE — insert above `    async def _token_status(self, user_id: str, provider_id: str, request: Any) -> str:`
# (verified: packages/ai-parrot/src/parrot/auth/oauth2/service.py:173)
# occurrences: 1 (verified: grep -c, 2026-10-23)

#: Providers whose durable credential lives in the Identity Vault (FEAT-735 Q1).
#: Every other provider is still served by the Session Vault.
_IDENTITY_OWNED_PROVIDERS = frozenset({"jira"})


    def _identity_store(self, request: Any) -> Any:
        """One ``IdentityStore`` per service, or ``None`` when unavailable.

        Mirrors :meth:`_vault_sync`: lazily built from ``app['authdb']``,
        cached, and ``None`` whenever the app or the pool is missing so the
        caller can fail open.
        """
        # FILL IN: copy the shape of _vault_sync (service.py:151) — cached
        # attribute, getattr(request, "app", None), guarded import of
        # navigator_auth.identity.store, app.get("authdb") or None.
        # Bounded by AC-4.
```

```python
# AFTER — replace the body line `            result = await sync.read_tokens_result(user_id, provider_id)`
# (verified: packages/ai-parrot/src/parrot/auth/oauth2/service.py:190)
# occurrences: 1 (verified: grep -c, 2026-10-23)

# FILL IN: branch at the TOP of _token_status, before `sync = self._vault_sync(request)`:
#   if provider_id in _IDENTITY_OWNED_PROVIDERS:
#       return await self._identity_token_status(user_id, provider_id, request)
# and leave the existing vault body untouched below it. Bounded by AC-1, AC-5.


    async def _identity_token_status(self, user_id: str, provider_id: str,
                                     request: Any) -> str:
        """``connected`` | ``needs_reconnect`` from the Identity Vault.

        Same contract as :meth:`_token_status`: any probe failure returns
        ``connected`` so a store outage never hides a working integration.
        """
        # FILL IN — bounded by AC-1, AC-2, AC-3, AC-4:
        #   store = self._identity_store(request)
        #   if store is None: return "connected"                  # fail open
        #   try:
        #       identity = await store.get_by_provider(user_id, provider_id)
        #       if identity is None:
        #           logger.info(...); return "needs_reconnect"    # never linked / row gone
        #       store.decrypt_credential(identity)                # SYNC — do not await
        #   except IdentityCredentialError:
        #       logger.info(...); return "needs_reconnect"        # the vault's "unreadable"
        #   except Exception:
        #       logger.warning(...); return "connected"           # fail open
        #   return "connected"
```

**Why**: the branch goes at the top rather than inside the vault read, so the
non-Jira path keeps its exact current code — no behaviour change for providers
this feature does not own, and the diff stays reviewable.

### `packages/ai-parrot/tests/unit/test_oauth2_service_token_status.py` (CREATE)

```python
"""Unit tests for IntegrationsService._token_status (FEAT-735 / TASK-4670)."""
# FILL IN: a fake request exposing .app as a dict, a fake IdentityStore and a
# fake VaultTokenSync, injected via the service's cached attributes so no
# Postgres is needed. One test per Acceptance Criterion below.
```

### Steps (in order)

1. Add `_IDENTITY_OWNED_PROVIDERS` and `_identity_store` — nothing calls them
   yet, so the file still behaves exactly as today.
2. Add `_identity_token_status` with its three exits.
3. Add the one-line branch at the top of `_token_status`; the vault body below
   is untouched.
4. Write the test matrix and run it.

### FILL IN checklist

- [ ] `_identity_store` accessor, caching and `None`-guarded; AC-4
- [ ] `_identity_token_status` with both fail-open exits; AC-2, AC-3
- [ ] the provider branch at the top of `_token_status`; AC-1, AC-5
- [ ] the five tests; all ACs

---

## Acceptance Criteria

- [ ] AC-1 For `jira`, the status comes from the Identity Vault — the Session
      Vault is **not** read
- [ ] AC-2 A sealed, openable identity row ⇒ `connected`
- [ ] AC-3 `IdentityCredentialError`, or no identity row, ⇒ `needs_reconnect`
- [ ] AC-4 Any other failure — no app, no pool, store raising — ⇒ `connected`
      (fail-open preserved)
- [ ] AC-5 For a non-Jira provider the behaviour is **unchanged**: the vault is
      read exactly as before and the Identity Vault is not touched
- [ ] AC-6 The method still returns only `"connected"` or `"needs_reconnect"`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_oauth2_service_token_status.py -q`

---

## Test Specification

| Test | Description |
|---|---|
| `test_status_connected_from_owner` | Jira + openable row ⇒ `connected`; the vault sync is never called |
| `test_status_needs_reconnect_on_credential_error` | `decrypt_credential` raises `IdentityCredentialError` ⇒ `needs_reconnect` |
| `test_status_needs_reconnect_without_row` | `get_by_provider` returns `None` ⇒ `needs_reconnect` |
| `test_status_fails_open` | Store raises / no `authdb` ⇒ `connected` |
| `test_non_jira_provider_still_uses_vault` | `fireflies` ⇒ `read_tokens_result` is called, the identity store is not |

---

## Agent Instructions

Do not touch `_vault_sync` or the existing vault body — other providers depend
on both. `decrypt_credential` is synchronous; awaiting it is the exact mistake
TASK-4664 made. Touch no file outside the two listed.

---

## Completion Note

**Completed 2026-10-23** (verification: verified).

`IntegrationsService` gained `_identity_store` (lazy, cached, `None`-guarded,
mirroring `_vault_sync`) and `_identity_token_status`; `_token_status` now
branches on `_IDENTITY_OWNED_PROVIDERS` at its first line and leaves the
existing vault body untouched below it.

**Contract error found and corrected** — the spec's §6 and this task both
named the class **`OAuth2Service`**. There is no such class: it is
**`IntegrationsService`** (`service.py:73`). The method anchor
(`async def _token_status(...)`) was correct and unique, so the edits landed
in the right place, but the first test run failed at import. Both the spec
and this task's contract were corrected in the closing commit. This is the
second stale name in the spec's contract (the first was
`test_jira_oauth.py`), which is worth remembering when the remaining task
cites §6.

**Evidence**: `pytest test_oauth2_service_token_status.py -q` → 7 passed
(new file); with the two sink suites → 60 passed; `ruff check` clean (the
pre-existing `F401 JiraTokenSet` under `TYPE_CHECKING` in `service.py` is
untouched and predates this task — verified against `HEAD`).

**Second failure worth recording**: `IdentityCredentialError` takes
`(provider, field, reason)`, not a single message. Constructing it with one
argument raises `TypeError` — the test, not the implementation, had it wrong.

Non-Jira providers are proven unaffected by two tests that assert the vault
is read and the identity store is not.
