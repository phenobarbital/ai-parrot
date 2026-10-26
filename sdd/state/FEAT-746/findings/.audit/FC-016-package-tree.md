---
id: FC-016
query_id: [Q036]
type: tree
intent: "Structure of security / auth / registry / observability / storage packages (and MCP transports)."
executed_at: 2026-10-25T22:47:25Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-016 — Tree of the packages the protocol would touch

## Summary

`find -maxdepth 2 -name '*.py'` (tests excluded) over core `security/, auth/, registry/, observability/, storage/` and server `mcp/`. Highlights: `security/` = audit_ledger, command/python sanitizers, redaction, prompt_injection, query_validator, groundedness/; `auth/` = 40+ modules incl. pbac, resolver, grants, approval_token, token_exchange, broker/, oauth2/; `registry/` = registry, storage, capabilities/, routing/; `observability/` = cost/, recorders/, subscribers/, exporters, context; `storage/` = artifacts, artifact_signing, overflow, s3_overflow, backends/{postgres,sqlite,dynamodb,mongodb}, security_reports/; server `mcp/` = agent_mount, agent_jobs, agent_resources, principal_guard, result_policy, session_store, server, transports/{base,grpc_session,http,quic,sse,stdio,streamable_http,unix,websocket}.

## Citations

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot/src/parrot/security/redaction.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot/src/parrot/auth/pbac.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot/src/parrot/auth/grants.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot/src/parrot/auth/approval_token.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot/src/parrot/registry/capabilities/registry.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot/src/parrot/observability/recorders/run_ledger.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot/src/parrot/storage/s3_overflow.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot/src/parrot/storage/backends/postgres.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot-server/src/parrot/mcp/agent_resources.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/quic.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py`
  lines: 1
  symbol: (file)
- path: `packages/ai-parrot-server/src/parrot/mcp/session_store.py`
  lines: 1
  symbol: (file)

## Notes

Core `parrot/mcp/transports` does not exist (bfs error) — transports live only in `ai-parrot-server`. Core `parrot/mcp/` holds client/integration/registry/oauth/toolkit_* modules.
