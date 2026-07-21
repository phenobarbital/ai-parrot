---
type: Wiki Entity
title: AgentREPL
id: class:parrot.cli.repl.AgentREPL
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Interactive REPL for agent conversation.
---

# AgentREPL

Defined in [`parrot.cli.repl`](../summaries/mod:parrot.cli.repl.md).

```python
class AgentREPL
```

Interactive REPL for agent conversation.

Uses ``prompt_toolkit.PromptSession.prompt_async()`` for async input
with history, tab completion, and keybindings.  Uses ``ResponseRenderer``
for Rich-based output.  Dispatches slash commands via
``SlashCommandDispatcher`` and forwards remaining input to the agent.

Attributes:
    bot: The ``AbstractBot`` instance being conversed with.
    config: Session configuration.
    renderer: Rich-based response renderer.
    dispatcher: Slash command dispatcher.
    history: Ordered list of ``ConversationTurn`` objects.
    console: Rich Console for direct output.

## Methods

- `async def run(self) -> None` — Run the REPL loop until the user exits.
- `async def send(self, query: str) -> AIMessage` — Send a query to the agent and return the full response.
- `async def send_stream(self, query: str) -> None` — Send a query to the agent and render the streaming response.
- `def register_command(self, cmd: SlashCommand) -> None` — Register a custom slash command with the dispatcher.
