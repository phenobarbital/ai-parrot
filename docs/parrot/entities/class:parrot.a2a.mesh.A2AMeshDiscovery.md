---
type: Wiki Entity
title: A2AMeshDiscovery
id: class:parrot.a2a.mesh.A2AMeshDiscovery
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Centralized discovery service for remote A2A agents.
---

# A2AMeshDiscovery

Defined in [`parrot.a2a.mesh`](../summaries/mod:parrot.a2a.mesh.md).

```python
class A2AMeshDiscovery
```

Centralized discovery service for remote A2A agents.

Provides a registry of remote A2A agents with automatic health checking,
multiple lookup methods, and event notifications.

Features:
    - Register agents by URL with automatic card discovery
    - Periodic health checks with configurable intervals
    - Lookup by name, skill ID, skill name, or tag
    - Full-text search across agent metadata
    - Event callbacks for status changes
    - YAML configuration with environment variable substitution
    - Statistics and monitoring

Example:
    # Basic usage
    mesh = A2AMeshDiscovery(health_check_interval=60.0)
    await mesh.start()

    agent_card = await mesh.register("http://my-agent:8080")
    print(f"Registered: {agent_card.name}")

    # Query by skill
    analysts = mesh.get_by_skill("data_analysis")
    for agent in analysts:
        print(f"  - {agent.card.name} at {agent.url}")

    await mesh.stop()

    # From config file
    mesh = A2AMeshDiscovery.from_config("config/a2a_agents.yaml")
    await mesh.start()  # Discovers all configured endpoints

## Methods

- `def from_config(cls, config_path: Union[str, Path], **kwargs) -> 'A2AMeshDiscovery'` — Create mesh from YAML configuration file.
- `async def start(self) -> None` — Start the mesh discovery service.
- `async def stop(self) -> None` — Stop the mesh discovery service.
- `def add_endpoint(self, url: str, *, name: Optional[str]=None, auth_token: Optional[str]=None, api_key: Optional[str]=None, headers: Optional[Dict[str, str]]=None, tags: Optional[Union[Set[str], List[str]]]=None, timeout: float=30.0, health_check_strategy: Union[HealthCheckStrategy, str]=HealthCheckStrategy.DISCOVERY, health_check_endpoint: Optional[str]=None, enabled: bool=True, priority: int=0, metadata: Optional[Dict[str, Any]]=None) -> 'A2AMeshDiscovery'` — Add an endpoint configuration for later discovery.
- `def remove_endpoint(self, url: str) -> bool` — Remove an endpoint configuration.
- `def get_endpoint(self, url: str) -> Optional[A2AEndpoint]` — Get endpoint configuration by URL.
- `def list_endpoints(self) -> List[A2AEndpoint]` — List all configured endpoints.
- `async def register(self, url: str, *, auth_token: Optional[str]=None, api_key: Optional[str]=None, headers: Optional[Dict[str, str]]=None, tags: Optional[Union[Set[str], List[str]]]=None, timeout: float=30.0, **kwargs) -> RegisteredAgent` — Register and discover an agent immediately.
- `async def unregister(self, name: str) -> bool` — Unregister an agent by name.
- `def get(self, name: str) -> Optional[RegisteredAgent]` — Get a registered agent by name.
- `def get_by_url(self, url: str) -> Optional[RegisteredAgent]` — Get a registered agent by URL.
- `def get_by_skill(self, skill_id: str, *, include_unhealthy: bool=False, match_name: bool=True) -> List[RegisteredAgent]` — Find agents that have a specific skill.
- `def get_by_tag(self, tag: str, *, include_unhealthy: bool=False, check_skill_tags: bool=True) -> List[RegisteredAgent]` — Find agents that have a specific tag.
- `def search(self, query: str, *, include_unhealthy: bool=False, search_fields: Optional[List[str]]=None) -> List[RegisteredAgent]` — Full-text search across agent metadata.
- `def list_healthy(self) -> List[RegisteredAgent]` — Get all healthy agents.
- `def list_unhealthy(self) -> List[RegisteredAgent]` — Get all unhealthy agents.
- `def list_all(self) -> List[RegisteredAgent]` — Get all registered agents regardless of health status.
- `def list_by_priority(self, descending: bool=True) -> List[RegisteredAgent]` — Get agents sorted by priority.
- `async def check_health_now(self, name: Optional[str]=None) -> Dict[str, bool]` — Trigger immediate health check.
- `def on_agent_healthy(self, callback: AgentEventCallback) -> 'A2AMeshDiscovery'` — Register callback for when an agent becomes healthy.
- `def on_agent_unhealthy(self, callback: AgentEventCallback) -> 'A2AMeshDiscovery'` — Register callback for when an agent becomes unhealthy.
- `def on_agent_registered(self, callback: AgentEventCallback) -> 'A2AMeshDiscovery'` — Register callback for when a new agent is registered.
- `def on_agent_removed(self, callback: AgentEventCallback) -> 'A2AMeshDiscovery'` — Register callback for when an agent is removed.
- `def stats(self) -> DiscoveryStats` — Get current discovery statistics.
- `def get_info(self) -> Dict[str, Any]` — Get detailed information about the mesh state.
