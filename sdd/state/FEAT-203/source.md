---
kind: inline
jira_key: null
fetched_at: 2026-05-29T00:00:00Z
summary_oneline: "Extract server infrastructure into ai-parrot-server PEP 420 namespace package"
---

# ai-parrot-server — PEP 420 Satellite Package Extraction

Using PEP 420 implicit namespace convention, convert all server infrastructure
for running ai-parrot as aiohttp services into an independent package
`ai-parrot-server`, centralizing the following sub-packages (currently in
ai-parrot core):

## Sub-packages to Extract

- **parrot/mcp**: Infrastructure to expose tools as MCP services. The
  decoupling separates *consuming* MCP (which agents do, stays in core) from
  *running MCP servers* (moves to ai-parrot-server).

- **parrot/a2a**: Allows consuming agents exposed via the A2A protocol. The
  decoupling separates *consuming* A2A (which agents do, stays in core) from
  *running A2A servers* (moves to ai-parrot-server).

- **parrot/handlers**: All REST HTTP service types exposed for operating with
  agents. Only relevant when running an ai-parrot agent as a web service,
  websocket, or autonomous service.

- **parrot/services**: Services associated with the HTTP server.

- **parrot/scheduler**: APScheduler server infrastructure.

- **parrot/autonomous**: Service for agents running in autonomous mode.

## Important Notes

- **AgentRegistry** and **BotManager** remain in ai-parrot core, even though
  they are used for registering multiple bots/agents and their exposure.
- Follow the FEAT-201 (ai-parrot-embeddings) precedent for PEP 420 namespace
  packaging structure.
