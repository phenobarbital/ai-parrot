---
type: Wiki Overview
title: Foundations
id: doc:docs-chapters-foundations-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The foundations layer holds the core abstractions every other module in
relates_to:
- concept: mod:parrot.core.hooks
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
---

# Foundations

The foundations layer holds the core abstractions every other module in
AI-Parrot is built on: the hook/event bus, the data models shared between
clients, bots and tools, and the architectural decisions that keep the
framework vendor-agnostic and fully async.

## What lives here

- **Core hooks & event bus** — the cross-cutting infrastructure agents
  use to publish lifecycle events, attach observers and compose
  middleware. Source: `parrot.core.hooks`.
- **Pydantic data models** — `AIMessage`, `SourceDocument`,
  `MessageResponse`, `ToolCall` and friends. These are the lingua franca
  between clients, bots and integrations. Source: `parrot.models`.
- **Helpers & utils** — small reusable building blocks (string
  normalisation, async runners, retry decorators).

## Read next

For the long-form architectural reasoning behind these pieces, see the
nine-part architecture series in this section's sidebar:

- [Architecture — MCP Server](../architecture/01-mcp-server.md)
- [Architecture — A2A](../architecture/02-a2a.md)
- [Architecture — Toolkits](../architecture/03-toolkits.md)
- [Architecture — Interaction Surface](../architecture/04-interaction-surface.md)
- [Architecture — Hardening](../architecture/05-hardening.md)
- [Architecture — Cross-cutting Concerns](../architecture/06-cross-cutting.md)
- [Architecture — AgentCrew](../architecture/07-agentcrew.md)
- [Architecture — AgentsFlow DAG](../architecture/08-agentsflow-dag.md)
- [Architecture — Ontologic RAG](../architecture/09-ontologic-rag.md)

## API reference

The auto-generated API for these modules is in
[API Reference → Clients](../api-reference/clients.md) and the per-module
pages that follow it.
