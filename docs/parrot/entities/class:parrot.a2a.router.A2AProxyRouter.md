---
type: Wiki Entity
title: A2AProxyRouter
id: class:parrot.a2a.router.A2AProxyRouter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Proxy/Gateway for routing requests to A2A agents without LLM processing.
---

# A2AProxyRouter

Defined in [`parrot.a2a.router`](../summaries/mod:parrot.a2a.router.md).

```python
class A2AProxyRouter
```

Proxy/Gateway for routing requests to A2A agents without LLM processing.

This router receives requests and forwards them to appropriate downstream
agents based on configurable routing rules. No LLM is involved in the
routing decision - it's pure rule-based matching.

The router can also expose itself as an A2A-compliant server, presenting
an aggregated view of all downstream agents' capabilities.

Use Cases:
    - API Gateway: Single entry point for multiple specialized agents
    - Load Balancer: Distribute requests across equivalent agents
    - Router: Direct requests based on content/intent
    - Facade: Hide internal agent topology from clients

Example:
    # Setup
    mesh = A2AMeshDiscovery()
    await mesh.register("http://agent1:8080")
    await mesh.register("http://agent2:8080")

    router = A2AProxyRouter(mesh, name="Gateway")

    # Add routing rules
    router.route_by_skill("data_analysis", "DataAnalyst")
    router.route_by_tag("customer", "SupportBot")
    router.route_by_regex(r"urgent|emergency", "PriorityHandler")
    router.set_default("GeneralAssistant")

    # Route a message (no LLM involved!)
    task = await router.route_message("Analyze this data...")
    print(task.artifacts[0].parts[0].text)

    # Expose as A2A server
    app = web.Application()
    router.setup(app)

## Methods

- `def add_route(self, pattern: str, target: Union[str, List[str]], *, strategy: RoutingStrategy=RoutingStrategy.SKILL_MATCH, priority: int=0, load_balance: LoadBalanceStrategy=LoadBalanceStrategy.FIRST_HEALTHY, weights: Optional[Dict[str, float]]=None, transform_request: Optional[TransformFunc]=None, transform_response: Optional[ResponseTransformFunc]=None, enabled: bool=True, metadata: Optional[Dict[str, Any]]=None) -> 'A2AProxyRouter'` — Add a routing rule.
- `def route_by_skill(self, skill_id: str, target: Union[str, List[str]], **kwargs) -> 'A2AProxyRouter'` — Add routing rule that matches by skill ID.
- `def route_by_skill_name(self, skill_name: str, target: Union[str, List[str]], **kwargs) -> 'A2AProxyRouter'` — Add routing rule that matches by skill name (partial match).
- `def route_by_tag(self, tag: str, target: Union[str, List[str]], **kwargs) -> 'A2AProxyRouter'` — Add routing rule that matches by tag.
- `def route_by_regex(self, pattern: str, target: Union[str, List[str]], **kwargs) -> 'A2AProxyRouter'` — Add routing rule that matches by regex pattern in the message.
- `def route_round_robin(self, agents: List[str], **kwargs) -> 'A2AProxyRouter'` — Add round-robin routing across multiple agents.
- `def set_default(self, agent_name: str) -> 'A2AProxyRouter'` — Set the default agent for requests that don't match any rule.
- `def remove_route(self, pattern: str, strategy: Optional[RoutingStrategy]=None) -> bool` — Remove a routing rule.
- `def clear_routes(self) -> 'A2AProxyRouter'` — Clear all routing rules.
- `def list_routes(self) -> List[Dict[str, Any]]` — List all configured routing rules.
- `def find_target(self, message: str, *, skill_id: Optional[str]=None, tags: Optional[List[str]]=None) -> RoutingResult` — Find the target agent for a request.
- `async def route_message(self, message: str, *, skill_id: Optional[str]=None, tags: Optional[List[str]]=None, context_id: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None, timeout: Optional[float]=None) -> Task` — Route a message to the appropriate agent and return the response.
- `async def route_message_stream(self, message: str, *, skill_id: Optional[str]=None, tags: Optional[List[str]]=None, context_id: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None) -> AsyncIterator[str]` — Route a message and stream the response.
- `async def invoke_skill(self, skill_id: str, params: Optional[Dict[str, Any]]=None, *, agent_name: Optional[str]=None, context_id: Optional[str]=None) -> Any` — Invoke a specific skill on a remote agent.
- `async def close_clients(self) -> None` — Close all cached client connections.
- `async def ask(self, message: str, *, agent: Optional[str]=None, **kwargs) -> str` — Shortcut: send message and get response as string.
- `async def fan_out(self, message: str, agents: List[str], *, timeout: float=60.0, **kwargs) -> Dict[str, Union[str, Exception]]` — Send message to multiple agents in parallel.
- `async def pipeline(self, message: str, agents: List[str], **kwargs) -> str` — Execute a sequential pipeline of agents.
- `def get_agent_card(self, force_refresh: bool=False) -> AgentCard` — Get the AgentCard for this router.
- `def setup(self, app: web.Application, base_path: Optional[str]=None) -> None` — Mount the router as an A2A server on an aiohttp application.
- `def stats(self) -> ProxyStats` — Get current statistics.
- `def get_info(self) -> Dict[str, Any]` — Get detailed information about the router state.
