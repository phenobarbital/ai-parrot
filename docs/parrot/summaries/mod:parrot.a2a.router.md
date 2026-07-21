---
type: Wiki Summary
title: parrot.a2a.router
id: mod:parrot.a2a.router
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2A Proxy Router - Routes requests to remote A2A agents without LLM processing.
relates_to:
- concept: class:parrot.a2a.router.A2AProxyRouter
  rel: defines
- concept: class:parrot.a2a.router.LoadBalanceStrategy
  rel: defines
- concept: class:parrot.a2a.router.ProxyStats
  rel: defines
- concept: class:parrot.a2a.router.RoutingResult
  rel: defines
- concept: class:parrot.a2a.router.RoutingRule
  rel: defines
- concept: class:parrot.a2a.router.RoutingStrategy
  rel: defines
- concept: mod:parrot.a2a.client
  rel: references
- concept: mod:parrot.a2a.mesh
  rel: references
- concept: mod:parrot.a2a.models
  rel: references
---

# `parrot.a2a.router`

A2A Proxy Router - Routes requests to remote A2A agents without LLM processing.

This module provides a gateway/proxy for routing requests to multiple A2A agents
based on configurable rules. Unlike LLM-based orchestration, routing decisions
are made using deterministic rules (skill matching, tag matching, regex patterns)
resulting in minimal latency and zero LLM costs.

Key Features:
    - Rule-based routing (skill, tag, regex, round-robin)
    - Load balancing across equivalent agents
    - Request/response transformation hooks
    - Aggregated AgentCard exposing all downstream skills
    - Full A2A protocol compliance (can be consumed as an A2A agent itself)

Example:
    # Create router with mesh discovery
    mesh = A2AMeshDiscovery()
    await mesh.register("http://sales-bot:8080")
    await mesh.register("http://support-bot:8080")
    await mesh.start()

    router = A2AProxyRouter(mesh, name="APIGateway")

    # Configure routing rules
    router.route_by_skill("sales_query", "SalesBot")
    router.route_by_skill("support_ticket", "SupportBot")
    router.route_by_regex(r"precio|price|costo", "SalesBot")
    router.set_default("SupportBot")

    # Use programmatically
    task = await router.route_message("What's the price of product X?")

    # Or expose as HTTP service
    app = web.Application()
    router.setup(app)
    # Now accessible at /.well-known/agent.json as a unified gateway

## Classes

- **`RoutingStrategy(str, Enum)`** — Strategy for selecting target agent.
- **`LoadBalanceStrategy(str, Enum)`** — Strategy for load balancing across multiple target agents.
- **`RoutingRule`** — Defines a routing rule for matching requests to agents.
- **`RoutingResult`** — Result of a routing decision.
- **`ProxyStats`** — Statistics for the proxy router.
- **`A2AProxyRouter`** — Proxy/Gateway for routing requests to A2A agents without LLM processing.
