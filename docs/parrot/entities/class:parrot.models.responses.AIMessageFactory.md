---
type: Wiki Entity
title: AIMessageFactory
id: class:parrot.models.responses.AIMessageFactory
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory to create AIMessage from different provider responses.
---

# AIMessageFactory

Defined in [`parrot.models.responses`](../summaries/mod:parrot.models.responses.md).

```python
class AIMessageFactory
```

Factory to create AIMessage from different provider responses.

## Methods

- `def from_completion(response: Any, input_text: str, structured_output: Optional[Any]=None, output_mode: OutputMode=OutputMode.DEFAULT, formatter: Optional[Any]=None, **kwargs) -> AIMessage` — Create AIMessage with proper separation of concerns
- `def from_openai(response: Any, input_text: str, model: str, user_id: Optional[str]=None, session_id: Optional[str]=None, turn_id: Optional[str]=None, structured_output: Any=None) -> AIMessage` — Create AIMessage from OpenAI response.
- `def from_groq(response: Any, input_text: str, model: str, user_id: Optional[str]=None, session_id: Optional[str]=None, turn_id: Optional[str]=None, structured_output: Any=None) -> AIMessage` — Create AIMessage from Groq response.
- `def from_grok(response: Any, input_text: str, model: str, user_id: Optional[str]=None, session_id: Optional[str]=None, turn_id: Optional[str]=None, structured_output: Any=None) -> AIMessage` — Create AIMessage from Grok response (xai_sdk Response object).
- `def from_claude(response: Dict[str, Any], input_text: str, model: str, user_id: Optional[str]=None, session_id: Optional[str]=None, turn_id: Optional[str]=None, structured_output: Any=None, tool_calls: List[ToolCall]=None) -> AIMessage` — Create AIMessage from Claude response.
- `def from_bedrock(response: Dict[str, Any], input_text: str, model: str, user_id: Optional[str]=None, session_id: Optional[str]=None, turn_id: Optional[str]=None, structured_output: Any=None, tool_calls: List[ToolCall]=None) -> AIMessage` — Create AIMessage from Bedrock Converse API response.
- `def from_claude_agent(messages: List[Any], input_text: str, model: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, turn_id: Optional[str]=None, structured_output: Any=None) -> AIMessage` — Create an ``AIMessage`` from a ``claude_agent_sdk`` message stream.
- `def from_gemini(response: Any, input_text: str, model: str, user_id: Optional[str]=None, session_id: Optional[str]=None, turn_id: Optional[str]=None, structured_output: Any=None, tool_calls: List[ToolCall]=None, conversation_history: Optional[Any]=None, text_response: Optional[str]=None, files: Optional[List[Path]]=None, images: Optional[List[Any]]=None, code: Optional[str]=None) -> AIMessage` — Create AIMessage from Gemini/Vertex AI response.
- `def create_message(response: Any, input_text: str, model: str, user_id: Optional[str]=None, session_id: Optional[str]=None, turn_id: Optional[str]=None, structured_output: Any=None, tool_calls: List[ToolCall]=None, conversation_history: Optional[Any]=None, text_response: Optional[str]=None, usage: Optional[CompletionUsage]=None, response_time: Optional[float]=None) -> AIMessage` — Create AIMessage from any provider response.
- `def from_imagen(**kwargs)`
- `def from_speech(**kwargs)`
- `def from_video(**kwargs)`
