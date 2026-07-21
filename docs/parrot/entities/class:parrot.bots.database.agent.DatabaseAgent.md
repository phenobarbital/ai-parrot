---
type: Wiki Entity
title: DatabaseAgent
id: class:parrot.bots.database.agent.DatabaseAgent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unified database agent backed by BasicAgent + QueryResponse structured output.
relates_to:
- concept: class:parrot.bots.agent.BasicAgent
  rel: extends
---

# DatabaseAgent

Defined in [`parrot.bots.database.agent`](../summaries/mod:parrot.bots.database.agent.md).

```python
class DatabaseAgent(BasicAgent)
```

Unified database agent backed by BasicAgent + QueryResponse structured output.

Inherits composable prompt layers, LLM lifecycle, and tool management
from BasicAgent.  Database toolkits handle actual DB I/O; the internal
DatabaseAgentToolkit exposes formatting helpers as LLM tools.

Args:
    name: Agent display name.
    toolkits: List of ``DatabaseToolkit`` instances.
    default_user_role: Fallback role when none is provided/inferred.
    vector_store: Optional vector store for cache similarity search.
    redis_url: Optional Redis URL for cache persistence.
    retry_config: Optional query retry configuration.
    **kwargs: Forwarded to ``BasicAgent.__init__``.

## Methods

- `async def configure(self, app: Any=None) -> None` — Configure the agent: create cache partitions, start toolkits,
- `async def cleanup(self) -> None` — Stop all toolkits, close the cache manager, then run base cleanup.
- `async def create_system_prompt(self, **kwargs: Any) -> str` — Build the system prompt using the database-specific PromptBuilder layers.
- `def get_default_components(self, user_role: UserRole) -> OutputComponent` — Return default output components for a user role.
- `async def ask(self, question: str, user_role: Optional[UserRole]=None, database: Optional[str]=None, context: Optional[str]=None, output_components: Optional[Union[str, OutputComponent]]=None, output_format: Optional[Any]=None, session_id: Optional[str]=None, user_id: Optional[str]=None, structured_output: Optional[Any]=None, output_mode: Optional[OutputMode]=None, **kwargs: Any) -> AIMessage` — Process a database query using registered toolkits and the LLM.
- `async def conversation(self, question: str, **kwargs: Any) -> AIMessage` — Conversation method — delegates to ``ask()``.
- `async def invoke(self, question: str, **kwargs: Any) -> AIMessage` — Invoke method — delegates to ``ask()``.
- `async def ask_stream(self, question: str, **kwargs: Any)` — Streaming ask — yields single response (streaming not yet implemented).
