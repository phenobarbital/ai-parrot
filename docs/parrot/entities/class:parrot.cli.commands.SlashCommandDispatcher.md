---
type: Wiki Entity
title: SlashCommandDispatcher
id: class:parrot.cli.commands.SlashCommandDispatcher
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Dispatches slash commands in the agent REPL.
---

# SlashCommandDispatcher

Defined in [`parrot.cli.commands`](../summaries/mod:parrot.cli.commands.md).

```python
class SlashCommandDispatcher
```

Dispatches slash commands in the agent REPL.

Parses ``/command [args]`` strings and routes them to registered
async handler functions. Unknown commands print the help listing.

Attributes:
    logger: Module-level logger.

## Methods

- `def register(self, cmd: SlashCommand) -> None` — Register a slash command.
- `async def dispatch_async(self, input_text: str, repl: 'AgentREPL') -> bool` — Parse and execute a slash command asynchronously.
- `def get_completions(self) -> List[str]` — Return slash command names for tab completion.
