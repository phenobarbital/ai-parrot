---
type: Wiki Entity
title: BaseBot
id: class:parrot.bots.base.BaseBot
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base Bot implementation providing concrete implementations of
relates_to:
- concept: class:parrot.bots.abstract.AbstractBot
  rel: extends
---

# BaseBot

Defined in [`parrot.bots.base`](../summaries/mod:parrot.bots.base.md).

```python
class BaseBot(AbstractBot)
```

Base Bot implementation providing concrete implementations of
abstract methods defined in AbstractBot.

This is the recommended base class for creating custom bots. It provides
full implementations of ask, ask_stream, invoke, and conversation methods
with support for:
- Vector store context retrieval
- Knowledge base integration
- Conversation history management
- Tool usage (agentic mode)
- Multiple output formats
- Security and prompt injection detection

Subclasses can override these methods to customize behavior or use them
as-is for standard bot functionality.

## Methods

- `async def conversation(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: Optional[str]=None, use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, return_context: bool=False, memory: Optional[Callable]=None, ensemble_config: dict=None, mode: str='adaptive', ctx: Optional[RequestContext]=None, output_mode: OutputMode=OutputMode.DEFAULT, format_kwargs: dict=None, system_prompt: Optional[str]=None, trace_context=None, **kwargs) -> AIMessage` — Conversation method with vector store and history integration.
- `async def chat(self, *args, **kwargs) -> AIMessage` — Alias for conversation method for backward compatibility.
- `async def invoke(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, use_conversation_history: bool=True, memory: Optional[Callable]=None, ctx: Optional[RequestContext]=None, response_model: Optional[Type[BaseModel]]=None, **kwargs) -> AIMessage` — Simplified conversation method with adaptive mode and conversation history.
- `async def ask(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: Optional[str]=None, use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, memory: Optional[Callable]=None, ensemble_config: dict=None, ctx: Optional[RequestContext]=None, permission_context: Optional[Any]=None, structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]]=None, system_prompt: Optional[str]=None, output_mode: OutputMode=OutputMode.DEFAULT, format_kwargs: dict=None, use_tools: bool=True, trace_context=None, **kwargs) -> AIMessage` — Ask method with tools always enabled and output formatting support.
- `async def ask_stream(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: Optional[str]=None, use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, memory: Optional[Callable]=None, ensemble_config: dict=None, ctx: Optional[RequestContext]=None, permission_context: Optional[Any]=None, structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]]=None, output_mode: OutputMode=OutputMode.DEFAULT, system_prompt: Optional[str]=None, trace_context=None, **kwargs) -> AsyncIterator[Union[str, AIMessage]]` — Stream responses using the same preparation logic as :meth:`ask`.
