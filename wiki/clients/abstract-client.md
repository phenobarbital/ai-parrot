---
title: "AbstractClient: The Provider Client Family"
summary: "The AbstractClient contract (ask, ask_stream, invoke, resume, get_client), its memory-less history design, and the satellite packages that ship each provider client."
---

# AbstractClient: The Provider Client Family

## Purpose

`AbstractClient` is the single interface AI-Parrot uses to talk to every LLM
provider. Bots, agents and crews never call a provider SDK directly: they hold
an `AbstractClient` subclass and call `ask()`, `ask_stream()`, `invoke()` or
`resume()` on it. Concrete behaviour (authentication, wire format, tool-schema
shape, streaming) lives in the subclass; shared machinery (tool registry,
per-event-loop SDK client cache, token budgets, structured-output parsing,
`max_tokens` resolution) lives in the base class.

Two design points shape how you use it:

- **Memory-less (FEAT-524).** A client neither loads nor saves conversation
  history. The owning bot renders history with `parrot.memory.render_history()`
  and passes it per call as `history=`. The client only maps that provider-neutral
  list onto its own message shape through `_format_history()`.
- **Satellite distribution (FEAT-523).** Core ships only the base classes and
  `OpenAIBaseClient`. Each provider is a separate `ai-parrot-client-<provider>`
  package that merges into the same `parrot.clients.*` namespace (PEP 420) and
  registers itself under the `parrot.clients` entry-point group. With no
  satellite installed, `LLMFactory.list_providers()` returns `{}`.

### Provider families

Verified under `packages/ai-parrot-client-*/src/parrot/clients/`:

| Distribution | Module | Client class(es) | Entry-point keys |
|---|---|---|---|
| `ai-parrot-client-openai` | `parrot.clients.openai` | `OpenAIClient` (subclass of `OpenAIBaseClient`), `OpenAICodexClient` in `codex_agent.py` | `openai` |
| `ai-parrot-client-anthropic` | `parrot.clients.anthropic` | `AnthropicClient`, `ClaudeAgentClient` (in `claude_agent.py`) | `claude` |
| `ai-parrot-client-google` | `parrot.clients.google` | `GoogleGenAIClient`, `GeminiLiveClient` (`live.py`), `GeminiOpenAICompatClient` (`openai_compat.py`) | `google` |
| `ai-parrot-client-groq` | `parrot.clients.groq` | `GroqClient` | `groq` |
| `ai-parrot-client-amazon` | `parrot.clients.amazon` | `BedrockConverseClient`, `NovaClient` | `bedrock-converse`, `nova` |
| `ai-parrot-client-grok` | `parrot.clients.grok` | `GrokClient` | `grok`, `xai` |
| `ai-parrot-client-meta` | `parrot.clients.meta` | `MetaClient` | `meta`, `muse` |
| `ai-parrot-client-moonshot` | `parrot.clients.moonshot` | `MoonshotClient` | `moonshot`, `kimi` |
| `ai-parrot-client-nvidia` | `parrot.clients.nvidia` | `NvidiaClient` | `nvidia` |
| `ai-parrot-client-openrouter` | `parrot.clients.openrouter` | `OpenRouterClient` | `openrouter` |
| `ai-parrot-client-local` | `parrot.clients.local` | `LocalLLMClient` | `local`, `localllm` |
| `ai-parrot-client-vllm` | `parrot.clients.vllm` | `vLLMClient` (subclass of `LocalLLMClient`) | `vllm` |
| `ai-parrot-client-zai` | `parrot.clients.zai` | `ZaiClient` | `zai`, `z.ai` |
| `ai-parrot-client-hf` | `parrot.clients.hf` | `TransformersClient` | `hf` |
| `ai-parrot-client-gemma4` | `parrot.clients.gemma4` | `Gemma4Client` | `gemma4` |
| `ai-parrot-client-jev` | `parrot.clients.jev` | `JevClient` | `jev`, `typesafe` |

