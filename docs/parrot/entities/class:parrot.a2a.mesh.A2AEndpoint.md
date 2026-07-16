---
type: Wiki Entity
title: A2AEndpoint
id: class:parrot.a2a.mesh.A2AEndpoint
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for an A2A endpoint before discovery.
---

# A2AEndpoint

Defined in [`parrot.a2a.mesh`](../summaries/mod:parrot.a2a.mesh.md).

```python
class A2AEndpoint
```

Configuration for an A2A endpoint before discovery.

Represents a known endpoint that can be registered with the mesh.
The actual AgentCard is fetched during discovery.

Attributes:
    url: Base URL of the A2A agent
    name: Optional name hint (actual name comes from AgentCard)
    auth_token: Bearer token for authentication
    api_key: API key for X-API-Key header
    headers: Additional HTTP headers
    tags: Local tags for categorization (merged with agent's tags)
    timeout: Request timeout for this endpoint
    health_check_strategy: How to check health for this endpoint
    health_check_endpoint: Custom health check endpoint (if strategy is CUSTOM)
    enabled: Whether this endpoint is enabled
    priority: Priority for load balancing (higher = preferred)
    metadata: Additional metadata
