---
type: Wiki Summary
title: parrot.a2a.orchestrator
id: mod:parrot.a2a.orchestrator
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2A Hybrid Orchestrator - Combines rule-based routing with LLM-driven orchestration.
relates_to:
- concept: class:parrot.a2a.orchestrator.A2AOrchestrator
  rel: defines
- concept: class:parrot.a2a.orchestrator.AgentExecutionResult
  rel: defines
- concept: class:parrot.a2a.orchestrator.AgentSelection
  rel: defines
- concept: class:parrot.a2a.orchestrator.LLMDecisionStrategy
  rel: defines
- concept: class:parrot.a2a.orchestrator.OrchestrationMode
  rel: defines
- concept: class:parrot.a2a.orchestrator.OrchestrationPlan
  rel: defines
- concept: class:parrot.a2a.orchestrator.OrchestrationResult
  rel: defines
- concept: class:parrot.a2a.orchestrator.OrchestratorStats
  rel: defines
- concept: mod:parrot.a2a.client
  rel: references
- concept: mod:parrot.a2a.mesh
  rel: references
- concept: mod:parrot.a2a.models
  rel: references
- concept: mod:parrot.a2a.router
  rel: references
- concept: mod:parrot.clients.base
  rel: references
---

# `parrot.a2a.orchestrator`

A2A Hybrid Orchestrator - Combines rule-based routing with LLM-driven orchestration.

This module provides an intelligent orchestrator that uses deterministic rules
when possible (fast, zero cost) and falls back to LLM-based decision making
for complex scenarios requiring reasoning about which agents to use.

Key Features:
    - Rule-based routing (via A2AProxyRouter) for known patterns
    - LLM fallback for complex/ambiguous requests
    - Parallel execution across multiple agents
    - Sequential pipelines with output chaining
    - Automatic agent selection based on skills and capabilities
    - Comprehensive statistics and observability

Example:
    # Setup
    mesh = A2AMeshDiscovery()
    await mesh.start()

    orchestrator = A2AOrchestrator(mesh)

    # Configure rules (tried first - fast, no cost)
    orchestrator.route_by_skill("data_analysis", "DataBot")
    orchestrator.route_by_tag("support", "SupportBot")

    # Configure LLM fallback (for complex decisions)
    orchestrator.set_fallback_llm(llm_client)

    # Execute - uses rules if possible, LLM if needed
    result = await orchestrator.run(
        "Analyze sales data and create a customer report",
        mode=OrchestrationMode.HYBRID
    )

## Classes

- **`OrchestrationMode(str, Enum)`** — Mode of orchestration.
- **`LLMDecisionStrategy(str, Enum)`** — Strategy for LLM-based agent selection.
- **`AgentSelection(BaseModel)`** — Single agent selection from LLM.
- **`OrchestrationPlan(BaseModel)`** — Complete orchestration plan from LLM.
- **`AgentExecutionResult`** — Result from a single agent execution.
- **`OrchestrationResult`** — Complete result from orchestration.
- **`OrchestratorStats`** — Statistics for the orchestrator.
- **`A2AOrchestrator`** — Hybrid orchestrator combining rule-based routing with LLM decision-making.
