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

- [A2A Communication](https://github.com/phenobarbital/ai-parrot/wiki/MCP-%26-A2A-A2A-Secure-Communication-Demo)
- [MCP Sessions](https://github.com/phenobarbital/ai-parrot/wiki/MCP-%26-A2A-Create-and-configure-agent),
  [Simple MCP Server](https://github.com/phenobarbital/ai-parrot/wiki/MCP-%26-A2A-Simple-Mcp-Server)
- [Telegram](https://github.com/phenobarbital/ai-parrot/wiki/Integrations-Telegram-Bot-Integration-Guide), [MS Teams](https://github.com/phenobarbital/ai-parrot/wiki/Integrations-MS-Teams-Toolkit-for-AI-Parrot),
  [WhatsApp Orchestrator](https://github.com/phenobarbital/ai-parrot/wiki/Integrations-WhatsApp-%2B-AutonomousOrchestrator-Integration)
- [Office 365 OAuth](https://github.com/phenobarbital/ai-parrot/wiki/Integrations-Office-365-OAuth-2.0-%28Delegated%29-%E2%80%94-AI-Parrot-Integration)
- [M365 Copilot Semantic UI Model → Adaptive Cards](https://github.com/phenobarbital/ai-parrot/wiki/Bots-%26-Agents-Semantic-UI-Model-%E2%86%92-Adaptive-Cards-%28FEAT-303%29)

## API reference

- [API Reference → Integrations](../api-reference/integrations.md)
- [API Reference → MCP](../api-reference/mcp.md)
- [API Reference → A2A](../api-reference/a2a.md)
