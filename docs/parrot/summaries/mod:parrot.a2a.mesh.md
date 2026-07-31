---
type: Wiki Summary
title: parrot.a2a.mesh
id: mod:parrot.a2a.mesh
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2A Mesh Discovery - Centralized service for discovering remote A2A agents.
relates_to:
- concept: class:parrot.a2a.mesh.A2AEndpoint
  rel: defines
- concept: class:parrot.a2a.mesh.A2AMeshDiscovery
  rel: defines
- concept: class:parrot.a2a.mesh.AgentStatus
  rel: defines
- concept: class:parrot.a2a.mesh.DiscoveryStats
  rel: defines
- concept: class:parrot.a2a.mesh.HealthCheckStrategy
  rel: defines
- concept: mod:parrot.a2a.client
  rel: references
- concept: mod:parrot.a2a.models
  rel: references
---

# `parrot.a2a.mesh`

A2A Mesh Discovery - Centralized service for discovering remote A2A agents.

This module provides a centralized discovery service for remote A2A agents,
similar to how MCPServerConfig lists available MCP servers. It enables:
- Registration of remote A2A agents by URL
- Health checking with configurable intervals
- Agent lookup by name, skill, or tag
- Configuration from YAML files with environment variable substitution
- Event callbacks for agent status changes

Example:
    # Standalone usage
    mesh = A2AMeshDiscovery()
    await mesh.start()
    await mesh.register("http://agent1:8080")
    await mesh.register("http://agent2:8080")

    # Query agents
    agent = mesh.get("CustomerSupport")
    analysts = mesh.get_by_skill("data_analysis")

    # From YAML config
    mesh = A2AMeshDiscovery.from_config("a2a_agents.yaml")
    await mesh.start()

## Classes

- **`AgentStatus(str, Enum)`** — Status of an agent in the mesh.
- **`HealthCheckStrategy(str, Enum)`** — Strategy for health checking agents.
- **`A2AEndpoint`** — Configuration for an A2A endpoint before discovery.
- **`DiscoveryStats`** — Statistics about mesh discovery operations.
- **`A2AMeshDiscovery`** — Centralized discovery service for remote A2A agents.
