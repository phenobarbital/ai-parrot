# Integrations & Transport

AI-Parrot provides first-class integrations with messaging platforms, voice
systems, and the open protocols that enable agents to talk to each other
and the outside world: MCP (Model Context Protocol) and A2A (Agent-to-Agent).

## Key Concepts

- **Platform Integrations**: Pre-built bots for Telegram, MS Teams, Slack,
  and WhatsApp. Each platform has a Pydantic-validated configuration
  (`TelegramAgentConfig`, `MSTeamsAgentConfig`, etc.) and wires through
  `IntegrationBotManager`.
- **MCP (Model Context Protocol)**: Expose any AI-Parrot agent as an MCP
  server for consumption by Claude Desktop, Cursor, and other MCP clients.
  Also works as a client to consume external MCP servers. Includes built-in
  OAuth2 flow for endpoints that require authentication.
- **A2A (Agent-to-Agent)**: The native AI-Parrot protocol for agent discovery
  and inter-agent communication. Enables two agents on different hosts to
  negotiate capabilities and route tasks.
- **REST Surface**: Aiohttp-based HTTP handlers for chat, MCP, config,
  datasets, and threads — the interface your frontend talks to.

## What You Can Build

- **Multi-platform bots** that run simultaneously on Telegram, Teams, and
  Slack with unified conversation handling.
- **Agent-as-a-service** by exposing your agent via MCP for integration
  with Claude Desktop or Cursor.
- **Tool consumption pipelines** that pull external MCP servers into your
  agent's toolkit.
- **Multi-agent workflows** where agents discover and delegate to each
  other across process or host boundaries using A2A.
- **Web and mobile frontends** that connect through the REST API handlers.

## Deep Dive

For implementation details, configuration options, and platform-specific
guides, see the [Integrations](https://github.com/phenobarbital/ai-parrot/wiki/Home),
[MCP & A2A](https://github.com/phenobarbital/ai-parrot/wiki/Home), and
[Server & APIs](https://github.com/phenobarbital/ai-parrot/wiki/Home)
sections in the Wiki.