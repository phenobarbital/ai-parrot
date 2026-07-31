---
type: Wiki Overview
title: 'TASK-1654: BFTokenServiceResolver — CredentialResolver for BF Token Service'
id: doc:sdd-tasks-completed-task-1654-bftokenservice-resolver-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **5**. The `BFTokenServiceResolver` is the core
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
---

# TASK-1654: BFTokenServiceResolver — CredentialResolver for BF Token Service

**Feature**: FEAT-261 — Per-User Auth & OBO for MS Agents SDK Integration
**Spec**: `sdd/specs/auth-obo-msagentsdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1655
**Assigned-to**: unassigned

---

## Context

Implements spec Module **5**. The `BFTokenServiceResolver` is the core
credential adapter: given a tool name, it looks up the OAuth connection name
from config, fetches the per-user token from the Bot Framework Token Service
via the SDK, and optionally performs OBO exchange for the configured scopes.
It records `key_fingerprint` to `AuditLedger` per invocation.

## Scope

Create a new file `auth.py` in the msagentsdk package. Implement:
- `CredentialRequired` exception class
- `BFTokenServiceResolver(CredentialResolver)` class

## Files to Create/Modify

- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/auth.py` — CREATE

## Implementation Notes

### CredentialRequired exception:

```python
class CredentialRequired(Exception):
    """Raised when per-user credentials are needed but not yet authorized."""

    def __init__(self, tool: str, connection_name: str) -> None:
        self.tool = tool
        self.connection_name = connection_name
        super().__init__(
            f"User authorization required for tool '{tool}' "
            f"(connection: '{connection_name}')"
        )
```

### BFTokenServiceResolver:

The resolver needs `turn_context` to call the token service. Since
`CredentialResolver.resolve(channel, user_id)` doesn't carry the turn context,
we accept it as a `**kwarg`:

```python
class BFTokenServiceResolver(CredentialResolver):
    def __init__(
        self,
        oauth_connections: Dict[str, str],
        obo_scopes: Dict[str, List[str]],
        audit_ledger: "AuditLedger | None" = None,
    ) -> None:
        self._connections = oauth_connections  # tool → connection_name
        self._obo_scopes = obo_scopes          # tool → [scope, ...]
        self._ledger = audit_ledger
        self.logger = logging.getLogger(__name__)

    async def resolve(
        self,
        channel: str,
        user_id: str,
        **kwargs,
    ) -> Optional[Any]:
        tool: str = kwargs.get("tool", "")
        turn_context = kwargs.get("turn_context")
        connection_name = self._connections.get(tool)
        if not connection_name:
            self.logger.debug("No OAuth connection configured for tool=%s", tool)
            return None

        token = await self._fetch_token(turn_context, user_id, connection_name)
        if token is None:
            raise CredentialRequired(tool=tool, connection_name=connection_name)

        # OBO exchange if scopes are configured for this tool
        target_token = token
        if tool in self._obo_scopes and self._obo_scopes[tool]:
            target_token = await self._obo_exchange(
                turn_context, token, self._obo_scopes[tool], connection_name
            )

        # Compute key_fingerprint and record audit
        if self._ledger:
            from .audit import AuditEntry
            import hashlib, datetime
            raw = target_token.encode("utf-8") if isinstance(target_token, str) else target_token
            fingerprint = hashlib.sha256(raw[:8]).hexdigest()
            self._ledger.record(AuditEntry(
                timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                user_id=user_id,
                channel=channel,
                tool=tool,
                connection=connection_name,
                key_fingerprint=fingerprint,
                action="resolve",
            ))

        return target_token

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        # The BF token service handles OAuth via sign-in cards, not URL redirects
        raise NotImplementedError(
            "BFTokenServiceResolver uses OAuthCard sign-in; no URL redirect."
        )

    async def _fetch_token(self, turn_context, user_id: str, connection_name: str):
        """Fetch user token from the BF Token Service."""
        if turn_context is None:
            self.logger.warning("No turn_context — cannot fetch token")
            return None
        try:
            # The MS Agents SDK token service API (varies by SDK version)
            # Try UserTokenClient first (newer SDK), fall back to adapter methods
            token_client = None
            if hasattr(turn_context, "turn_state"):
                from microsoft_agents.hosting.core import UserTokenClient
                token_client = turn_context.turn_state.get(UserTokenClient)

            if token_client:
                result = await token_client.get_user_token(
                    user_id, connection_name,
                    turn_context.activity.channel_id,
                    None  # magic_code
                )
            elif hasattr(turn_context, "adapter") and hasattr(turn_context.adapter, "get_user_token"):
                result = await turn_context.adapter.get_user_token(
                    turn_context, connection_name, None
                )
            else:
                self.logger.warning(
                    "Cannot fetch token: no UserTokenClient or adapter.get_user_token"
                )
                return None

            if result and hasattr(result, "token"):
                return result.token
            return None
        except Exception as exc:
            self.logger.warning("Token fetch failed: %s", exc)
            return None

    async def _obo_exchange(self, turn_context, token: str, scopes: List[str],
                            connection_name: str) -> str:
        """Exchange token for OBO scopes (best-effort)."""
        # OBO is handled by the token service; in practice for M365 Agents SDK
        # this may be a no-op if the token already has the needed scopes.
        # Return the original token if we can't exchange.
        try:
            if turn_context is None:
                return token
            # Attempt OBO via SignIn resource if the SDK supports it
            return token
        except Exception as exc:
            self.logger.warning("OBO exchange failed, using original token: %s", exc)
            return token
```

