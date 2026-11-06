---
title: "Agents and Chatbots: The Bot Class Hierarchy"
summary: "How AbstractBot, BaseBot, Chatbot, BasicAgent and Agent fit together, how they are configured, how an ask() call flows, and how bots are registered with @register_agent."
---

# Agents and Chatbots: The Bot Class Hierarchy

## Purpose

Every conversational component in AI-Parrot is a *bot*: a Python object that
owns a system prompt, an LLM client, a `ToolManager`, optional knowledge-base /
vector-store access, and the conversation history for its sessions. The classes
live under `packages/ai-parrot/src/parrot/bots/` and form a single inheritance
chain:

```
AbstractBot            parrot/bots/abstract.py   (config, tools, prompts, memory ownership)
  └─ BaseBot           parrot/bots/base.py       (concrete ask / ask_stream / invoke / conversation)
       └─ Chatbot      parrot/bots/chatbot.py    (database or manual configuration)
            └─ BasicAgent   parrot/bots/agent.py (tools, MCP, notifications, dataframes)
                 └─ Agent                        (BasicAgent with an empty agent_tools())
```

Use `Chatbot` for a conversational bot, and `Agent` (or a subclass of it) when
the bot should call tools. Concrete specialised bots (`WebAgent`, `InfoAgent`,
`VoiceBot`, the Jira/GitHub/Fireflies agents, ...) are further subclasses in the
same package. `parrot.bots` imports only the base hierarchy eagerly
(`AbstractBot`, `BaseBot`, `BasicAgent`, `Agent`); `Chatbot`, `BasicBot`,
`WebAgent`, `WebSearchAgent`, `VoiceBot` and `InfoAgent` are resolved lazily on
first attribute access through a module-level `__getattr__`.

`AbstractBot` is the sole owner of conversation history: it loads and renders
history, hands it to the LLM client, and is the only writer of turns. Clients
are memory-less.

## Public API

- [`parrot.bots.abstract`](ref:parrot.bots.abstract) — `AbstractBot`, the ABC every bot derives from. Defines `configure()`, `get_client()`, `register_tools()`, `conversation()`, `invoke()`, `shutdown()`, `cleanup()` and the abstract `ask()` / `ask_stream()` signatures.
- [`parrot.bots.base`](ref:parrot.bots.base) — `BaseBot`, the concrete implementation of `ask()`, `ask_stream()`, `invoke()`, `conversation()` and the `chat()` alias.
- [`parrot.bots.chatbot`](ref:parrot.bots.chatbot) — `Chatbot`, which resolves its configuration from the database (`from_database=True`) or manually (`from_manual_config()`).
- [`parrot.bots.agent`](ref:parrot.bots.agent) — `BasicAgent` and `Agent`: tool-using bots with MCP support, answer memory and notification capabilities.
- [`parrot.bots`](ref:parrot.bots) — package facade exporting `AbstractBot`, `BaseBot`, `BasicAgent`, `Agent` and the lazy `Chatbot`, `BasicBot`, `WebAgent`, `WebSearchAgent`, `VoiceBot`, `InfoAgent`.
- [`parrot.registry`](ref:parrot.registry) — the global `agent_registry`, the `register_agent` decorator, `AgentRegistry`, `BotConfig`, `BotMetadata`, `AgentKind`.
- [`parrot.registry.registry`](ref:parrot.registry.registry) — implementation of `AgentRegistry` (`register`, `register_instance`, `get_instance`, `register_bot_decorator`, `instantiate_startup_agents`).

Key methods on `AbstractBot` / `BaseBot`:

| Method | Notes |
|---|---|
| `async configure(self, app=None) -> None` | Idempotent async setup; see lifecycle below. |
| `async ask(self, question, session_id=None, user_id=None, ..., use_tools=True, **kwargs) -> AIMessage` | One question, one `AIMessage`. |
| `async ask_stream(self, question, session_id=None, user_id=None, ...)` | Streaming counterpart. |
| `async conversation(self, question, session_id=None, user_id=None, ..., mode="adaptive", ...)` | Conversational entry point with history. |
| `async invoke(...)` | Stateless call to the LLM (no conversation turn). |
| `register_tools(self, tools)` | Delegates to `self.tool_manager.register_tools(tools)`. |
| `get_client(self) -> AbstractClient` | The LLM client in use (a hook used by mixins such as model switching). |
| `async shutdown(self, **kwargs)` / `async cleanup(self)` | Teardown hooks. |

