---
type: Wiki Overview
title: API Reference
id: doc:docs-api-reference-index-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: This section is generated automatically from the docstrings of the
---

# API Reference

This section is generated automatically from the docstrings of the
`parrot` package by
[mkdocstrings](https://mkdocstrings.github.io/). The pages mirror the
top-level subpackages most users interact with.

| Module | What's there |
|---|---|
| [Clients](./clients.md) | `AbstractClient`, provider wrappers, presets |
| [Bots](./bots.md) | `AbstractBot`, `Chatbot`, `Agent`, crews |
| [Tools](./tools.md) | `@tool`, `AbstractToolkit`, `OpenAPIToolkit` |
| [Memory](./memory.md) | Conversation memory, episodic memory |
| [Stores](./stores.md) | Vector store back-ends |
| [Loaders](./loaders.md) | Document loaders for RAG |
| [Integrations](./integrations.md) | Messaging platform adapters |
| [MCP](./mcp.md) | Model Context Protocol clients & servers |
| [A2A](./a2a.md) | Agent-to-Agent protocol |

!!! note "Coverage"

    Some modules have richer docstrings than others. If a page looks
    sparse, that's an invitation to improve the docstrings upstream
    in `packages/ai-parrot/src/parrot/` — not to rewrite the page.

For conceptual narratives, jump into the chapter pages on the left
sidebar.
