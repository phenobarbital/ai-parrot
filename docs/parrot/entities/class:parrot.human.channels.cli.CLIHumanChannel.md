---
type: Wiki Entity
title: CLIHumanChannel
id: class:parrot.human.channels.cli.CLIHumanChannel
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Interactive CLI channel for Human-in-the-Loop.
relates_to:
- concept: class:parrot.human.channels.base.HumanChannel
  rel: extends
---

# CLIHumanChannel

Defined in [`parrot.human.channels.cli`](../summaries/mod:parrot.human.channels.cli.md).

```python
class CLIHumanChannel(HumanChannel)
```

Interactive CLI channel for Human-in-the-Loop.

Renders interaction prompts in the terminal using Rich and captures
human responses via stdin. Uses asyncio.run_in_executor to avoid
blocking the event loop during input().

This is a production-grade channel — not just for testing. If you're
running agents from your terminal and want to answer questions
directly, this is the channel to use.

Args:
    console: Rich Console instance (created if not provided).
    prompt_prefix: Prefix shown before user input prompts.
    show_context: Whether to display interaction context.
    input_timeout: Optional local timeout for input in seconds.
        None means no local timeout (global interaction timeout
        still applies via the manager).

## Methods

- `async def register_response_handler(self, callback: Callable[[HumanResponse], Awaitable[None]]) -> None` — Register the manager's response callback.
- `async def send_interaction(self, interaction: HumanInteraction, recipient: str) -> bool` — Display the interaction in the terminal and capture the response.
- `async def send_notification(self, recipient: str, message: str) -> None` — Display a notification in the terminal.
- `async def cancel_interaction(self, interaction_id: str, recipient: str) -> bool` — Cancel a pending interaction.