## Configuration & Parameters

### Constructor (`AbstractBot.__init__`)

The main keyword arguments (all verified in the signature):

| Parameter | Default | Meaning |
|---|---|---|
| `name` | `"Nav"` | Bot name. |
| `system_prompt` | `None` | Custom system prompt (otherwise the class `system_prompt_template`). |
| `llm` | `None` | `"provider:model"` string, provider string, client class or `AbstractClient` instance. |
| `instructions` | `None` | Extra instructions appended to the system prompt. |
| `tools` | `None` | List of tool names, `AbstractTool` or `ToolDefinition` objects. |
| `tool_threshold` | `0.7` | Confidence threshold for tool usage. |
| `use_kb` / `local_kb` | `False` | Enable knowledge bases. |
| `strict_mode`, `block_on_threat`, `injection_detection`, `injection_probability_threshold` | `True`, `False`, `True`, `0.98` | Prompt-injection and security behaviour. |
| `output_mode` | `OutputMode.DEFAULT` | Default output formatting. |
| `include_search_tool` | `False` | Include the `search_tools` meta-tool. |
| `prompt_builder` / `prompt_preset` | `None` | Composable prompt layers; `prompt_builder` wins over `prompt_preset`. |
| `guardrails` | `None` | Names, dicts or `Guardrail` instances for the unified guardrail pipelines. |
| `warmup_on_configure`, `debug`, `event_bus` | `False`, `False`, `None` | Misc. runtime switches. |

Extra `**kwargs` are consumed by subclasses.

### Subclass defaults

- `Chatbot.__init__(name="Nav", system_prompt=None, human_prompt=None, from_database=True, tools=None, **kwargs)`. It also reads `threshold`, `max_tools` (default 10), `documents_dir` and `company_information` from kwargs.
- `BasicAgent.__init__(name="Agent", agent_id="agent", use_llm="google", llm=None, tools=None, system_prompt=None, human_prompt=None, use_tools=True, instructions=None, dataframes=None, **kwargs)`. When `system_prompt` is not given it defaults to `PromptBuilder.agent()`; `instructions` is stored as the agent `goal`. With `use_tools=True` a `ToJsonTool` is appended to the tool list. When no `llm` is supplied it falls back to `GoogleGenAIClient`.
- Agent-specific tools are contributed by overriding `agent_tools(self) -> List[AbstractTool]`; they are added to `self.tools` and registered on the `tool_manager` during `__init__`. `Agent.agent_tools()` returns `[]`.

### Configuration lifecycle

`configure(app=None)` is idempotent per instance: a repeat call with the same app object is a no-op. `Chatbot.configure()` first tries `bot_exists(...)` and `from_database(bot)`; if the database is unavailable or the bot is not stored, it logs a message, sets `_from_database = False` and calls `from_manual_config()`, which fills defaults for `description`, `role`, `goal`, `rationale`, `backstory`, `capabilities`, LLM temperature/tokens and tool thresholds from class attributes. `BasicAgent.configure()` calls `super().configure(app)` and then wires REPL/pandas namespaces into any registered `WorkingMemoryToolkit`. The full contract (guards, `configure_is_noop`, `configure_skipped`) is documented in [Agent configure lifecycle](agent-configure-lifecycle.md).

### Request flow

1. A caller (HTTP handler, integration, another agent, your code) awaits `bot.ask(question, session_id=..., user_id=...)`.
2. `BaseBot.ask()` emits invoke lifecycle events, runs the guardrail / injection checks, loads and renders history, optionally pulls vector-store context (`use_vector_context`), and builds the system prompt.
3. The prompt, history and the `ToolManager`'s tools go to the resolved `AbstractClient`; tool calls are executed by the client loop and results fed back.
4. The result is formatted according to `output_mode` and returned as an `AIMessage`; the turn is persisted through `AbstractBot`.

