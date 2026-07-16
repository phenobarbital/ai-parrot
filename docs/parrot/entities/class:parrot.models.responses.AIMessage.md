---
type: Wiki Entity
title: AIMessage
id: class:parrot.models.responses.AIMessage
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unified AI message response that can handle various output types.
---

# AIMessage

Defined in [`parrot.models.responses`](../summaries/mod:parrot.models.responses.md).

```python
class AIMessage(BaseModel)
```

Unified AI message response that can handle various output types.

## Methods

- `def content(self) -> Any` — Get content as a string. This is an alias for to_text property
- `def content(self, value: Any) -> None` — Set content by updating the output field.
- `def to_text(self) -> str` — Get text representation of output.
- `def has_tools(self) -> bool` — Check if tools were used.
- `def add_tool_call(self, tool_call: ToolCall) -> None` — Add a tool call to the response.
- `def add_artifact(self, artifact_type: str, content: Any, **metadata) -> None` — Add an artifact produced during processing.
- `def has_context(self) -> bool` — Check if any context (vector or conversation) was used.
- `def context_summary(self) -> Dict[str, Any]` — Get a summary of context usage.
- `def set_vector_context_info(self, used: bool, context_length: int=0, search_results_count: int=0, search_type: Optional[str]=None, score_threshold: Optional[float]=None, sources: Optional[List[str]]=None, source_documents: Optional[List[SourceDocument]]=None) -> None` — Set vector context information.
- `def set_conversation_context_info(self, used: bool, context_length: int=0) -> None` — Set conversation context information.
- `def to_dict(self) -> Dict[str, Any]` — Convert to dictionary for serialization.
- `def get_context_metadata(self) -> Dict[str, Any]` — Get metadata about context usage for logging/analytics.
- `def render_as(self, mode: OutputMode, formatter: Any, **kwargs) -> 'AIMessage'` — Create a new AIMessage with different rendering.
