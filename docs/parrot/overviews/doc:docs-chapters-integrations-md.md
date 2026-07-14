---
type: Wiki Overview
title: Integrations & Transport
id: doc:docs-chapters-integrations-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: AI-Parrot ships first-class integrations with messaging platforms
relates_to:
- concept: mod:parrot.a2a
  rel: mentions
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.mcp
  rel: mentions
---

# Integrations & Transport

AI-Parrot ships first-class integrations with messaging platforms
(Telegram, MS Teams, Slack, WhatsApp), voice (WhisperX, voice chat)
and the open protocols that let agents talk to each other and to the
outside world: **MCP** (Model Context Protocol) and **A2A**
(Agent-to-Agent).

## What lives here

### Platform integrations (`parrot.integrations`)

- **`IntegrationBotManager`** — the entry point that wires a bot into
  one or more platforms.
- **Per-platform configs** — `TelegramAgentConfig`,
  `MSTeamsAgentConfig`, etc., with Pydantic-validated credentials.

### MCP (`parrot.mcp`)

- **As a server**: expose any AI-Parrot agent as an MCP server so
  other tools (Claude Desktop, Cursor, …) can call it.
- **As a client**: consume external MCP servers and surface their
  tools to your agent.
- **Auth**: built-in OAuth2 flow for MCP endpoints that require it.

### A2A (`parrot.a2a`)

The native AI-Parrot protocol for agent discovery and inter-agent
communication. Lets two agents — possibly on different hosts —
negotiate capabilities and route tasks.

### REST surface (`parrot.handlers`)

Aiohttp-based HTTP handlers for chat, MCP, config, datasets and
threads. This is what your frontend talks to.

## Decision matrix

| You want… | Use |
|---|---|
| Agent in a messaging app | `parrot.integrations.<platform>` |
| Expose agent to Claude Desktop / Cursor | MCP server |
| Consume tools from a third party | MCP client |
| Multi-agent across processes/hosts | A2A |
| Web/mobile frontend | `parrot.handlers` REST API |

## Read next

- [A2A Communication](../a2a_communication.md)
- [MCP Sessions](../mcp_session.md),
  [Simple MCP Server](../simple_mcp_server.md)
- [Telegram](../telegram_integration.md), [MS Teams](../msteams.md),
  [WhatsApp Orchestrator](../WHATSAPP_AUTONOMOUS_ORCHESTRATOR.md)
- [Office 365 OAuth](../integrations/office365-oauth2.md)
- [M365 Copilot Semantic UI Model → Adaptive Cards](../integrations/msagentsdk-semantic-cards.md)

## API reference

- [API Reference → Integrations](../api-reference/integrations.md)
- [API Reference → MCP](../api-reference/mcp.md)
- [API Reference → A2A](../api-reference/a2a.md)
