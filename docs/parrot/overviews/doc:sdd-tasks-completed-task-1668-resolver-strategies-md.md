---
type: Wiki Overview
title: 'TASK-1668: Adapt OBO / static-key / oauth2 / mcp resolver strategies'
id: doc:sdd-tasks-completed-task-1668-resolver-strategies-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 2. Make the existing resolvers constructible by
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.oauth2.workiq_provider
  rel: mentions
- concept: mod:parrot.integrations.mcp.fireflies_a2a
  rel: mentions
---

# TASK-1668: Adapt OBO / static-key / oauth2 / mcp resolver strategies

**Feature**: FEAT-264 — Unified Credential Broker
**Spec**: `sdd/specs/unified-credential-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1667
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Make the existing resolvers constructible by
`CredentialResolverFactory` from `ProviderCredentialConfig.options`, and add the `mcp`
strategy. No change to OBO/static-key semantics — they already work.

---

## Scope

- Wire the factory's `auth` kinds to strategies:
  - `obo` → `WorkIQOBOCredentialResolver` (construct from `options.source`/`scope` + injected o365/vault deps).
  - `static_key` → `FirefliesCredentialResolver` (from `options.vault_key`/`capture_url` + vault).
  - `oauth2` → `OAuthCredentialResolver` (from `options.provider` + oauth manager).
  - `mcp` → a thin MCP-backed strategy (token via vault/header; integrates with TASK-1676).
- Keep strategy constructors backward-compatible (the A2A/FEAT-263 call sites still work
  until replaced).
- Unit tests: factory builds each kind from a representative config.

**NOT in scope**: the broker/factory themselves (TASK-1667), MCP token injection plumbing
(TASK-1676), deleting the old `wire_*` (TASK-1672).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/broker.py` | MODIFY | factory dispatch → concrete strategies |
| `packages/ai-parrot/src/parrot/auth/oauth2/workiq_provider.py` | MODIFY | accept factory-style construction (keep existing ctor) |
| `packages/ai-parrot/src/parrot/integrations/mcp/fireflies_a2a.py` | (note) | satellite path is `ai-parrot-integrations`; keep API stable |
| `packages/ai-parrot/tests/unit/test_resolver_strategies.py` | CREATE | per-kind build tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import OAuthCredentialResolver, StaticCredentialResolver  # credentials.py:49,81
from parrot.auth.oauth2.workiq_provider import WorkIQOBOCredentialResolver  # workiq_provider.py:66
from parrot.integrations.mcp.fireflies_a2a import FirefliesCredentialResolver  # ai-parrot-integrations: integrations/mcp/fireflies_a2a.py:49
```

### Existing Signatures to Use
```python
# parrot/auth/oauth2/workiq_provider.py:66
class WorkIQOBOCredentialResolver(CredentialResolver):
    def __init__(self, o365_interface, o365_oauth_manager, vault_token_sync, workiq_scope=WORKIQ_SCOPE)
WORKIQ_SCOPE = "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"  # :54

# integrations/mcp/fireflies_a2a.py:49 (ai-parrot-integrations)
class FirefliesCredentialResolver(CredentialResolver):
    def __init__(self, vault_token_sync, oob_capture_url)
    async def store_key(self, user_id: str, api_key: str) -> None  # :147

# parrot/auth/credentials.py:49,81
class OAuthCredentialResolver(CredentialResolver): __init__(self, oauth_manager)
class StaticCredentialResolver(CredentialResolver): __init__(server_url, username=None, password=None, token=None, auth_type="basic_auth")
```

### Does NOT Exist
- ~~a generic `mcp` resolver strategy~~ — create a thin one in this task.
- ~~`fireflies_a2a.py` in `packages/ai-parrot`~~ — it lives in `ai-parrot-integrations` (`src/parrot/integrations/mcp/fireflies_a2a.py`).

---

## Implementation Notes
- Deps (o365 interface, oauth manager, vault) are injected into the factory by the broker
  builder (TASK-1670), not hard-coded. The factory reads only `cfg.options` + injected deps.
- Do not duplicate OBO/static-key logic — instantiate the existing resolvers.

## Acceptance Criteria
- [ ] Factory builds a working resolver for each of obo/oauth2/static_key/mcp from config.
- [ ] Existing FEAT-263 resolver constructors remain callable (no breakage).
- [ ] `pytest packages/ai-parrot/tests/unit/test_resolver_strategies.py -v` passes; `ruff` clean.

## Agent Instructions
Standard SDD flow.

## Completion Note
*(Agent fills this in when done)*
