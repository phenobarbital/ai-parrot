---
id: F001
query_id: Q001, Q013, [Q020, Q034, Q037, Q038]
type: read
intent: "Locate and read the A2A client/server — closest existing pattern for calling a remote parrot agent."
executed_at: 2026-10-25T22:42:35Z
duration_ms: 0
parent_id: null
depth: 2
merged_from: FC-001, FW-001, FW-002
lane_origin: FC-001-a2a-client-server, FW-001-a2a-client-core, FW-002-a2a-server-security
---

# F001 — A2A client + server: JSON-over-HTTP, free-text in, text out

## Summary

A2A is fully implemented and is the only cross-network agent-to-agent path today. The client (`parrot/a2a/client.py`, 750 lines) speaks JSON over aiohttp: discovery via `/.well-known/agent-card.json`, `send_message(content: str)` posts `{"message": ...}` and parses a `Task`; `stream_message` reads SSE and extracts text from `artifactUpdate` parts. The remote agent is exposed to a local LLM through `A2ARemoteAgentTool(AbstractTool)` whose `_execute(question: str)` returns the first artifact's text — i.e. the raw remote payload lands in the caller's context as a string. `A2ARemoteSkillTool` builds a per-skill Pydantic input model from the AgentSkill's `input_schema` (typed input exists at skill level). The server (`ai-parrot-server` `parrot/a2a/server.py`, 2084 lines) wraps a bot as aiohttp routes (`_handle_send_message`, `_handle_stream_message`, `_handle_jsonrpc`, task/push-config CRUD) and has a credential gate that appends an `AuditLedgerEntry` per credentialed tool call; `A2ASecurityMiddleware`/`SecureA2AClient` live in `a2a/security.py`. No typed contract, no handle/descriptor result, no binary transport.

## Citations

- path: `packages/ai-parrot/src/parrot/a2a/client.py`
  lines: 40-60
  symbol: `A2AClient`
  excerpt: |
    class A2AClient:
        """
        Client for communicating with remote A2A agents.
- path: `packages/ai-parrot/src/parrot/a2a/client.py`
  lines: 213-243
  symbol: `A2AClient.send_message`
  excerpt: |
    async def send_message(self, content: str, *, context_id: Optional[str] = None,
                           metadata: Optional[Dict[str, Any]] = None) -> Task:
        url = f"{self.base_url}/a2a/message{self._verb_sep}send"
        message = Message.user(content, context_id=context_id, metadata=metadata)
        payload = {"message": message.to_dict()}
        async with self._session.post(url, json=payload) as resp:
- path: `packages/ai-parrot/src/parrot/a2a/client.py`
  lines: 245-310
  symbol: `A2AClient.stream_message`
  excerpt: |
    url = f"{self.base_url}/a2a/message{self._verb_sep}stream"
    ... headers={"Accept": "text/event-stream"}
    if "artifactUpdate" in data:
- path: `packages/ai-parrot/src/parrot/a2a/client.py`
  lines: 543-553
  symbol: `A2ARemoteAgentTool`
  excerpt: |
    class A2ARemoteAgentTool(AbstractTool):
        name: str = "ask_remote_agent"
        description: str = "Ask a question to a remote A2A agent"
        args_schema: Type[BaseModel] = A2ARemoteAgentInput
- path: `packages/ai-parrot/src/parrot/a2a/client.py`
  lines: 607-625
  symbol: `A2ARemoteAgentTool._execute`
  excerpt: |
    async def _execute(self, question: str, context_id: Optional[str] = None, **kwargs) -> str:
        ...
        if task.artifacts:
            return task.artifacts[0].parts[0].text if task.artifacts[0].parts else ""
- path: `packages/ai-parrot/src/parrot/a2a/client.py`
  lines: 695-707
  symbol: `A2ARemoteSkillTool`
- path: `packages/ai-parrot/src/parrot/a2a/client.py`
  lines: 144-171
  symbol: `A2AClient.discover`
  excerpt: |
    Tries the A2A v1.0 discovery URI (/.well-known/agent-card.json)
    first and falls back to the v0.3 URI (/.well-known/agent.json).
- path: `packages/ai-parrot-server/src/parrot/a2a/server.py`
  lines: 85-100
  symbol: `A2AServer`
  excerpt: |
    class A2AServer:
        """
        Wraps an AI-Parrot Agent (BasicAgent/AbstractBot) as an A2A HTTP service.
- path: `packages/ai-parrot-server/src/parrot/a2a/server.py`
  lines: 1249-1302
  symbol: `A2AServer._handle_send_message`
- path: `packages/ai-parrot-server/src/parrot/a2a/server.py`
  lines: 1842
  symbol: `A2AServer._handle_jsonrpc`
- path: `packages/ai-parrot-server/src/parrot/a2a/server.py`
  lines: 965-985
  symbol: `A2AServer._invoke_tool_with_credential_gate`
  excerpt: |
    - **Resolved**: the tool runs; an AuditLedgerEntry is appended;
      task.complete(result) is called.
- path: `packages/ai-parrot-server/src/parrot/a2a/server.py`
  lines: 2039-2059
  symbol: `A2AEnabledMixin`
- path: `packages/ai-parrot-server/src/parrot/a2a/security.py`
  lines: 1409
  symbol: `A2ASecurityMiddleware`
- path: `packages/ai-parrot-server/src/parrot/a2a/security.py`
  lines: 1682
  symbol: `SecureA2AClient`
- path: `packages/ai-parrot/src/parrot/a2a/models.py`
  lines: 1007
  symbol: `AgentCard`
- path: `packages/ai-parrot/src/parrot/a2a/models.py`
  lines: 785
  symbol: `AgentCardSignature`
- path: `packages/ai-parrot/src/parrot/a2a/mesh.py`
  lines: 73-136
  symbol: `A2AEndpoint`, `A2AMeshDiscovery`
- path: `packages/ai-parrot/src/parrot/a2a/mixin.py`
  lines: 34
  symbol: `A2AClientMixin`

## Notes

Package files (Q034): core `parrot/a2a/{client,mesh,mixin,models,orchestrator,router}.py`, server `parrot/a2a/{server,security,push_notifications}.py`, plus `bots/a2a_agent.py` and `bots/flows/agents/a2a_orchestrator.py`. The symbol at server.py:965-985 is the method whose docstring was read; its exact `def` name was not captured — verify before citing by name. `A2AMeshDiscovery` (mesh.py:136) is an existing discovery mechanism separate from AgentRegistry (see FC-006). [cross-lane: type=git_log, intent=recent activity on a2a/security.py and mesh.py — signing / discovery changes]


<!-- merged from FW-001 -->

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


<!-- merged from FW-002 -->

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

- [citation-check: missing] packages/ai-parrot-server/src/parrot/a2a/server.py:965-985 — cited symbol `_invoke_tool_with_credential_gate` does not exist; the method at line 961 is `async def _try_invoke_with_gate(`. Use `_try_invoke_with_gate` (already cited by the merged FW-002 block).
- [citation-check: stale] packages/ai-parrot/src/parrot/a2a/client.py:607 — `_execute` is ambiguous (two defs: 607 A2ARemoteAgentTool, 745 A2ARemoteSkillTool); the cited line range 607-625 selects A2ARemoteAgentTool correctly.
