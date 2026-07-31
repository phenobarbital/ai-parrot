---
type: Wiki Entity
title: BasicAgent
id: class:parrot.bots.agent.BasicAgent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Represents an Agent in Navigator.
relates_to:
- concept: class:parrot.bots.chatbot.Chatbot
  rel: extends
- concept: class:parrot.notifications.NotificationMixin
  rel: extends
---

# BasicAgent

Defined in [`parrot.bots.agent`](../summaries/mod:parrot.bots.agent.md).

```python
class BasicAgent(Chatbot, NotificationMixin)
```

Represents an Agent in Navigator.

Agents are chatbots that can access to Tools and execute commands.
Each Agent has a name, a role, a goal, a backstory,
and an optional language model (llm).

These agents are designed to interact with structured and unstructured data sources.

Features:
- Built-in MCP server support (no separate mixin needed)
- Can connect to HTTP, OAuth, API-key authenticated, and local MCP servers
- Automatic tool registration from MCP servers
- Compatible with all existing agent functionality
- Notification capabilities through various channels (e.g., email, Slack, Teams)

## Methods

- `async def handle_files(self, attachments: Dict[str, Any]) -> List[str]` — Handle uploaded files and register them as DataFrames.
- `def agent_tools(self) -> List[AbstractTool]` — Return the agent-specific tools.
- `def set_response(self, response: AgentResponse)` — Set the response for the agent.
- `async def save_document(self, content: str, prefix: str='report', extension: str='txt', directory: Optional[Path]=None, subdir: str='documents') -> None` — Save the document to a file.
- `async def open_prompt(self, prompt_file: str=None) -> str` — Opens a prompt file and returns its content.
- `async def open_query(self, query: str, directory: Optional[Path]=None, **kwargs) -> str` — Opens a query string and formats it with provided keyword arguments.
- `async def generate_report(self, prompt_file: str, save: bool=False, directory: Optional[Path]=None, **kwargs) -> Tuple[AIMessage, AgentResponse]` — Generate a report based on the provided prompt.
- `async def save_transcript(self, transcript: str, filename: str=None, prefix: str='transcript', directory: Optional[str]=None, subdir='transcripts') -> str` — Save the transcript to a file.
- `async def pdf_report(self, content: str, filename_prefix: str='report', directory: Optional[Path]=None, title: str=None, **kwargs) -> str` — Generate a report based on the provided prompt.
- `async def markdown_report(self, content: str, filename: Optional[str]=None, filename_prefix: str='report', directory: Optional[Path]=None, subdir: str='documents', **kwargs) -> str` — Saving Markdown report based on provided file.
- `async def speech_report(self, report: str, max_lines: int=15, num_speakers: int=2, podcast_instructions: Optional[str]='for_podcast.txt', directory: Optional[Path]=None, output_directory: Optional[Path]=None, script_model: Optional[str]=None, tts_model: Optional[str]=None, **kwargs) -> Dict[str, Any]` — Generate a Transcript Report and a Podcast based on findings.
- `async def report(self, prompt_file: str, **kwargs) -> AgentResponse` — Generate a report based on the provided prompt.
- `async def generate_presentation(self, content: str, filename_prefix: str='report', template_name: Optional[str]=None, pptx_template: str='corporate_template.pptx', output_dir: Optional[Path]=None, title: str=None, **kwargs)` — Generate a PowerPoint presentation using the provided tool.
- `async def create_speech(self, content: str, language: str='en-US', only_script: bool=False, **kwargs) -> Dict[str, Any]` — Generate a Transcript Report and a Podcast based on findings.
- `async def add_mcp_server(self, config: MCPServerConfig) -> List[str]` — Add an MCP server and register its tools.
- `async def add_mcp_server_url(self, name: str, url: str, auth_type: Optional[str]=None, auth_config: Optional[Dict[str, Any]]=None, headers: Optional[Dict[str, str]]=None, allowed_tools: Optional[List[str]]=None, blocked_tools: Optional[List[str]]=None, **kwargs) -> List[str]` — Convenience method to add a public URL-based MCP server.
- `async def add_local_mcp_server(self, name: str, script_path: Union[str, Path], interpreter: str='python', **kwargs) -> List[str]` — Add a local stdio MCP server.
- `async def add_http_mcp_server(self, name: str, url: str, auth_type: Optional[str]=None, auth_config: Optional[Dict[str, Any]]=None, headers: Optional[Dict[str, str]]=None, **kwargs) -> List[str]` — Add an HTTP MCP server with optional authentication.
- `async def add_api_key_mcp_server(self, name: str, url: str, api_key: str, header_name: str='X-API-Key', use_bearer_prefix: bool=False, **kwargs) -> List[str]` — Add an API-key authenticated MCP server.
- `async def remove_mcp_server(self, server_name: str)` — Remove an MCP server and unregister its tools.
- `def list_mcp_servers(self) -> List[str]` — List all connected MCP servers.
- `def get_mcp_client(self, server_name: str)` — Get the MCP client for a specific server.
- `async def shutdown(self, **kwargs)` — Shutdown the agent and disconnect all MCP servers.
- `def as_tool(self, tool_name: str=None, tool_description: str=None, use_conversation_method: bool=True, context_filter: Optional[Callable[[AgentContext], AgentContext]]=None) -> 'AgentTool'` — Convert this agent into an AgentTool that can be used by other agents.
- `def register_as_tool(self, target_agent: 'BasicAgent', tool_name: str=None, tool_description: str=None, **kwargs) -> None` — Register this agent as a tool in another agent's tool manager.
- `def add_dataframe(self, df, name: str=None)` — Add a dataframe to the agent and configure PythonPandasTool.
- `async def create_system_prompt(self, **kwargs)`
- `def remove_dataframe(self, name: str)` — Remove a dataframe by name.
- `async def followup(self, question: str, turn_id: str, data: Any, session_id: Optional[str]=None, user_id: Optional[str]=None, use_conversation_history: bool=True, memory: Optional[Any]=None, ctx: Optional[Any]=None, structured_output: Optional[Any]=None, output_mode: Any=None, format_kwargs: dict=None, return_structured: bool=True, **kwargs) -> AIMessage` — Generate a follow-up question using a previous turn as context.
