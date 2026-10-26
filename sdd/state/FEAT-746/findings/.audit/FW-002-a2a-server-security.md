---
id: FW-002
query_id: Q013
type: wiki_page
intent: "Drill: read the top wiki page from Q001 (A2A) for API outline."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: FW-001
depth: 2
---

# FW-002 — A2AServer (ai-parrot-server) exposes agent tools as skills, has a credential gate, broker and audit-ledger hooks

## Summary

`A2AServer` (wiki page, 5.1k tokens) wraps any `AbstractBot` as an aiohttp A2A service: `_build_skills_from_tools` converts the agent's tools to `AgentSkill`s (so today the *tools themselves* are the exposed surface — the opposite of the brainstorm's "capabilities, never tools"), `process_message` delegates to `agent.ask`, and `_try_invoke_with_gate`/`_invoke_skill` run a named tool through a credential gate. Constructor already accepts `broker` (CredentialBroker, FEAT-264), `audit_ledger` (AuditLedger), `suspended_store`, `identity_mapper`; identity is extracted from message metadata (`_extract_identity`, never a service identity). Security classes (JWT, mTLS, SecurityPolicy, SecureA2AClient) ship in `parrot.a2a.security` (server satellite).

## Citations

- path: `packages/ai-parrot-server/src/parrot/a2a/server.py`
  symbol: `A2AServer`
  wiki_page_id: file:packages/ai-parrot-server/src/parrot/a2a/server.py (score 0.48)
  excerpt: |
    def __init__(self, agent, *, base_path="/a2a", version="1.0.0", capabilities=None, extra_skills=None,
                 tags=None, broker=None, identity_mapper=None, credential_resolvers=None,
                 suspended_store=None, audit_ledger=None, push_store=None, output_mode=OutputMode.TEXT)
- path: `packages/ai-parrot-server/src/parrot/a2a/server.py`
  symbol: `A2AServer._build_skills_from_tools`
  excerpt: |
    def _build_skills_from_tools(self): Convert agent's tools to A2A skills (excluding internal plumbing).
    def _tool_to_skill(self, tool): Convert an AbstractTool to an AgentSkill.
    def _try_invoke_with_gate(self, tool_name, params): Invoke a named tool through the credential gate.
    def _invoke_skill(self, skill_id, params): legacy direct-invocation path
- path: `packages/ai-parrot-server/src/parrot/a2a/server.py`
  symbol: `A2AServer._extract_identity`
  excerpt: |
    Identity contract (FEAT-260 / TASK-1643): message.metadata["user_id"] > from.email > from.id > sender > x-ms-user-email;
    "A2AServer never falls back to a service identity"
- path: `packages/ai-parrot/src/parrot/a2a/__init__.py`
  symbol: `_SERVER_CLASSES`
  excerpt: |
    "JWTAuthenticator": ("parrot.a2a.security", ...), "MTLSAuthenticator": ("parrot.a2a.security", ...),
    "A2ASecurityMiddleware": ..., "SecureA2AClient": ...
- path: `docs/agent_mesh.md`
  wiki_page_id: file:docs/agent_mesh.md (score 0.61)
  excerpt: |
    DATACENTER "DataGuardian" — A2A Server (gRPC + mTLS) — skills query_customers (read-only) ... | DMZ | EDGE "CustomerAssistant"

## Notes

- The server already has the two hooks the brainstorm wants below the LLM (credential broker gate + audit ledger), but they are credential-shaped (per-user OAuth credentials), not capability/policy-shaped.
- [cross-lane: type=read, intent=read server.py _try_invoke_with_gate and _execute_tool to see what the serving-side tool execution path looks like without an LLM]
