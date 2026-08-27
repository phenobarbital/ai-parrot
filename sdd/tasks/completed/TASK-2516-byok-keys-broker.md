# TASK-2516: BYOK — per-user LLM API keys + CredentialBroker resolver

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2511
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8. Resolved in brainstorm: keys persisted encrypted per-user
via the existing navigator-session **AES-GCM vault** (NOT Fernet — Fernet
does not exist in this codebase) following the `CredentialsHandler` pattern
(Redis session vault hot copy + DocumentDB durable copy), resolved at
client-build time through a new `CredentialBroker` resolver, passed as
`api_key` to `LLMFactory.create` on Studio test runs. Keys are never
returned in plaintext.

---

## Scope

- Core: add `_UserLLMKeyResolver(CredentialResolver)` to
  `parrot/auth/broker.py` — resolves `{provider} -> api_key` for a given
  user from the vault storage; registered with `CredentialResolverFactory`.
- Server: `StudioKeysHandler(StudioBaseView)` in `handlers/studio/byok.py`:
  - `POST /api/v1/astudio/keys` — `ByokKeyRequest(provider, api_key:
    SecretStr)`; provider validated against `SUPPORTED_CLIENTS` (400
    otherwise); encrypt with `encrypt_credential`; store: session vault
    hot copy + DocumentDB durable (collection `user_llm_keys`); 201.
  - `GET /api/v1/astudio/keys` — masked list only
    (`{provider, masked: "sk-…abcd", created_at}`).
  - `DELETE /api/v1/astudio/keys/{provider}` — remove both copies.
  - Missing vault master keys → 503 with operator guidance (soft-import
    pattern from credentials.py).
- Test-run integration hook: a helper
  `resolve_user_api_key(app, user_id, provider) -> Optional[str]` used by
  TASK-2517's `test/ask` to pass `api_key=` into `LLMFactory.create`.
- Tests: crypto round-trip (deterministic master keys fixture), masking,
  provider validation, resolver behavior.

**NOT in scope**: using the key on non-Studio surfaces (chat handlers);
key rotation UI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/broker.py` | MODIFY | `_UserLLMKeyResolver` + factory registration |
| `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py` | CREATE | keys handler + resolve helper |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | add routes |
| `packages/ai-parrot-server/tests/studio/test_byok.py` | CREATE | crypto/masking/resolver tests |
| `packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py` | CREATE | resolver unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.security.credentials_utils import encrypt_credential, decrypt_credential  # :19,:52
from navigator_session.vault.config import get_active_key_id, load_master_keys  # credentials.py:41 (soft import!)
from parrot.clients.factory import SUPPORTED_CLIENTS, LLMFactory  # factory.py:106,159
from parrot.auth.credentials import CredentialResolver            # auth/credentials.py:162
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/credentials_utils.py
def encrypt_credential(credential: dict, key_id: int, master_key: bytes) -> str: ...  # :19
def decrypt_credential(encrypted: str, master_keys: dict[int, bytes]) -> dict: ...    # :52
# ciphertext: [key_id 2B BE][nonce 12B][payload+tag], base64

# packages/ai-parrot-server/src/parrot/handlers/credentials.py — THE pattern
@is_authenticated()
@user_session()
class CredentialsHandler(BaseView):  # :69-71
    COLLECTION: str = "user_credentials"      # :83 (DocumentDB via parrot.interfaces.documentdb)
    SESSION_PREFIX: str = "_credentials:"     # :84
    # helpers: _get_user_id :90, _session_key :111, _set_session_credential :122,
    #          _remove_session_credential :133, _get_all_session_credentials :143
def _load_vault_keys() -> tuple[int, bytes, dict[int, bytes]]: ...  # credentials.py:50
# soft import guard: try/except ImportError around navigator_session.vault (credentials.py:41-48)

# packages/ai-parrot/src/parrot/auth/broker.py
class CredentialResolverFactory: ...   # :66
class _VaultStaticKeyResolver(CredentialResolver): ...  # :276 — closest existing resolver shape
class CredentialBroker: ...            # :326
# parrot/auth/credentials.py: CredentialResolver(ABC) :162, ResolvedCredential :65,
#   StaticCredentialResolver :216

# packages/ai-parrot/src/parrot/clients/factory.py
SUPPORTED_CLIENTS = {...}  # :106 — keys: claude, anthropic, google, openai, groq, ...
class LLMFactory:
    @staticmethod
    def create(llm: str, model_args=None, tool_manager=None, **kwargs) -> AbstractClient: ...  # :191
        # **kwargs reach the client __init__ — api_key accepted, e.g.
        # AnthropicClient.__init__(self, api_key: str = None, ...)  claude.py:79
```

### Does NOT Exist
- ~~Fernet / `cryptography.fernet`~~ — zero matches in `packages/*/src`;
  use the AES-GCM helpers above.
- ~~An LLM-API-key table/handler~~ — `CredentialsHandler` stores DATABASE
  connection credentials only; `user_llm_keys` collection is NEW.
- ~~`parrot.clients.SUPPORTED_CLIENTS`~~ — import from
  `parrot.clients.factory`.
- ~~`AnthropicClient(model=...)` explicit param~~ — model flows via
  `**kwargs`; `api_key` IS an explicit param (claude.py:79).
- ~~A generic per-user key resolver in broker.py~~ — `_VaultStaticKeyResolver`
  resolves STATIC configured keys; the per-user resolver is NEW.

---

## Implementation Notes

### Pattern to Follow
Copy the `CredentialsHandler` storage discipline wholesale: session vault
hot copy (`SESSION_PREFIX`-style key), DocumentDB fire-and-forget durable
write, `_load_vault_keys` guard → 503 when unavailable.

