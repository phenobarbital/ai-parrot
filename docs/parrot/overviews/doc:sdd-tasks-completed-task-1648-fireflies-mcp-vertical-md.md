---
type: Wiki Overview
title: 'TASK-1648: fireflies MCP-credential vertical (Group B — GATED on OQ#6)'
id: doc:sdd-tasks-completed-task-1648-fireflies-mcp-vertical-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **B2**. Research found fireflies is **MCP-based**,
  not a
relates_to:
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.services.vault_token_sync
  rel: mentions
---

# TASK-1648: fireflies MCP-credential vertical (Group B — GATED on OQ#6)

**Feature**: FEAT-263 — AI-Parrot ⇄ M365 Copilot via A2A (per-user credentials)
**Spec**: `sdd/specs/copilot-a2a-percredential.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1646
**Assigned-to**: unassigned

---

## Context

Implements spec Module **B2**. Research found fireflies is **MCP-based**, not a
native toolkit (only under `parrot/mcp/*` + telegram MCP). Its credential lands
through MCP, so the auth surface reuses the telegram `mcp_persistence`
(`vault_credential_name`) precedent rather than a bespoke api-key form.

> **GATE — OQ#6 (unresolved).** Confirm whether the fireflies MCP server is
> static-API-key or MCP-OAuth BEFORE implementing. Bias: static-key for v1 of
> this vertical. Do not start until OQ#6 is answered (record the answer in spec §8).

---

## Scope

- Resolve OQ#6 (static-key vs MCP-OAuth) and record it.
- Wire a `CredentialResolver` for `provider="fireflies"` over MCP: missing cred →
  OOB capture (static key form OR MCP-OAuth code) → vault (`mcp_persistence` /
  `VaultTokenSync`) → resume → result, with audit.
- Integration test against the bridge with a mocked MCP server.

**NOT in scope**: bridge changes (Group A), jira/work-iq.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | map fireflies tool → MCP CredentialResolver |
| `packages/ai-parrot-integrations/src/parrot/integrations/.../fireflies_a2a.py` | CREATE | fireflies MCP credential adapter (path TBD per MCP layout) |
| `packages/ai-parrot-server/tests/integration/test_a2a_fireflies_vertical.py` | CREATE | fireflies-over-bridge test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (verify exact symbols before use)
```python
# MCP credential persistence precedent (telegram):
#   packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py
#     -> vault_credential_name pattern, per-user MCP server config
# MCP client/registry:
#   packages/ai-parrot/src/parrot/mcp/{client,registry,integration,filtering}.py
from parrot.services.vault_token_sync import VaultTokenSync   # verified: ai-parrot-server .../services/vault_token_sync.py:55
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/services/vault_token_sync.py
class VaultTokenSync:                                          # :55
    async def store_tokens(self, nav_user_id: str, provider: str, tokens: Dict[str, Any]) -> None: ...  # :106
```

### Does NOT Exist  (confirmed via grep 2026-06-26)
- ~~native `FirefliesToolkit` / `FirefliesTool` class~~ — fireflies is MCP-only
- ~~a fireflies OAuth provider in `OAuth2ProviderRegistry`~~ — not registered (jira + o365 only)
- ~~a bespoke fireflies api-key form~~ — reuse MCP credential persistence instead

---

## Implementation Notes
### Key Constraints
- DO NOT start before OQ#6 is resolved.
- Reuse MCP credential persistence; no parallel secret store.
- async; no secret in A2A payloads.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py` — `vault_credential_name` precedent.
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` — nonce→callback→vault precedent.

---

## Acceptance Criteria
- [ ] OQ#6 resolved and recorded in spec §8.
- [ ] fireflies over the bridge: missing cred → OOB capture → vault → resume → result.
- [ ] Audit entry recorded; no secret in A2A payloads.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/integration/test_a2a_fireflies_vertical.py -v`

---

## Test Specification
```python
async def test_fireflies_vertical_end_to_end(): ...   # mocked MCP server
async def test_fireflies_no_secret_in_payload(): ...
```

---

## Agent Instructions
**GATED**: resolve OQ#6 first. Requires TASK-1646 in `completed/`. Parallel-safe
with TASK-1647/1649.

### Completion Note
**DONE.** OQ#6 resolved: Fireflies.ai accepts exclusively a static API key (no OAuth).

Implementation (2026-06-27):
- Created `packages/ai-parrot-integrations/src/parrot/integrations/mcp/fireflies_a2a.py`
  with `FirefliesCredentialResolver` — per-user static-key resolver backed by
  `VaultTokenSync` (vault key: `fireflies:api_key`). OOB capture URL surfaced on
  first use. `store_key()` method for the capture endpoint to persist the key.
- Modified `packages/ai-parrot-server/src/parrot/a2a/server.py`: added
  `wire_fireflies_resolver(resolver)` convenience method (registers under
  `provider="fireflies"`). Also added `wire_workiq_resolver(resolver)` (TASK-1649).
- Created `packages/ai-parrot-server/tests/integration/test_a2a_fireflies_vertical.py`:
  8 tests covering missing-key → INPUT_REQUIRED, no-secret-in-payload, resolved-key →
  COMPLETED, audit-entry, store_key, get_auth_url, wire resolver, no-service-identity
  fallback. All 8 pass.
- Updated `conftest.py` to extend `parrot.integrations.__path__` with the worktree's
  `ai-parrot-integrations/src` directory (new pattern needed for the new `mcp/` sub-package).

Spec §8 updated with OQ#6 resolution.