Most OpenAI wire-compatible providers (Groq, Local, Meta, Moonshot, Nvidia,
OpenAI, OpenRouter, Zai) subclass `OpenAIBaseClient`; Anthropic, Google, Grok,
Bedrock, HF, Gemma4 and Jev subclass `AbstractClient` directly. Bedrock Converse
derives from `BedrockConverseBase`, itself an `AbstractClient`.

## Public API

- [`parrot.clients.base`](ref:parrot.clients.base) — `AbstractClient`, `LLM_PRESETS`, `StreamingRetryConfig`, `RetryConfig`, `TokenRetryMixin`, `MessageResponse`.
- [`parrot.clients.factory`](ref:parrot.clients.factory) — `LLMFactory` and the lazily populated `SUPPORTED_CLIENTS` registry.
- [`parrot.clients.openai_base`](ref:parrot.clients.openai_base) — `OpenAIBaseClient`, the shared base of OpenAI-compatible providers.
- [`parrot.clients.protocols`](ref:parrot.clients.protocols) — `VoiceCapable`, a `runtime_checkable` Protocol for clients with `stream_voice()`.
- [`parrot.clients.budget`](ref:parrot.clients.budget) — cumulative question-budget ledger (see the token budgets page).

The package `parrot.clients` re-exports `LLM_PRESETS`, `AbstractClient`,
`OpenAIBaseClient` and `StreamingRetryConfig`.

### The abstract surface

The base class declares four abstract methods plus `get_client()`:

```python
async def get_client(self) -> Any

async def ask(
    self, prompt: str, model: str, max_tokens: Optional[int] = None,
    temperature: float = 0.7, files: Optional[List[Union[str, Path]]] = None,
    system_prompt: Optional[str] = None,
    history: Optional[Sequence[HistoryMessage]] = None,
    structured_output: Union[type, StructuredOutputConfig, None] = None,
    tools: Optional[List[Dict[str, Any]]] = None, use_tools: Optional[bool] = None,
    deep_research: bool = False, background: bool = False, lazy_loading: bool = False,
) -> MessageResponse

async def ask_stream(
    self, prompt: str, model: str = None, max_tokens: Optional[int] = None,
    temperature: float = 0.7, files=None, system_prompt=None, history=None,
    tools=None, deep_research: bool = False,
    agent_config: Optional[Dict[str, Any]] = None, lazy_loading: bool = False,
) -> AsyncIterator[Union[str, AIMessage]]

async def invoke(
    self, prompt: str, *, output_type: Optional[type] = None,
    structured_output: Optional[StructuredOutputConfig] = None,
    model: Optional[str] = None, system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None, temperature: float = 0.0,
    use_tools: bool = False, tools: Optional[list] = None,
) -> InvokeResult

async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> MessageResponse
```

- `ask()` is the full conversational call. There is no `user_id` or `session_id`
  parameter: identity and persistence belong to the bot.
- `ask_stream()` yields `str` chunks and then one final `AIMessage` with usage and
  stop metadata. Implementors must yield at least one `str` before it; detect the end with
  `isinstance(chunk, AIMessage)`.
- `invoke()` is the lightweight, stateless call: no retry, no history, no prompt
  builder. It returns an `InvokeResult` and raises `InvokeError` on any provider failure.
- `resume()` continues a suspended tool execution, injecting `user_input` as the tool result
  from the saved `state`.
- `batch_ask()` exists but raises `NotImplementedError` unless a subclass implements it.

### Concrete helpers on the base class

- `complete(prompt, *, model, system_prompt, max_tokens, temperature) -> str`: a thin
  wrapper around `ask()` for single-shot, tool-less text.
- Tools: `register_tool`, `register_tools`, `register_python_tool`, `set_tools`,
  `get_tool`, `list_tools`, `remove_tool`, `clear_tools`, and the `tool_manager` property.
