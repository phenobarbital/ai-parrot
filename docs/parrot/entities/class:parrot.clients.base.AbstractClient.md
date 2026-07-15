---
type: Wiki Entity
title: AbstractClient
id: class:parrot.clients.base.AbstractClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base Class for LLM models.
relates_to:
- concept: class:parrot.core.events.lifecycle.mixin.EventEmitterMixin
  rel: extends
---

# AbstractClient

Defined in [`parrot.clients.base`](../summaries/mod:parrot.clients.base.md).

```python
class AbstractClient(EventEmitterMixin, ABC)
```

Abstract base Class for LLM models.

## Methods

- `def tool_manager(self) -> ToolManager` — Get the tool manager.
- `def tool_manager(self, manager: ToolManager) -> None` — Set the tool manager (allows reference swapping at runtime).
- `def client(self) -> Optional[Any]` — Return the SDK client bound to the *current* event loop, or ``None``.
- `def client(self, value: Optional[Any]) -> None` — Accept ``None`` (legacy reset) and reject non-``None`` assignments.
- `def default_model(self) -> str` — Return the default model for the client.
- `async def get_client(self) -> Any` — Return the client instance.
- `async def complete(self, prompt: str, *, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: Optional[int]=None, temperature: Optional[float]=None) -> str` — Send a prompt, return the model's textual reply as a plain string.
- `async def close(self) -> None` — Close all per-loop SDK clients.
- `async def close_all(self) -> None` — Tear down every per-loop SDK client entry.
- `def set_program(self, program_slug: str) -> None` — Set the program slug for the client.
- `async def start_conversation(self, user_id: str, session_id: str, metadata: Optional[Dict[str, Any]]=None, chatbot_id: Optional[str]=None) -> ConversationHistory` — Start a new conversation session.
- `async def get_conversation(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> Optional[ConversationHistory]` — Get an existing conversation session.
- `async def clear_conversation(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> bool` — Clear conversation history for a session.
- `async def delete_conversation(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> bool` — Delete conversation history entirely.
- `async def list_user_conversations(self, user_id: str, chatbot_id: Optional[str]=None) -> List[str]` — List all conversation sessions for a user.
- `def set_tools(self, tools: List[Union[str, AbstractTool]]) -> None` — Set complete list of tools, replacing existing.
- `def get_tool(self, name: str) -> Optional[AbstractTool]` — Get a tool by name from ToolManager or legacy tools.
- `def register_tool(self, tool: Union[ToolDefinition, AbstractTool]=None, name: str=None, description: str=None, input_schema: Dict[str, Any]=None, function: Callable=None) -> None` — Register a Python function as a tool for LLM to call.
- `def register_tools(self, tools: List[Union[ToolDefinition, AbstractTool]]) -> None` — Register multiple tools at once.
- `def register_python_tool(self, report_dir: Optional[Path]=None, plt_style: str='seaborn-v0_8-whitegrid', palette: str='Set2') -> PythonREPLTool` — Register Python REPL tool with a ClaudeAPIClient.
- `def list_tools(self) -> List[str]` — Get a list of all registered tool names.
- `def remove_tool(self, name: str) -> bool` — Remove a tool by name.
- `def clear_tools(self) -> None` — Clear all registered tools.
- `async def ask(self, prompt: str, model: str, max_tokens: int=4096, temperature: float=0.7, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, structured_output: Union[type, StructuredOutputConfig, None]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, use_tools: Optional[bool]=None, deep_research: bool=False, background: bool=False, lazy_loading: bool=False) -> MessageResponse` — Send a prompt to the model and return the response.
- `async def ask_stream(self, prompt: str, model: str=None, max_tokens: int=4096, temperature: float=0.7, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, deep_research: bool=False, agent_config: Optional[Dict[str, Any]]=None, lazy_loading: bool=False) -> AsyncIterator[Union[str, AIMessage]]` — Stream the model's response.
- `async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> MessageResponse` — Resume a suspended model execution.
- `async def batch_ask(self, requests: List[Any]) -> List[Any]` — Process multiple requests in batch.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None) -> InvokeResult` — Lightweight stateless invocation — no retry, no history, no prompt builder.
- `def create_conversation_memory(memory_type: str='memory', **kwargs) -> ConversationMemory` — Factory method to create a conversation memory instance.
