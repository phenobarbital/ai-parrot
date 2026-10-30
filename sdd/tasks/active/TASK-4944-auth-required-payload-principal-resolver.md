# TASK-4944: AuthRequiredPayload, to_payload() on both needs-auth exceptions, principal-first OAuthCredentialResolver

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4937, TASK-4940
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (G5, S8, AC-6). Two needs-auth signals exist: `AuthorizationRequired` (converted to a
`ToolResult` by `ToolManager`) and `CredentialRequired` (FEAT-264 broker seam, bubbles uncaught). This task adds
the single `AuthRequiredPayload` superset and a `to_payload()` on both exceptions, and makes
`OAuthCredentialResolver` resolve the principal before touching the token store (G2: a Telegram id resolves to the
same Navigator principal as the web session). The catch sites are TASK-4945.

---

## Scope

- `credentials.py`: add `AuthRequiredPayload` (fields per spec §2); `CredentialRequired.to_payload(*, tool_name=None)`;
  `OAuthCredentialResolver.__init__(oauth_manager, *, principal_resolver=None)`; `resolve` → principal →
  `get_valid_token(channel, principal.user_id, channel_user_id=user_id)`; `get_auth_url` → `create_authorization_url(
  channel, principal.user_id, principal=principal)`; unresolved principal → `resolve` returns `None`,
  `get_auth_url` raises `AuthorizationRequired` with a link instruction message.
- `exceptions.py`: `AuthorizationRequired.to_payload()`.
- Tests: `test_auth_required_payload_superset` (payload half), `test_oauth_resolver_resolves_principal_first`.

**NOT in scope**: ToolManager / AgentTalk catch sites and `AuthRequiredEnvelope` fields (TASK-4945).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/credentials.py` | MODIFY | AuthRequiredPayload, to_payload, principal-first resolver |
| `packages/ai-parrot/src/parrot/auth/exceptions.py` | MODIFY | AuthorizationRequired.to_payload |
| `packages/ai-parrot/tests/unit/test_auth_required.py` | MODIFY | payload assertions |
| `packages/ai-parrot/tests/unit/auth/test_auth_required_payload.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.principal import PrincipalResolver, resolve_principal    # TASK-4937
from parrot.auth.credentials import AuthKind, CredentialRequired           # verified: credentials.py:43, :113
from parrot.auth.exceptions import AuthorizationRequired                  # verified: exceptions.py:12
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/credentials.py
AuthKind = Literal["obo", "oauth2", "static_key", "mcp", "device_code"]          # :43
class CredentialRequired(Exception):                                             # :113
    def __init__(self, provider: str, auth_url: str, auth_kind: str, *, user_code=None,
                 verification_uri=None, expires_in=None) -> None                 # attrs provider, auth_url, auth_kind, user_code,
                                                                                 #   verification_uri, expires_in
class OAuthCredentialResolver(CredentialResolver):                               # :184
    def __init__(self, oauth_manager: "JiraOAuthManager") -> None                # :194  self._manager
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]         # :197 → get_valid_token
    async def get_auth_url(self, channel: str, user_id: str) -> str              # :200 → create_authorization_url
# imports at top: from __future__ import annotations; abc; dataclass; typing; pydantic BaseModel, Field (:27-36)

# packages/ai-parrot/src/parrot/auth/exceptions.py
@dataclass
class AuthorizationRequired(Exception):                                          # :12
    def __init__(self, tool_name, message, auth_url=None, provider="unknown", scopes=None)   # attrs tool_name, message,
                                                                                             #   auth_url, provider, scopes
```

### Does NOT Exist
- ~~`AuthorizationRequired.to_payload()` / `CredentialRequired.to_payload()`~~ — new.
- ~~`AuthRequiredPayload`~~ — new; it lives in `credentials.py` (exceptions.py imports it lazily to avoid a cycle).
- ~~`NeedsAuthorizationError`~~ — never existed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/credentials.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/exceptions.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_auth_required.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_auth_required_payload.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#CredentialRequired",
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#OAuthCredentialResolver",
    "sym:packages/ai-parrot/src/parrot/auth/exceptions.py#AuthorizationRequired"
  ]
}
```

---

## Implementation Notes

- `exceptions.py` must not import `credentials.py` at module level (credentials is heavier); import inside `to_payload`.
- `AuthorizationRequired.to_payload()` → `auth_kind="oauth2"` when `auth_url` is set, else `None`.
- `CredentialRequired.to_payload()` message: `str(self)` is fine (it never contains a secret — auth_url is a consent URL).
- A2A ids (e-mail) resolve through the registered resolver too (AC-3: `resolve("a2a", <email>)`).

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Add `AuthRequiredPayload` + `CredentialRequired.to_payload` (block A) — *why*: S8 single contract.
2. Rewrite `OAuthCredentialResolver` (block A) — *why*: G2/AC-3 principal first, fail closed.
3. Add `AuthorizationRequired.to_payload` (block B) — *why*: both signals serialize identically.
4. Tests.

