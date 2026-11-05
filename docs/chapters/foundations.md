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

- [Architecture — MCP Server](https://github.com/phenobarbital/ai-parrot/wiki/Architecture-1.-MCP-Server-%E2%80%94-exposing-tools-as-a-service)
- [Architecture — A2A](https://github.com/phenobarbital/ai-parrot/wiki/Architecture-2.-A2A-%E2%80%94-exposing-agents-and-orchestrators-as-services)
- [Architecture — Toolkits](https://github.com/phenobarbital/ai-parrot/wiki/Architecture-3.-Toolkits-for-third-party-services-and-Cloud-Security-composition)
- [Architecture — Interaction Surface](https://github.com/phenobarbital/ai-parrot/wiki/Architecture-4.-Interaction-surface-%E2%80%94-WebSockets%2C-audio%2C-integrations)
- [Architecture — Hardening](https://github.com/phenobarbital/ai-parrot/wiki/Architecture-5.-Hardening-%E2%80%94-anti-prompt-injection%2C-PBAC-and-tool-gating)
- [Architecture — Cross-cutting Concerns](https://github.com/phenobarbital/ai-parrot/wiki/Architecture-6.-Cross-cutting-concerns-and-reference-deployment)
- [Architecture — AgentCrew](https://github.com/phenobarbital/ai-parrot/wiki/Architecture-7.-AgentCrew-%E2%80%94-Sequential%2C-Parallel%2C-Flow-and-Loop-execution)
- [Architecture — AgentsFlow DAG](https://github.com/phenobarbital/ai-parrot/wiki/Architecture-8.-AgentsFlow-%E2%80%94-DAG-first-orchestration-with-per-node-FSM)
- [Architecture — Ontologic RAG](https://github.com/phenobarbital/ai-parrot/wiki/Architecture-9.-Ontologic-RAG-%E2%80%94-graph-first-retrieval%2C-intent-routing-%26-multi-tenant-knowledge)

## API reference

The auto-generated API for these modules is in
[API Reference → Clients](../api-reference/clients.md) and the per-module
pages that follow it.
