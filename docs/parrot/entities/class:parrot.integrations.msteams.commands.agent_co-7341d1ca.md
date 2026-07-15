---
type: Wiki Entity
title: AgentCommandHandler
id: class:parrot.integrations.msteams.commands.agent_commands.AgentCommandHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Core agent commands for MS Teams.
---

# AgentCommandHandler

Defined in [`parrot.integrations.msteams.commands.agent_commands`](../summaries/mod:parrot.integrations.msteams.commands.agent_commands.md).

```python
class AgentCommandHandler
```

Core agent commands for MS Teams.

Registers /function, /tool, /skill, /commands, /help, /clear, /whoami,
/question, /call, and custom config-mapped commands on the router.

Args:
    agent: The AI-Parrot agent instance.
    wrapper: The ``MSTeamsAgentWrapper`` instance (used for response
        helpers and config access).

## Methods

- `def register(self, router: 'MSTeamsCommandRouter') -> None` — Register all core and custom commands on the router.
- `async def handle_function(self, turn_context) -> None` — Handle /function <method> [key=val ...] -- invoke agent method with kwargs.
- `async def handle_call(self, turn_context) -> None` — Handle /call <method> [args ...] -- invoke agent method with positional args.
- `async def handle_tool(self, turn_context) -> None` — Handle /tool <name> [input] -- use a specific tool via LLM.
- `async def handle_skill(self, turn_context) -> None` — Handle /skill <name> [input] -- activate a skill and query the agent.
- `async def handle_question(self, turn_context) -> None` — Handle /question <text> -- ask the LLM without tools.
- `async def handle_commands(self, turn_context) -> None` — Handle /commands -- list all commands, tools, skills, agent methods.
- `async def handle_help(self, turn_context) -> None` — Handle /help -- show help text.
- `async def handle_whoami(self, turn_context) -> None` — Handle /whoami -- show agent info and user identity.
- `async def handle_clear(self, turn_context) -> None` — Handle /clear -- clear conversation history.
