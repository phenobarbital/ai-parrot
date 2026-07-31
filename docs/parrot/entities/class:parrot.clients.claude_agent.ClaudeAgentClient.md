---
type: Wiki Entity
title: ClaudeAgentClient
id: class:parrot.clients.claude_agent.ClaudeAgentClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dispatch tasks to a Claude Code agent via ``claude-agent-sdk``.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
---

# ClaudeAgentClient

Defined in [`parrot.clients.claude_agent`](../summaries/mod:parrot.clients.claude_agent.md).

```python
class ClaudeAgentClient(AbstractClient)
```

Dispatch tasks to a Claude Code agent via ``claude-agent-sdk``.

This client wraps the bundled ``claude`` CLI as a subprocess and is
intended for ai-parrot Agents that need to delegate file-aware,
bash-capable, tool-using work to a Claude Code sub-agent.

Authentication is delegated to the CLI: it picks up ``ANTHROPIC_API_KEY``
from the environment when set, otherwise it relies on whatever auth
flow the user has previously completed via ``claude auth``.

Methods that have no SDK equivalent (``batch_ask``, ``ask_to_image``,
the analytic helpers) raise ``NotImplementedError`` with a redirect to
:class:`AnthropicClient`.

## Methods

- `async def get_client(self) -> Any` — Return a fresh ``ClaudeSDKClient`` instance.
- `async def ask(self, prompt: str, model: Optional[Union[str, Any]]=None, max_tokens: int=4096, temperature: float=0.7, files: Optional[List[Any]]=None, system_prompt: Optional[str]=None, structured_output: Any=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, use_tools: Optional[bool]=None, deep_research: bool=False, background: bool=False, lazy_loading: bool=False, *, run_options: Optional[ClaudeAgentRunOptions]=None) -> AIMessage` — Dispatch ``prompt`` to a Claude Code agent and return an AIMessage.
- `async def stream_messages(self, prompt: str, *, run_options: Optional[ClaudeAgentRunOptions]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, session_id: Optional[str]=None) -> AsyncIterator[Any]` — Yield raw Claude Agent SDK messages as they arrive.
- `async def ask_stream(self, prompt: str, model: Optional[str]=None, max_tokens: int=4096, temperature: float=0.7, files: Optional[List[Any]]=None, system_prompt: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, deep_research: bool=False, agent_config: Optional[Dict[str, Any]]=None, lazy_loading: bool=False, *, run_options: Optional[ClaudeAgentRunOptions]=None) -> AsyncIterator[Union[str, AIMessage]]` — Yield the agent's text output incrementally as ``TextBlock``s arrive.
- `async def resume(self, session_id: str, user_input: str, state: Optional[Dict[str, Any]]=None) -> AIMessage` — Continue a previous Claude Code agent session.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Any=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None, run_options: Optional[ClaudeAgentRunOptions]=None) -> InvokeResult` — Stateless structured-output extraction.
- `async def batch_ask(self, requests: List[Any], **kwargs: Any) -> List[Any]` — Always raises — the agent SDK has no batch primitive.
- `async def ask_to_image(self, *args: Any, **kwargs: Any) -> AIMessage`
- `async def summarize_text(self, *args: Any, **kwargs: Any) -> AIMessage`
- `async def translate_text(self, *args: Any, **kwargs: Any) -> AIMessage`
- `async def analyze_sentiment(self, *args: Any, **kwargs: Any) -> AIMessage`
- `async def analyze_product_review(self, *args: Any, **kwargs: Any) -> AIMessage`
- `async def extract_key_points(self, *args: Any, **kwargs: Any) -> AIMessage`