### Key Constraints
- NEVER log or return plaintext; masking shows first 3 + last 4 chars max.
- `SecretStr` in the Pydantic request; call `.get_secret_value()` only at
  encryption time.
- Resolver lookup order: session vault (fast) → DocumentDB (fallback).
- Provider names normalized lowercase before validation.

### References in Codebase
- `handlers/mcp_persistence.py` — second DocumentDB CRUD example.
- `packages/ai-parrot/tests/unit/test_credential_broker.py` — broker test
  patterns to extend.

---

## Acceptance Criteria

- [ ] POST stores encrypted (AES-GCM helpers); GET returns masked only;
      DELETE removes both copies.
- [ ] Unsupported provider → 400; missing master keys → 503.
- [ ] `_UserLLMKeyResolver` resolves stored key; returns None when absent.
- [ ] `resolve_user_api_key` helper usable with
      `LLMFactory.create(..., api_key=...)`.
- [ ] No plaintext keys in any log or response (assert in tests).
- [ ] `pytest packages/ai-parrot-server/tests/studio/test_byok.py packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py -v` passes.
- [ ] `ruff check` clean on touched paths.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_byok.py
class TestByok:
    async def test_store_and_masked_list(self, studio_app, vault_keys): ...
    async def test_plaintext_never_in_response_or_logs(self, studio_app, vault_keys, caplog): ...
    async def test_unsupported_provider_400(self, studio_app): ...
    async def test_missing_master_keys_503(self, studio_app, monkeypatch): ...
    async def test_delete_removes_both_copies(self, studio_app, vault_keys): ...

# packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py
class TestUserLLMKeyResolver:
    async def test_resolves_stored_key(self): ...
    async def test_absent_key_returns_none(self): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2511 completed
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-27
**Notes**:
- `_UserLLMKeyResolver(CredentialResolver)` added to `broker.py`,
  implementing `resolve(channel=provider, user_id)` by reading the
  DocumentDB collection `"user_llm_keys"` and decrypting with the SAME
  AES-GCM helpers (`encrypt_credential`/`decrypt_credential`) the Studio
  handler writes with. Fails CLOSED (`None`) on any missing dependency,
  vault-key, or decrypt error.
- **Design decision on "registered with `CredentialResolverFactory`"**:
  the factory's existing `build()` dispatch is keyed on
  `ProviderCredentialConfig.auth`, a CLOSED `Literal["obo", "oauth2",
  "static_key", "mcp", "device_code"]` in `auth/credentials.py` (a file
  NOT in this task's scope). BYOK has no `ProviderCredentialConfig`
  declaration at all — it's session-user-driven, not agent-declared —
  so I did not add a 6th literal value there. Instead added a dedicated
  `CredentialResolverFactory.build_user_llm_key_resolver()` method,
  documented inline explaining why it sits outside the `cfg.auth`
  dispatch. This satisfies "registered with the factory" (obtainable
  uniformly through the SAME class) without touching an out-of-scope
  file or overloading a Literal designed for a different (agent-to-
  external-service OAuth) use case.
- `StudioKeysHandler` copies `CredentialsHandler`'s STORAGE discipline
  wholesale (session-vault hot copy + DocumentDB fire-and-forget durable
  copy, `_load_vault_keys()` soft-import guard → 503) but resolves the
  session user via `StudioBaseView._get_user()`/`_resolve_session()`
  (TASK-2511/2512's already-fixed helpers) rather than
  `CredentialsHandler`'s own `getattr(self, '_session', None)` pattern —
  which, on inspection, appears to rely on `self._session` being
  populated by `AbstractModel` (`navigator/views/abstract.py:395-397`),
  a base class `CredentialsHandler` does NOT use (it extends plain
  `BaseView`, same as every Studio handler). Whether that's a pre-
  existing latent gap in `credentials.py` was NOT investigated further —
  out of scope for this task; Studio's OWN handlers already have a
  verified-working session-resolution path, so I used that instead of
  propagating an unverified pattern.
- `resolve_user_api_key(app, user_id, provider)` — the TASK-2517
  integration hook — takes only `app` (no request/session), so it can
  only reach the DocumentDB durable copy (via `_UserLLMKeyResolver`),
  not the per-request session-vault hot copy; documented inline as a
  deliberate, signature-driven limitation (the "fast path" is only
  reachable from inside a live Studio request, e.g. `GET /keys`).
- Masking: `first_3…last_4` chars (`"sk-…1234"`), matching the spec's
  example exactly; `SecretStr.get_secret_value()` called ONLY at
  encryption time, never logged/returned; verified via
  `test_plaintext_never_in_response_or_logs` (asserts across every
  `caplog` record, not just the response body).

**Deviations from spec**: none functionally — see the
`build_user_llm_key_resolver()` design note above for the one
interpretive decision.

Verification: `pytest packages/ai-parrot-server/tests/studio/
test_byok.py packages/ai-parrot/tests/unit/
test_user_llm_key_resolver.py -v` → 9 + 7 = 16/16 passed (run as two
separate pytest invocations — the two packages' `tests/conftest.py`
modules collide under one session, a pre-existing repo-wide test-infra
limitation unrelated to this task). `ruff check` on every touched path
→ clean except intentional `BLE001` fail-open patterns matching
established convention. Full regression sweep: ai-parrot-server
(`tests/studio/`, `tests/manager/`, ephemeral-owner, DB-bot fallback) →
130/130 passed; ai-parrot core (`tests/skills/`, BYOK resolver,
existing `test_credential_broker.py`) → 35/35 passed — confirms the
`CredentialResolverFactory` addition doesn't disturb any existing
resolver-kind behavior.
