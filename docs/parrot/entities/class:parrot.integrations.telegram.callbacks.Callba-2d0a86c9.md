---
type: Wiki Entity
title: CallbackRegistry
id: class:parrot.integrations.telegram.callbacks.CallbackRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Discovers and stores @telegram_callback handlers from an agent.
---

# CallbackRegistry

Defined in [`parrot.integrations.telegram.callbacks`](../summaries/mod:parrot.integrations.telegram.callbacks.md).

```python
class CallbackRegistry
```

Discovers and stores @telegram_callback handlers from an agent.

Used by TelegramAgentWrapper to route incoming CallbackQuery
updates to the correct agent method.

## Methods

- `def discover_from_agent(self, agent: Any) -> int` — Scan an agent instance for methods decorated with @telegram_callback.
- `def register(self, prefix: str, handler: Callable, description: str='') -> None` — Programmatically register a callback handler.
- `def get_handler(self, prefix: str) -> Optional[CallbackMetadata]` — Get handler metadata by prefix.
- `def match(self, callback_data: str) -> Optional[tuple[CallbackMetadata, Dict[str, Any]]]` — Match callback_data against registered prefixes.
- `def prefixes(self) -> List[str]` — List all registered prefixes.
- `def handlers(self) -> Dict[str, CallbackMetadata]` — All registered handlers.