- Lifecycle: `close()` / `close_all()` and `async with` support (`__aenter__` / `__aexit__`).
- `set_program(program_slug)` sets the program slug.

### History handling

`_format_history(history)` is the only history extension point for providers. The
default emits `{"role": ..., "content": [{"type": "text", "text": ...}]}` per message.
`_build_messages(prompt, files, history)` composes `[*formatted_history, current_turn]`.
Overrides exist in the Google client (SDK content objects), the Bedrock Converse base
(`{"role", "content": [{"text": ...}]}`) and `JevClient`.

### Tool-loop capability (`supports_tool_loop`)

The class attribute `supports_tool_loop` declares whether the client's text `ask()` executes tool calls.
When `True` (the default), `ask()` runs the tool loop: it executes enabled, registered tools and feeds
their results back before returning, either in-process or through an agent bridge, within existing loop limits.
The attribute is declarative — `ask()` never reads it.

Clients that declare `supports_tool_loop = False` are:
- `TransformersClient` (`hf` / `transformers` provider keys)
- `JevClient` (`jev` / `typesafe` provider keys)
- `GeminiLiveClient` (`gemini-live` provider key)

`OpenAICodexClient` and `ClaudeAgentClient` run the tool loop through their respective agent bridges
(`CodexToolBridge` and `ClaudeAgentToolBridge`). These bridges expose only tools registered in
`client.tool_manager`; inline `tools=` arguments to `ask()` are ignored.

Readers of this flag include:
- **PageIndex agentic retrieval** — calls `require_tool_loop(client)` before candidate search; raises
  `ValueError` on a `False` client.
- **AbstractBot** — warns once per real `configure()` run if the client lacks the capability; it never
  refuses the client.

There is **no streaming capability flag**. `ask_stream()` may skip the tool loop that `ask()` runs.
Known gaps are tracked as ledger issues (Groq, Grok, Meta Responses API).

## Configuration & Parameters

Constructor: `AbstractClient.__init__(preset=None, tools=None, use_tools=False, debug=True, tool_manager=None, **kwargs)`.
Keyword arguments read by the base class include `model`, `temperature` (default `0`),
`top_k` (30), `top_p` (0.2), `max_tokens`, `invoke_max_tokens`, `api_key`, `version`,
`headers`, `use_session`, `client_type`, `program`, `fallback_model`, and the budget
options `token_budget`, `budget_mode`, `final_answer_reserve`, `budget_registry`.

- **`preset`** selects an entry of `LLM_PRESETS` (`analytical`, `creative`, `balanced`,
  `concise`, `detailed`, `comprehensive`, `verbose`, `summarization`, `translation`,
  `inspiration`, `default`), which sets temperature and `max_tokens`. An unknown name
  falls back to `default`.
- **`max_tokens` resolution**: per-call value, then the instance value (`max_tokens=` or a
  preset), then the class default `_default_max_tokens`. `invoke()` uses
  `invoke_max_tokens`, then an explicitly configured `max_tokens`, then `_invoke_max_tokens`.
  `_model_max_tokens` (`{model_fragment: cap}`) clamps the budget to a per-model ceiling.
- **Subclass class attributes** you may override: `client_type`, `client_name`,
  `credential_env` (config names holding the server-side API key, used by
  `has_server_credentials()`), `tool_format` (wire format for tool schemas),
  `_lightweight_model`, `_fallback_model`, `_min_cache_tokens`, and
  `budget_supported_methods`.
- **Model fallback**: `_fallback_model` is retried on capacity errors (see
  `_is_capacity_error` / `_should_use_fallback`).
- **`use_session=True`** makes `async with` create an `aiohttp.ClientSession`.

`LLMFactory.create(llm, model_args=None, tool_manager=None, **kwargs)` accepts
`"provider:model"` or `"provider"`. `model_args` may carry `temperature`, `top_k`, `top_p`,
`max_tokens`. An unknown provider raises `ImportError` suggesting the matching
`ai-parrot-client-<provider>` install. `LLMFactory.parse_llm_string`,
`list_providers()`, `list_models(provider)` and `supported_clients()` are also available.

