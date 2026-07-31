---
type: Wiki Entity
title: ToolInterface
id: class:parrot.interfaces.tools.ToolInterface
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Interface for tool management in bot implementations.
---

# ToolInterface

Defined in [`parrot.interfaces.tools`](../summaries/mod:parrot.interfaces.tools.md).

```python
class ToolInterface
```

Interface for tool management in bot implementations.

This interface provides methods for:
- Initializing and registering tools
- Syncing tools with LLM clients
- Determining when to use tools
- Validating tools
- Configuring LLM clients

## Methods

- `def pageindex_toolkit(self) -> Any` — The bot's ``PageIndexToolkit`` instance, or ``None``.
- `def graphindex_toolkit(self) -> Any` — The bot's ``GraphIndexToolkit`` instance, or ``None``.
- `def graphindex_builder(self) -> Any` — Optional ``GraphIndexBuilder`` enabling document ingestion.
- `def has_pageindex_tools(self) -> bool` — Whether this bot has PageIndex tools incorporated.
- `def has_graphindex_tools(self) -> bool` — Whether this bot has GraphIndex tools incorporated.
- `def llmwiki_toolkit(self) -> Any` — The bot's ``LLMWikiToolkit`` instance, or ``None``.
- `def has_llmwiki_tools(self) -> bool` — Whether this bot has LLM Wiki tools incorporated.
- `def has_knowledge_index(self) -> bool` — Whether the bot exposes any knowledge index (Page or Graph).
- `def sync_tools(self, llm: AbstractClient=None) -> None` — Assign Bot's ToolManager as a reference to LLM's ToolManager.
- `def get_tools_summary(self) -> Dict[str, Any]` — Get a comprehensive summary of available tools and configuration.
- `def validate_tools(self) -> Dict[str, Any]` — Validate all registered tools.
- `def register_tool(self, tool: Union[ToolDefinition, AbstractTool]=None, name: str=None, description: str=None, input_schema: Dict[str, Any]=None, function: Callable=None) -> None` — Register a tool in the shared ToolManager.
- `def configure_llm(self, llm: Union[str, Callable]=None, **kwargs) -> AbstractClient` — Configuration of LLM at runtime (during conversation/ask methods)
- `def llm_chain(self, llm: str='vertexai', model: str=None, **kwargs) -> AbstractClient` — llm_chain.