## Usage Examples

A conversational bot, configured manually without a database:

```python
import asyncio
from parrot.bots import Chatbot


async def main() -> None:
    bot = Chatbot(
        name="HelpDesk",
        llm="google",
        system_prompt="You are a concise internal help desk assistant.",
        from_database=False,
    )
    await bot.configure()
    response = await bot.ask("How do I reset my VPN token?", session_id="s1", user_id="u1")
    print(response.content)


asyncio.run(main())
```

A tool-using agent with its own tools and a registry entry:

```python
from typing import List

from parrot.bots import Agent
from parrot.registry import register_agent
from parrot.tools.abstract import AbstractTool


@register_agent(name="ReportAgent", at_startup=True, tags=["reports"])
class ReportAgent(Agent):
    """Agent that drafts weekly reports."""

    def agent_tools(self) -> List[AbstractTool]:
        # Return concrete AbstractTool instances (see the toolkits wiki pages).
        return []
```

Registering a bot with the decorator immediately calls `AgentRegistry.register()`. The decorator accepts `name`, `priority`, `dependencies`, `singleton`, `at_startup`, `startup_config`, `tags` and `roost`, and raises `TypeError` when applied to something that is not a subclass of `AbstractBot`. If the class body defines a string `model` attribute, the registry also records a `ModelConfig` for it (provider `google`, taking `max_tokens` and `temperature` from the class when present).

Streaming a response:

```python
async for chunk in bot.ask_stream("Summarise the incident report", session_id="s1", user_id="u1"):
    if isinstance(chunk, str):
        print(chunk, end="", flush=True)
```

`ask_stream()` is annotated as `AsyncIterator[Union[str, AIMessage]]`, so a stream may end with a final `AIMessage` object rather than a text chunk.

## Gotchas

- **`from_database` defaults to `True` on `Chatbot`.** Without a configured DSN the database lookup fails and the bot silently falls back to manual configuration (a warning is logged). Pass `from_database=False` for deterministic, self-contained bots.
- **Always `await bot.configure()`** before the first call when you build a bot yourself. `BotManager`-style hosts do this for you; scripts do not.
- **`configure()` overrides must respect the idempotency guards.** Overrides that run work after `super().configure(app)` should check `self.configure_skipped`; do not rely on `configure_count > 1`.
- **`llm` vs `use_llm`.** `AbstractBot` and `Chatbot` use `llm`; `BasicAgent` additionally accepts `use_llm="google"`, which is only a provider hint. Prefer the explicit `"provider:model"` form in `llm`.
- **`ask()` in `AbstractBot` is abstract.** The concrete implementation, including event emission and `trace_context` handling, lives in `BaseBot`; subclass `BaseBot` (or `Chatbot`/`Agent`) rather than `AbstractBot` unless you intend to replace the whole pipeline.
- **No arbitrary Python execution by default.** `BasicAgent` deliberately does not add a Python REPL tool; wire one explicitly if (and only if) the agent is trusted.
- **Do not mutate shared class attributes.** `BasicAgent` copies `speech_tts_options` per instance for this reason; follow the same pattern for any dict/list class defaults you add.
- **`@register_agent` requires an `AbstractBot` subclass**; decorating a plain class raises `TypeError` at import time.
- Never call provider SDKs from a bot; go through the `AbstractClient` chosen by `llm`.

## Related

- [Agent configure lifecycle](agent-configure-lifecycle.md) — idempotent `configure()` contract and subclass guards.
- [Agent](agent.md) — deeper notes on the agent class.
- [AgentCrew](orchestration/agentcrew.md) — running several agents sequentially, in parallel, or as a DAG.
- [AgentsFlow](orchestration/agentsflow.md) — event-driven DAG orchestration of agents.
- [Exposing an agent as an MCP server](mcp/agent-as-mcp-server.md) — publishing a bot over MCP.
- [Agent security guardrails](security/agent-security-guardrails.md) — the guardrail pipelines that bots consult.
