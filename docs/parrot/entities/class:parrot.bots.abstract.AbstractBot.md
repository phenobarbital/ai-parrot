---
type: Wiki Entity
title: AbstractBot
id: class:parrot.bots.abstract.AbstractBot
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: AbstractBot.
relates_to:
- concept: class:parrot.bots.stores.local.LocalKBMixin
  rel: extends
- concept: class:parrot.core.events.lifecycle.mixin.EventEmitterMixin
  rel: extends
- concept: class:parrot.interfaces.database.DBInterface
  rel: extends
- concept: class:parrot.interfaces.tools.ToolInterface
  rel: extends
- concept: class:parrot.interfaces.vector.VectorInterface
  rel: extends
- concept: class:parrot.mcp.integration.MCPEnabledMixin
  rel: extends
---

# AbstractBot

Defined in [`parrot.bots.abstract`](../summaries/mod:parrot.bots.abstract.md).

```python
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC)
```

AbstractBot.

This class is an abstract representation a base abstraction for all Chatbots.
Inherits from ToolInterface for tool management and VectorInterface for vector store operations.

## Methods

- `def prompt_pipeline(self) -> Optional['PromptPipeline']`
- `def prompt_pipeline(self, pipeline: 'PromptPipeline')`
- `def status(self) -> AgentStatus` — Get the current status of the agent.
- `def status(self, value: AgentStatus) -> None` — Set the status of the agent and trigger event.
- `def add_event_listener(self, event_name: str, callback: Callable) -> None` — Add a listener for an event.
- `def system_prompt(self) -> str` — Get Current System Prompt Template.
- `def system_prompt(self, value: str) -> None` — Define the system prompt template.
- `def set_program(self, program_slug: str) -> None` — Set the program slug for the bot.
- `def get_vector_store(self)`
- `def define_store_config(self) -> Optional[StoreConfig]` — Override this method to declaratively configure the vector store.
- `def register_kb(self, kb: AbstractKnowledgeBase)` — Register a new knowledge base.
- `def get_policy_rules(self) -> list` — Return policy rules for this bot.
- `def get_supported_models(self) -> List[str]`
- `def llm(self)`
- `def llm(self, model)`
- `def configure_conversation_memory(self) -> None` — Configure the unified conversation memory system.
- `def prompt_builder(self) -> Optional[PromptBuilder]` — Get the composable prompt builder, if set.
- `def prompt_builder(self, builder: PromptBuilder) -> None` — Set the composable prompt builder.
- `async def configure_kb(self)` — Configure Knowledge Base.
- `async def configure(self, app=None) -> None` — Basic Configuration of Bot.
- `async def post_configure(self) -> None` — Hook called at the end of :meth:`configure`.
- `async def warmup_embeddings(self) -> None` — Warm up embedding/KB/vector-store models to avoid first-ask latency.
- `def is_configured(self) -> bool` — Return whether the bot has completed its configuration.
- `def get_conversation_memory(self, storage_type: str='memory', **kwargs) -> ConversationMemory` — Factory function to create conversation memory instances.
- `async def get_conversation_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> Optional[ConversationHistory]` — Get conversation history using unified memory system.
- `async def create_conversation_history(self, user_id: str, session_id: str, metadata: Optional[Dict[str, Any]]=None, chatbot_id: Optional[str]=None) -> ConversationHistory` — Create new conversation history using unified memory system.
- `async def save_conversation_turn(self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str]=None) -> None` — Save a conversation turn using unified memory system.
- `async def clear_conversation_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> bool` — Clear conversation history using unified memory system.
- `async def delete_conversation_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> bool` — Delete conversation history entirely using unified memory system.
- `async def list_user_conversations(self, user_id: str, chatbot_id: Optional[str]=None) -> List[str]` — List all conversation sessions for a user.
- `def configure_store_router(self, config: Any, ontology_resolver: Optional[Any]=None, multi_store_tool: Optional[Any]=None) -> None` — Configure the store-level router for this bot.
- `async def get_vector_context(self, question: str, search_type: str='similarity', search_kwargs: dict=None, metric_type: str='COSINE', limit: int=10, score_threshold: float=None, ensemble_config: dict=None, return_sources: bool=False, expand_to_parent: Optional[bool]=None) -> str` — Get relevant context from vector store.
- `def build_conversation_context(self, history: ConversationHistory, max_chars_per_message: int=200, max_total_chars: int=1500, include_turn_timestamps: bool=False, smart_truncation: bool=True) -> str` — Build conversation context from history using Template to avoid f-string conflicts.
- `def is_agent_mode(self) -> bool` — Check if the bot is configured to operate in agent mode.
- `def is_conversational_mode(self) -> bool` — Check if the bot is configured for pure conversational mode.
- `def get_operation_mode(self) -> str` — Get the current operation mode of the bot.
- `def get_tool(self, tool_name: str) -> Optional[Union[ToolDefinition, AbstractTool]]` — Get a specific tool by name.
- `def list_tool_categories(self) -> List[str]` — List available tool categories.
- `def get_tools_by_category(self, category: str) -> List[str]` — Get tools by category.
- `async def create_system_prompt(self, user_context: str='', vector_context: str='', conversation_context: str='', kb_context: str='', pageindex_context: str='', metadata: Optional[Dict[str, Any]]=None, memory_context: Optional[str]=None, **kwargs) -> 'Union[str, List]'` — Create the complete system prompt for the LLM with user context support.
- `async def get_user_context(self, user_id: str, session_id: str) -> str` — Retrieve user-specific context for the database interaction.
- `async def conversation(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: str='COSINE', use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, return_context: bool=False, memory: Optional[Callable]=None, ensemble_config: dict=None, mode: str='adaptive', ctx: Optional[RequestContext]=None, output_mode: OutputMode=OutputMode.DEFAULT, format_kwargs: dict=None, trace_context: Optional[TraceContext]=None, **kwargs) -> AIMessage` — Conversation method with vector store and history integration.
- `def as_markdown(self, response: AIMessage, return_sources: bool=False, return_context: bool=False, return_tools: bool=False) -> str` — Enhanced markdown formatting with context information.
- `def get_response(self, response: AIMessage, return_sources: bool=True, return_context: bool=False, return_tools: bool=False) -> AIMessage` — Response processing with error handling.
- `async def session(self, ctx: Optional[RequestContext]=None, *, request: 'web.Request'=None, app: Optional[Any]=None, llm: Optional[Any]=None, user_id: Union[str, int, None]=None, session_id: Optional[str]=None, **ctx_kwargs) -> AsyncIterator['AbstractBot']` — Bind a RequestContext to the current asyncio task for the block's lifetime.
- `async def shutdown(self, **kwargs) -> None` — Shutdown.
- `async def invoke(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, use_conversation_history: bool=True, memory: Optional[Callable]=None, ctx: Optional[RequestContext]=None, response_model: Optional[Type[BaseModel]]=None, **kwargs) -> AIMessage` — Simplified conversation method with adaptive mode and conversation history.
- `async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage` — Resume a suspended conversation turn using the underlying client.
- `async def get_conversation_summary(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]` — Get a summary of the conversation history.
- `def get_tools_count(self) -> int` — Get the total number of available tools from LLM client.
- `def has_tools(self) -> bool` — Check if any tools are available via LLM client.
- `def get_available_tools(self) -> List[str]` — Get list of available tool names from LLM client.
- `def register_tools(self, tools: List[Union[ToolDefinition, AbstractTool]]) -> None` — Register multiple tools via LLM client's tool_manager.
- `async def post_login(self, user_context: 'UserContext') -> None` — Per-user initialization hook run after authentication.
- `async def clone_for_user(self, user_context: 'UserContext') -> 'AbstractBot'` — Return an independent agent instance scoped to a single user.
- `async def ask(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: str='COSINE', use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, memory: Optional[Callable]=None, ensemble_config: dict=None, ctx: Optional[RequestContext]=None, structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]]=None, output_mode: OutputMode=OutputMode.DEFAULT, format_kwargs: dict=None, use_tools: bool=True, trace_context: Optional[TraceContext]=None, **kwargs) -> AIMessage` — Ask method with tools always enabled and output formatting support.
- `async def ask_stream(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, search_type: str='similarity', search_kwargs: dict=None, metric_type: str='COSINE', use_vector_context: bool=True, use_conversation_history: bool=True, return_sources: bool=True, memory: Optional[Callable]=None, ensemble_config: dict=None, ctx: Optional[RequestContext]=None, structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]]=None, output_mode: OutputMode=OutputMode.DEFAULT, trace_context: Optional[TraceContext]=None, **kwargs) -> AsyncIterator[Union[str, AIMessage]]` — Stream responses using the same preparation logic as :meth:`ask`.
- `async def get_infographic(self, question: str, template: Optional[str]=None, session_id: Optional[str]=None, user_id: Optional[str]=None, use_vector_context: bool=True, use_conversation_history: bool=False, theme: Optional[str]=None, accept: str='text/html', ctx: Optional[RequestContext]=None, **kwargs) -> AIMessage` — Generate a structured infographic response.
- `async def enhance_infographic(self, *, skeleton: str, brief: str, data_context: 'Dict[str, Any]', js_bundles_available: 'List[Any]') -> str` — Enhance a deterministic infographic skeleton with LLM-generated JS.
- `async def enhance_interactive(self, *, skeleton: str, brief: str, data_context: 'Dict[str, Any]', js_bundles_available: 'List[Any]', library_guide: str='') -> str` — Author a self-contained interactive HTML page from a scaffold skeleton.
- `async def get_interactive(self, question: str, template: str='report', libraries: Optional[List[str]]=None, theme: Optional[str]=None, mode: str='enhance', data_context: Optional['Dict[str, Any]']=None, title: Optional[str]=None) -> AIMessage` — Generate a self-contained interactive HTML page (direct, no persistence).
- `async def cleanup(self) -> None` — Clean up agent resources including KB connections.