### `packages/ai-parrot/src/parrot/auth/credentials.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class CredentialRequired(Exception):' credentials.py → :113)
# BEFORE — insert above `class CredentialRequired(Exception):`
class AuthRequiredPayload(BaseModel):
    """Superset of AuthorizationRequired + CredentialRequired (S8); serialized by ToolManager and AgentTalk."""

    provider: str
    auth_url: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    tool_name: Optional[str] = None
    message: str = ""
    auth_kind: Optional[AuthKind] = None
    user_code: Optional[str] = None
    verification_uri: Optional[str] = None
    expires_in: Optional[int] = None

# INSIDE CredentialRequired — append method:
    def to_payload(self, *, tool_name: Optional[str] = None) -> AuthRequiredPayload:
        """Serialize to the unified needs-auth payload (device-code fields preserved)."""
        # FILL IN: AuthRequiredPayload(provider=…, auth_url=…, tool_name=tool_name, message=str(self),
        #          auth_kind=self.auth_kind if it is a valid AuthKind else None, user_code=…, verification_uri=…,
        #          expires_in=…) — bounded by AC-6 "device-code fields survive"
        raise NotImplementedError

# occurrences: 1 (verified: grep -c 'class OAuthCredentialResolver(CredentialResolver):' credentials.py → :184)
# REPLACE __init__/resolve/get_auth_url (:194-202) WITH:
    def __init__(self, oauth_manager: Any, *, principal_resolver: Optional["PrincipalResolver"] = None) -> None:
        self._manager = oauth_manager
        self._principal_resolver = principal_resolver

    async def _principal(self, channel: str, user_id: str) -> Optional["Principal"]:
        """Explicit resolver if given, else the process-wide one (fail closed on None)."""
        from parrot.auth.principal import resolve_principal  # local: keep module import light
        if self._principal_resolver is not None:
            return await self._principal_resolver.resolve(channel, user_id)
        return await resolve_principal(channel, user_id)

    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
        principal = await self._principal(channel, user_id)
        if principal is None:
            return None
        return await self._manager.get_valid_token(channel, principal.user_id, channel_user_id=user_id)

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        # FILL IN: principal None → raise AuthorizationRequired(tool_name="", message="Link your account to
        #          the platform first (/login).", provider=getattr(self._manager, "provider_id", "unknown"));
        #          else url, _ = await self._manager.create_authorization_url(channel, principal.user_id,
        #          principal=principal); return url — bounded by AC-2/AC-9
        raise NotImplementedError
```
**Why**: `channel_user_id=user_id` lets the manager find the legacy channel-scoped key (TASK-4941) while the
lookup key is the principal. FILL IN: add `List` to the typing import and a TYPE_CHECKING import of `Principal`,
`PrincipalResolver`.

### `packages/ai-parrot/src/parrot/auth/exceptions.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class AuthorizationRequired(Exception):' exceptions.py → :12)
# INSIDE AuthorizationRequired — append method after __repr__:
    def to_payload(self) -> "AuthRequiredPayload":
        """Serialize to the unified needs-auth payload (S8)."""
        from parrot.auth.credentials import AuthRequiredPayload  # local: avoid import cycle
        # FILL IN: provider, auth_url, scopes=list(self.scopes), tool_name, message=self.message,
        #          auth_kind="oauth2" if self.auth_url else None
        raise NotImplementedError
```

### FILL IN checklist
- [ ] `credentials.py::CredentialRequired.to_payload`
- [ ] `credentials.py::OAuthCredentialResolver.get_auth_url` — fail-closed branch
- [ ] `exceptions.py::AuthorizationRequired.to_payload`
- [ ] typing imports (`List`, TYPE_CHECKING Principal/PrincipalResolver)
- [ ] tests

---

## Acceptance Criteria

- [ ] Both exceptions produce an `AuthRequiredPayload`; device-code fields survive (AC-6 payload half)
- [ ] `OAuthCredentialResolver.resolve('telegram', '<tg id>')` calls `get_valid_token(channel, <nav id>, channel_user_id='<tg id>')` for a bound user and returns `None` for an unbound one
- [ ] `get_auth_url` for an unbound user raises `AuthorizationRequired`; for a bound user passes `principal=`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_auth_required_payload.py -q`
- `pytest packages/ai-parrot/tests/unit/test_auth_required.py -q`
- `pytest packages/ai-parrot/tests/unit/test_credential_broker.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_auth_required_payload.py
import pytest
from parrot.auth.credentials import AuthRequiredPayload, CredentialRequired, OAuthCredentialResolver
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.principal import Principal

def test_auth_required_payload_superset():
    a = AuthorizationRequired(tool_name="jira_search", message="connect", auth_url="https://x", provider="jira", scopes=["r"])
    c = CredentialRequired("o365", "https://dev", "device_code", user_code="ABCD", verification_uri="https://v", expires_in=900)
    assert isinstance(a.to_payload(), AuthRequiredPayload)
    p = c.to_payload(tool_name="mail")
    assert (p.user_code, p.verification_uri, p.expires_in, p.auth_kind) == ("ABCD", "https://v", 900, "device_code")

@pytest.mark.asyncio
async def test_oauth_resolver_resolves_principal_first():
    ...  # FILL IN: fake manager recording calls + resolver {("telegram","88123"): Principal(user_id="1042", …)};
         #          resolve("telegram","88123") → get_valid_token("telegram","1042", channel_user_id="88123");
         #          resolve("telegram","999") → None and no manager call
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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
