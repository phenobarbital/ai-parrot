---
type: Wiki Overview
title: 'TASK-1657: Wrapper Auth Wiring — BFTokenServiceResolver + AuditLedger in wrapper'
id: doc:sdd-tasks-completed-task-1657-wrapper-auth-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **8**. The `MSAgentSDKWrapper` currently does not
  wire
relates_to:
- concept: mod:parrot.auth.audit
  rel: mentions
---

# TASK-1657: Wrapper Auth Wiring — BFTokenServiceResolver + AuditLedger in wrapper

**Feature**: FEAT-261 — Per-User Auth & OBO for MS Agents SDK Integration
**Spec**: `sdd/specs/auth-obo-msagentsdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1654, TASK-1656
**Assigned-to**: unassigned

---

## Context

Implements spec Module **8**. The `MSAgentSDKWrapper` currently does not wire
any credential resolver. When `config.oauth_connections` is non-empty, the
wrapper should instantiate `BFTokenServiceResolver` and `AuditLedger`, and
pass them to `ParrotM365Agent`.

## Scope

Modify `MSAgentSDKWrapper.__init__()` to:
1. If `config.oauth_connections` is non-empty: instantiate `BFTokenServiceResolver`
   and `AuditLedger`.
2. Pass both to `ParrotM365Agent` via new constructor parameters.
3. If `oauth_connections` is empty: behave exactly as today (no resolver).

Modify `ParrotM365Agent.__init__()` to accept optional `resolver` and
`audit_ledger` parameters. Store them for use in `_handle_message()`.

## Files to Create/Modify

- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py` — MODIFY
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` — MODIFY

## Implementation Notes

### ParrotM365Agent constructor update:

```python
def __init__(
    self,
    parrot_agent: AbstractBot,
    welcome_message: Optional[str] = None,
    resolver: Optional[Any] = None,
    audit_ledger: Optional[Any] = None,
) -> None:
    self.parrot_agent = parrot_agent
    self.welcome_message = welcome_message or "Hello! I'm ready to help."
    self._resolver = resolver      # BFTokenServiceResolver or None
    self._audit_ledger = audit_ledger
    self.logger = logging.getLogger(
        f"ParrotM365Agent.{type(parrot_agent).__name__}"
    )
```

### MSAgentSDKWrapper update:

After the `from .agent import ParrotM365Agent` import, check for OAuth:

```python
# Create bridge agent
from .agent import ParrotM365Agent

resolver = None
audit_ledger = None
if config.oauth_connections:
    from .auth import BFTokenServiceResolver
    from parrot.auth.audit import AuditLedger

    audit_ledger = AuditLedger()
    resolver = BFTokenServiceResolver(
        oauth_connections=config.oauth_connections,
        obo_scopes=config.obo_scopes,
        audit_ledger=audit_ledger,
    )
    self.logger.info(
        "BFTokenServiceResolver wired for connections: %s",
        list(config.oauth_connections.keys()),
    )

self.m365_agent = ParrotM365Agent(
    parrot_agent=agent,
    welcome_message=config.welcome_message,
    resolver=resolver,
    audit_ledger=audit_ledger,
)
```

### _handle_message pass-through:

The resolver doesn't currently integrate into `_handle_message()` at the
agent level (the resolver will be called by tools directly via `PermissionContext`).
But store it on `self._resolver` so future integration is possible.

## Codebase Contract

### Verified Imports
```python
from .agent import ParrotM365Agent           # verified: wrapper.py:110
from parrot.auth.audit import AuditLedger    # to be created in TASK-1655
```

### Existing Signatures
```python
class MSAgentSDKWrapper:                     # wrapper.py:61
    def __init__(self, agent, config, app): ...  # wrapper.py:86

class ParrotM365Agent:                       # agent.py:14
    def __init__(self, parrot_agent, welcome_message=None): ...  # agent.py:33
```

### Does NOT Exist
- `BFTokenServiceResolver` — created in TASK-1654
- `AuditLedger` — created in TASK-1655

## Acceptance Criteria

- [ ] `MSAgentSDKWrapper` creates `BFTokenServiceResolver` and `AuditLedger`
      when `config.oauth_connections` is non-empty.
- [ ] `MSAgentSDKWrapper` skips resolver creation when `oauth_connections` is
      empty (backward compatible).
- [ ] `ParrotM365Agent` accepts optional `resolver` and `audit_ledger` params.
- [ ] Existing bots without OAuth connections start without errors.
- [ ] Wrapper logs the connection names when resolver is wired.

## Test Specification

```python
def test_wrapper_wires_resolver():
    # Wrapper creates BFTokenServiceResolver when oauth_connections non-empty
    ...

def test_wrapper_no_resolver_when_empty():
    # Wrapper skips resolver when oauth_connections is empty
    ...
```

### Completion Note

Modified `wrapper.py` to create `AuditLedger()` and `BFTokenServiceResolver(
oauth_connections=..., obo_scopes=..., audit_ledger=...)` when
`config.oauth_connections` is non-empty. Both are passed to `ParrotM365Agent`
via the new `resolver` and `audit_ledger` params. When `oauth_connections` is
empty, `resolver=None` and `audit_ledger=None` — fully backward compatible.
Logs the configured connection names at INFO when wired.
