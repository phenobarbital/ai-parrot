---
id: FW-001
query_id: Q001
type: wiki_query
intent: "Orient: locate the A2A client and server implementation (closest pattern for calling a remote agent)."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-001 — A2A client, models, mesh and proxy router live in CORE (`parrot/a2a`), JSON-over-aiohttp

## Summary

The A2A client layer is in the core package, not ai-parrot-server (wiki `dir:packages/ai-parrot/src/parrot/a2a`, 7 files; the brainstorm's assumed server location is wrong for the client). `A2AClient` (wiki file page, score 0.93) speaks A2A v1.0/v0.3 over aiohttp JSON: `discover()` fetches the agent card, `send_message`/`stream_message` (SSE), `invoke_skill(skill_id, params)` posts a data Part and returns `part.data` or text, `cancel_task`, push configs, `rpc_call`. Two tool wrappers already turn a remote agent into local tools: `A2ARemoteAgentTool` (free-text question) and `A2ARemoteSkillTool` (per-skill, Pydantic input model built dynamically by `_create_skill_input_model`) — the closest existing analogue of the proposed RemoteToolkit. `A2AProxyRouter` is an existing deterministic, no-LLM gateway (rule-based routing by skill/tag/regex, fan_out, pipeline, can mount itself as an A2A server); `A2AMeshDiscovery` is the existing remote-agent registry (YAML config, health checks, `get_by_skill`, `RegisteredAgent`).

## Citations

- path: `packages/ai-parrot/src/parrot/a2a/client.py`
  symbol: `A2AClient`
  wiki_page_id: file:packages/ai-parrot/src/parrot/a2a/client.py (score 0.93)
  excerpt: |
    class A2AClient: connect/discover/send_message/stream_message/invoke_skill/get_task/cancel_task/rpc_call
    self.headers = {"Content-Type": "application/json", "A2A-Version": "1.0"}
- path: `packages/ai-parrot/src/parrot/a2a/client.py`
  symbol: `A2ARemoteSkillTool`
  excerpt: |
    class A2ARemoteAgentTool(AbstractTool)  # remote agent as a tool (question, context_id)
    def _create_skill_input_model(skill)   # Pydantic model from AgentSkill.input_schema
    class A2ARemoteSkillTool(AbstractTool)  # one remote skill as a tool
- path: `packages/ai-parrot/src/parrot/a2a/router.py`
  symbol: `A2AProxyRouter`
  wiki_page_id: file:packages/ai-parrot/src/parrot/a2a/router.py
  excerpt: |
    "Routes requests to remote A2A agents without LLM processing" — RoutingStrategy SKILL_MATCH/TAG/REGEX/ROUND_ROBIN;
    route_message, invoke_skill, fan_out, pipeline, setup(app) exposes aggregated AgentCard
- path: `packages/ai-parrot/src/parrot/a2a/mesh.py`
  symbol: `A2AMeshDiscovery`
  wiki_page_id: file:packages/ai-parrot/src/parrot/a2a/mesh.py
  excerpt: |
    class A2AEndpoint(url, auth_token, api_key, headers, tags, priority, ...)
    class A2AMeshDiscovery: register(url), get(name), get_by_skill, get_by_tag, from_config(yaml), health loop
- path: `packages/ai-parrot/src/parrot/a2a/models.py`
  symbol: `AgentSkill`
  wiki_page_id: file:packages/ai-parrot/src/parrot/a2a/models.py
  excerpt: |
    AgentCard / AgentSkill / AgentCapabilities / Task / Message / Part(text|file_uri|file_bytes|data) / Artifact / RegisteredAgent
    SecurityScheme family incl. MutualTlsSecurityScheme, OAuth2SecurityScheme (v1.0 card)
- path: `packages/ai-parrot/src/parrot/a2a/mixin.py`
  symbol: `A2AClientMixin`
  wiki_page_id: file:packages/ai-parrot/src/parrot/a2a/mixin.py (score 1.00)
- path: `packages/ai-parrot/src/parrot/a2a/__init__.py`
  symbol: `__getattr__`
  excerpt: |
    # Server-side exports lazy via __getattr__: A2AServer, A2AEnabledMixin -> parrot.a2a.server;
    # JWTAuthenticator, MTLSAuthenticator, A2ASecurityMiddleware, SecureA2AClient -> parrot.a2a.security (ai-parrot-server)

## Notes

- `invoke_skill` already gives a typed-ish RPC over A2A (skill id + params dict), but the result travels inline as JSON `part.data` — the raw payload lands in the caller's context. This is the exact cost the brainstorm targets.
- `docs/agent_mesh.md` (wiki page) draws "A2A Server (gRPC + mTLS)" between a datacenter and an edge zone — the cross-network two-zone scenario is already a documented aspiration, but the implementation is HTTP/JSON.
- [cross-lane: type=read, intent=read packages/ai-parrot/src/parrot/a2a/client.py lines for A2ARemoteSkillTool._execute to confirm how skill results are returned to the LLM]
