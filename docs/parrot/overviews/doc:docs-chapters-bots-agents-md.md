---
type: Wiki Overview
title: Bots & Agents
id: doc:docs-chapters-bots-agents-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: A **bot** in AI-Parrot is a stateful conversational entity wrapped
relates_to:
- concept: mod:parrot.agents
  rel: mentions
---

# Bots & Agents

A **bot** in AI-Parrot is a stateful conversational entity wrapped
around an `AbstractClient`. An **agent** extends that with tool calling
and a ReAct-style reasoning loop. A **crew** orchestrates several
agents together via sequential, parallel or DAG-based execution.

## What lives here

- **`AbstractBot`** — base class for everything conversational.
- **`Chatbot`** — single-LLM, single-turn-aware, stateful chat.
- **`Agent` / `BasicAgent`** — tool-using ReAct agents.
- **`AgentCrew`** — orchestrator with three execution modes:
  - `run_sequential()` — output of agent _n_ feeds agent _n+1_
  - `run_parallel()` — agents run concurrently, results merged
  - `run_flow()` — DAG defined with `task_flow()`
- **Plugin agents** — see `parrot.agents` for the dynamic-import
  registry that resolves agents by name.

## Picking the right primitive

| You need… | Use |
|---|---|
| A single-LLM conversation, no tools | `Chatbot` |
| One agent + a set of tools | `Agent` / `BasicAgent` |
| Several agents in a pipeline | `AgentCrew.run_sequential` |
| Independent agents fanning out | `AgentCrew.run_parallel` |
| Branching dependencies between agents | `AgentCrew.run_flow` |

## Read next

- [Agents](../agent.md), [Agent Mesh](../agent_mesh.md)
- [Crews](../crew.md), [Crew Handler](../crew_handler.md),
  [Crew Summary](../crew_summary.md)
- [Orchestration](../orchestration.md) and
  [Advanced Orchestration](../ORCHESTRATION.md)

## API reference

[API Reference → Bots](../api-reference/bots.md)