## Usage Examples

Create a client through the factory and call it:

```python
import asyncio
from parrot.clients.factory import LLMFactory


async def main() -> None:
    client = LLMFactory.create(
        llm="groq:llama-3.3-70b-versatile",
        model_args={"temperature": 0.0, "max_tokens": 1024},
    )
    async with client:
        text = await client.complete("Say hello in one sentence.")
        print(text)


asyncio.run(main())
```

Stream a response and detect the final message:

```python
from parrot.clients.base import AbstractClient
from parrot.models.responses import AIMessage


async def stream(client: AbstractClient, model: str) -> None:
    async for chunk in client.ask_stream("Explain asyncio briefly.", model=model):
        if isinstance(chunk, AIMessage):
            print("\n[done]", chunk)
        else:
            print(chunk, end="", flush=True)
```

Write a new provider by subclassing and implementing the abstract methods:

```python
from typing import Any, Dict
from parrot.clients.base import AbstractClient


class MyClient(AbstractClient):
    client_type = "my"
    client_name = "my"
    _default_max_tokens = 4096

    async def get_client(self) -> Any:
        ...  # build and return the provider SDK client

    async def ask(self, prompt: str, model: str, **kwargs):
        ...

    async def ask_stream(self, prompt: str, model: str = None, **kwargs):
        ...

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]):
        ...

    async def invoke(self, prompt: str, **kwargs):
        ...
```

Register it by adding an entry under `[project.entry-points."parrot.clients"]` in your
distribution's `pyproject.toml`, the same way the satellite packages do.

## Gotchas

- **Do not persist history in a client.** Passing `history=` is the only supported route;
  there is no `user_id` / `session_id` on `ask()` or `ask_stream()`.
- **Override `_format_history` only.** Providers whose message shape differs override that
  one hook; `_build_messages` composes the final list and encodes the current turn once.
- **`tool_format` must be explicit for OpenAI-shaped subclasses.** Clients that speak an
  OpenAI protocol under a different `client_type` must declare `tool_format`, or tool
  schemas fall back to the Anthropic shape and the provider rejects the request.
- **Public text methods are wrapped for budgets.** `__init_subclass__` wraps each subclass's own `ask`, `ask_stream`,
  `resume` and `invoke` with the question-budget entry adapter. A client that does not list a method in
  `budget_supported_methods` rejects any requested budget before the implementation runs.
- **`_default_max_tokens` is declared twice in the base class body** (8192, then 16384); the
  later assignment wins, so the effective base default is 16384. Subclasses override it
  for their provider.
- **SDK clients are cached per event loop.** Use `close()` / `close_all()` or `async with`
  to release them; see the per-loop cache page.
- **Empty registry without satellites.** `LLMFactory.create("openai")` raises `ImportError` if
  `ai-parrot-client-openai` is not installed.
- **Never modify `parrot/clients/base.py` casually.** It is the foundation of every provider.
- **A `supports_tool_loop = False` client ignores offered tools.** `TransformersClient` logs nothing when
  tools arrive through `tool_manager`; check the flag first. An agent-mode `AbstractBot` logs one warning at
  `configure()` and never refuses the client.
- **There is no streaming capability flag.** `ask_stream()` may skip the tool loop `ask()` runs — Groq,
  Grok and Meta's Responses path today, tracked as ledger issues.

## Related

- [Per Loop LLM Client Cache](per-loop-cache.md) — how `_ensure_client()` caches one SDK client per loop.
- [OpenAI Compatible Client Base](openai-compatible.md) — the shared base for OpenAI-compatible providers.
- [Question Token Budgets](token-budgets.md) — cumulative budgets enforced on public text methods.
- [Conversation History Ownership](../memory/conversation-history-ownership.md) — why `AbstractBot` owns history and clients stay memory-less.
