---
id: FC-001
query_id: [Q020, Q034, Q037, Q038]
type: read
intent: "Locate and read the A2A client/server — closest existing pattern for calling a remote parrot agent."
executed_at: 2026-10-25T22:42:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-001 — A2A client + server: JSON-over-HTTP, free-text in, text out

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