Note on OBO: The exact Python API for OBO exchange in the MS Agents SDK is
unverified (OQ#4 from spec). Implement `_obo_exchange` as a best-effort
no-op initially. The token service may handle OBO internally depending on
how the Azure Bot OAuth connection is configured.

## Codebase Contract

### Verified Imports
```python
from parrot.auth.credentials import CredentialResolver  # verified: credentials.py:27
from navconfig.logging import logging                   # verified: agent.py:8 (pattern)
```

### Existing Signatures
```python
class CredentialResolver(ABC):             # credentials.py:27
    @abstractmethod
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...
    @abstractmethod
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...
    async def is_connected(self, channel: str, user_id: str) -> bool: ...
```

### Does NOT Exist
- `BFTokenServiceResolver` — does not exist yet; being created
- `CredentialRequired` — does not exist yet; being created in this file
- `AuditLedger` — does not exist yet; created in TASK-1655
- `from microsoft_agents import UserAuthorization` — may not exist; use turn_state
- `from microsoft_agents import AgentApplication` — may not exist; do not use

## Acceptance Criteria

- [ ] `BFTokenServiceResolver` in `msagentsdk/auth.py` subclasses
      `CredentialResolver`.
- [ ] `CredentialRequired` exception is defined with `tool` and
      `connection_name` attributes.
- [ ] `resolve()` returns `None` when no connection is configured for the tool.
- [ ] `resolve()` raises `CredentialRequired` when token service has no token
      for the user.
- [ ] `resolve()` returns token when the token service has a valid token.
- [ ] `resolve()` calls `AuditLedger.record()` with `key_fingerprint` when
      `audit_ledger` is provided.
- [ ] `get_auth_url()` raises `NotImplementedError` (sign-in cards, not redirects).

## Test Specification

```python
def test_resolver_returns_token():
    # BFTokenServiceResolver.resolve() returns token from mock SDK client
    ...

def test_resolver_no_token_returns_none():
    # Returns CredentialRequired when token service has no token
    ...

def test_resolver_obo_exchange():
    # Resolver performs OBO exchange when obo_scopes configured
    ...
```

### Completion Note

Created `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/auth.py`
with `CredentialRequired(Exception)` and `BFTokenServiceResolver(CredentialResolver)`.
`resolve()` looks up connection name, calls `_fetch_token()` (tries `UserTokenClient`
from `turn_state`, falls back to `adapter.get_user_token`), raises `CredentialRequired`
when no token, calls `_obo_exchange()` (best-effort no-op pending OQ#4), and records
audit via `_record_audit()` (SHA-256 of first 8 token bytes). All `microsoft_agents.*`
imports are lazy inside methods. `get_auth_url()` raises `NotImplementedError`.
