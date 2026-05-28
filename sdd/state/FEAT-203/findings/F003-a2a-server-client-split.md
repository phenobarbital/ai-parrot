---
id: F003
query: "parrot/a2a server vs client classification"
type: read
---

## Finding: parrot/a2a/ (9 files)

### Server infrastructure (→ satellite):
- server.py — A2AServer, A2AEnabledMixin (HTTP endpoints: /.well-known/agent.json,
  /a2a/message/send, /a2a/message/stream, etc.)
- security.py — A2ASecurityMiddleware, JWTAuthenticator, MTLSAuthenticator,
  SecureA2AClient (server-side auth/authz). 1984 lines.

### Client/consumer (→ stays in core):
- client.py — A2AClient, A2ARemoteAgentTool, A2ARemoteSkillTool
- mixin.py — A2AClientMixin
- mesh.py — A2AMeshDiscovery
- router.py — A2AProxyRouter
- orchestrator.py — A2AOrchestrator

### Shared (stays in core, imported by both):
- models.py — AgentCard, Task, Message, TaskState, etc. (pure dataclasses, no deps)

### Cross-deps:
- server.py uses TYPE_CHECKING imports to ..bots.abstract.AbstractBot, ..tools.abstract.AbstractTool
- security.py uses TYPE_CHECKING imports to .server, .client
- No other parrot modules import from parrot.a2a (only examples/tests)
- Self-contained module — cleanest extraction candidate
