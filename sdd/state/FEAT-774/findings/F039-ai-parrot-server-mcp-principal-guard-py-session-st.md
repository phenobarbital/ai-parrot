---
id: F039
query_id: Q052
type: git_log
intent: "Recent history of the server-side MCP principal guard / session store."
executed_at: 2026-10-30T15:19:33Z
duration_ms: 400
parent_id: null
depth: 0
merged_from: [FG-005]
---

# F039 — ai-parrot-server mcp/principal_guard.py, session_store.py history, last 180 days

## Summary

6 commits, all on 2026-09-01 by Jesus Lara, all from the `mcp-as-agent` feature. **`6b593db31`
(TASK-2604) created `principal_guard.py` (+191) with "principal resolution + tenant binding +
`_pctx_var`" and `tests/mcp/test_principal_resolution.py` (+118).** TASK-2605 added PBAC filtering,
TASK-2606 result-size policy, TASK-2609 a Redis-backed session store (`session_store.py`), and
`0f62e8731` closed a "critical PBAC bypass". Nothing since 2026-09-01: the server-side MCP
principal model (how parrot-as-MCP-server binds a caller to a principal and tenant and exposes it
via a ContextVar) is stable and is the only existing "MCP caller → principal" mechanism.

## Citations

- path: `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py`
  lines: 1-191
  symbol: `_pctx_var`
  excerpt: |
    6b593db31 2026-09-01 feat(mcp-as-agent): TASK-2604 — principal resolution + tenant binding + _pctx_var
      principal_guard.py +191, tests/mcp/test_principal_resolution.py +118
    5be9f385c 2026-09-01 TASK-2605 — PBAC filtering (principal_guard.py)
    c94e233f5 2026-09-01 TASK-2606 — result size policy (principal_guard.py)
    0f62e8731 2026-09-01 fix(mcp-as-agent): close critical PBAC bypass (principal_guard.py)
- path: `packages/ai-parrot-server/src/parrot/mcp/session_store.py`
  lines: 1-1
  symbol: `(Redis session store)`
  excerpt: |
    a2c17fe9b 2026-09-01 feat(mcp-as-agent): TASK-2609 — Redis-backed session store
    0ce81354b 2026-09-01 style: black formatting (principal_guard.py, session_store.py)

## Notes

- This is the HTTP/SSE MCP-server direction (remote callers → parrot). It establishes a principal from the transport (bearer / session), the inverse of S-4's stdio-server-in-Claude-Code case, but its `_pctx_var` ContextVar pattern is a reusable shape for threading a CLI principal into tool execution.
- [cross-lane: type=read, intent=Read principal_guard.py lines around _pctx_var and the resolve function to see what inputs (headers, session id) produce the principal and whether it yields a Navigator user_id.]
