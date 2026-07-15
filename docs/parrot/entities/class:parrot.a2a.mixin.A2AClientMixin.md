---
type: Wiki Entity
title: A2AClientMixin
id: class:parrot.a2a.mixin.A2AClientMixin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mixin to add A2A client capabilities to any AbstractBot.
---

# A2AClientMixin

Defined in [`parrot.a2a.mixin`](../summaries/mod:parrot.a2a.mixin.md).

```python
class A2AClientMixin
```

Mixin to add A2A client capabilities to any AbstractBot.

This allows an agent to communicate with remote A2A agents,
either directly or by registering them as tools.

Features:
    - Direct connection to remote A2A agents
    - Integration with A2AMeshDiscovery for centralized discovery
    - Integration with A2AProxyRouter for rule-based routing
    - Integration with A2AOrchestrator for hybrid orchestration
    - Automatic tool registration for remote agents/skills

Example:
    class MyAgent(A2AClientMixin, BasicAgent):
        pass

    agent = MyAgent(name="Orchestrator", llm="openai:gpt-4")
    await agent.configure()

    # Option 1: Connect to remote agents directly
    await agent.add_a2a_agent("https://data-agent:8080")
    await agent.add_a2a_agent("https://search-agent:8081")

    # Now the agent can use remote agents as tools
    response = await agent.ask("Search for X and analyze the data")

    # Or call remote agents directly
    result = await agent.ask_remote_agent("data-agent", "What's the total revenue?")

    # Option 2: Use mesh discovery
    mesh = A2AMeshDiscovery.from_config("agents.yaml")
    await mesh.start()
    agent.set_mesh(mesh)
    await agent.discover_from_mesh(skill="data_analysis")

    # Option 3: Use router for rule-based routing
    router = A2AProxyRouter(mesh)
    router.route_by_skill("analysis", "AnalystBot")
    agent.set_router(router)
    result = await agent.route_to_agent("Analyze this data")

    # Option 4: Use orchestrator for hybrid routing
    orchestrator = A2AOrchestrator(mesh)
    orchestrator.set_fallback_llm(llm_client)
    agent.set_orchestrator(orchestrator)
    result = await agent.orchestrate("Complex multi-agent task")

## Methods

- `def set_matrix_transport(self, transport: Any) -> None` — Set a Matrix-based A2A transport.
- `def get_matrix_transport(self) -> Optional[Any]` — Get the configured Matrix A2A transport.
- `def set_mesh(self, mesh: 'A2AMeshDiscovery') -> None` — Connect this agent to an A2A mesh discovery service.
- `def get_mesh(self) -> Optional['A2AMeshDiscovery']` — Get the connected mesh discovery service.
- `async def discover_from_mesh(self, skill: Optional[str]=None, tag: Optional[str]=None, register_as_tools: bool=True) -> List[A2AAgentConnection]` — Discover and connect to agents from the mesh.
- `def set_router(self, router: 'A2AProxyRouter') -> None` — Set an A2A router for rule-based message routing.
- `def get_router(self) -> Optional['A2AProxyRouter']` — Get the connected router.
- `async def route_to_agent(self, message: str, *, skill_id: Optional[str]=None, tags: Optional[List[str]]=None, context_id: Optional[str]=None) -> str` — Route a message to an agent using the configured router.
- `def set_orchestrator(self, orchestrator: 'A2AOrchestrator') -> None` — Set an A2A orchestrator for hybrid routing.
- `def get_orchestrator(self) -> Optional['A2AOrchestrator']` — Get the connected orchestrator.
- `async def orchestrate(self, message: str, *, mode: Optional[str]=None, agents: Optional[List[str]]=None, context_id: Optional[str]=None) -> str` — Orchestrate a message across multiple agents.
- `async def fan_out(self, message: str, agents: List[str], **kwargs) -> Dict[str, Union[str, Exception]]` — Send message to multiple agents in parallel.
- `async def pipeline(self, message: str, agents: List[str], **kwargs) -> str` — Execute sequential pipeline across agents.
- `async def add_a2a_agent(self, url: str, *, name: Optional[str]=None, auth_token: Optional[str]=None, api_key: Optional[str]=None, headers: Optional[Dict[str, str]]=None, register_as_tool: bool=True, register_skills_as_tools: bool=False, use_streaming: bool=False, timeout: float=60.0) -> A2AAgentConnection` — Connect to a remote A2A agent.
- `async def remove_a2a_agent(self, name: str) -> None` — Disconnect from a remote A2A agent.
- `def list_a2a_agents(self) -> List[str]` — List connected A2A agent names.
- `def get_a2a_agent(self, name: str) -> Optional[A2AAgentConnection]` — Get a connected A2A agent by name.
- `def get_a2a_client(self, name: str) -> Optional[A2AClient]` — Get the A2A client for a connected agent.
- `async def ask_remote_agent(self, agent_name: str, question: str, *, context_id: Optional[str]=None, stream: bool=False) -> str` — Ask a question directly to a remote A2A agent.
- `async def invoke_remote_skill(self, agent_name: str, skill_id: str, params: Optional[Dict[str, Any]]=None, *, context_id: Optional[str]=None) -> Any` — Invoke a specific skill on a remote agent.
- `async def shutdown_a2a(self) -> None` — Disconnect all A2A connections and cleanup resources.
- `async def shutdown(self, **kwargs) -> None` — Override shutdown to cleanup A2A connections.
