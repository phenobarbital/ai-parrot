---
type: Wiki Overview
title: 'TASK-1676: MCP per-user token injection via broker'
id: doc:sdd-tasks-completed-task-1676-mcp-per-user-token-injection-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 9. Lets MCP-backed credentialed tools call their MCP server
  with the
relates_to:
- concept: mod:parrot.mcp.client
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1676: MCP per-user token injection via broker

**Feature**: FEAT-264 — Unified Credential Broker
**Spec**: `sdd/specs/unified-credential-broker.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1667, TASK-1669
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9. Lets MCP-backed credentialed tools call their MCP server with the
broker-resolved per-user token, using the existing FEAT-262 MCP auth seam.

---

## Scope

- Provide a broker-backed `header_provider` (and/or `token_supplier`) for
  `MCPClientConfig`, keyed by the per-call canonical `user_id`, so the MCP call carries the
  per-user bearer at invocation time (not connect time).
- Bridge the `current_credential()` ContextVar (TASK-1669) into the MCP tool proxy's
  header resolution so a tool declaring `credential_provider` + MCP transport works.
- Tests: the broker-resolved token reaches `MCPClientConfig.get_headers(context)`.

**NOT in scope**: the broker (1667), the seam (1669), the `mcp` resolver strategy shape
(1668 — this task consumes it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/client.py` | MODIFY | broker-backed header/token supplier hook |
| `packages/ai-parrot/src/parrot/tools/mcp_mixin.py` | MODIFY | pass per-user context into header resolution |
| `packages/ai-parrot/tests/unit/test_mcp_per_user_token.py` | CREATE | token-injection tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.client import MCPClientConfig          # mcp/client.py:132
from parrot.tools.abstract import current_credential   # created in TASK-1669
```

### Existing Signatures to Use
```python
# parrot/mcp/client.py:132
@dataclass
class MCPClientConfig:
    name: str; url=None; command=None; ...
    auth_credential=None; auth_type=None; auth_config={}; token_supplier=None
    headers={}; header_provider=None              # Callable[[ReadonlyContext], Dict[str,str]]
    oauth2=None; auth_preset=None; user_id=None; transport="auto"
    async def get_headers(self, context=None) -> Dict[str, str]  # :238  static → auth_credential → header_provider(context)

# parrot/tools/mcp_mixin.py:57
async def add_mcp_server(self, config: 'MCPServerConfig', context=None) -> List[str]
```

### Does NOT Exist
- ~~a built-in per-call credential hook for MCP tools today~~ — only static headers +
  `header_provider` callback; this task wires the broker into it.

---

## Implementation Notes
- Resolve the token at call time via `current_credential()` / the broker, not at
  `connect()` — otherwise the token is not per-user.
- Reuse `get_headers()` precedence; inject `Authorization: Bearer <token>` via
  `header_provider`. Never log the token.

## Acceptance Criteria
- [ ] A broker-resolved per-user token reaches `MCPClientConfig.get_headers(context)`.
- [ ] An MCP-backed tool with `credential_provider` calls its server with the per-user bearer.
- [ ] `pytest packages/ai-parrot/tests/unit/test_mcp_per_user_token.py -v` passes; `ruff` clean.

## Agent Instructions
Standard SDD flow.

## Completion Note
*(Agent fills this in when done)*
