---
type: Wiki Entity
title: AgentHandler
id: class:parrot.handlers.agents.abstract.AgentHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract class for chatbot/agent handlers.
---

# AgentHandler

Defined in [`parrot.handlers.agents.abstract`](../summaries/mod:parrot.handlers.agents.abstract.md).

```python
class AgentHandler(BaseView)
```

Abstract class for chatbot/agent handlers.

Provide a complete abstraction for exposing AI Agents as a REST API.

## Methods

- `def set_program(self, program_slug: str) -> None` — Set the program slug for the agent.
- `def setup(self, app: Union[WebApp, web.Application], route: List[Dict[Any, str]]=None) -> None` — Setup the handler with the application and route.
- `async def create_agent(self, app: web.Application)`
- `def define_tools(self)` — Define additional tools for the agent.
- `def db_connection(self, driver: str='pg', dsn: str=None, credentials: dict=None) -> AsyncDB` — Return a database connection.
- `async def register_background_task(self, task: Callable[..., Awaitable], request: web.Request=None, done_callback: Optional[Callable[..., Awaitable]]=None, *args, **kwargs) -> JobRecord` — Register a background task with the BackgroundService.
- `async def find_jobs(self, request: web.Request) -> web.Response` — Return Jobs by User.
- `async def get_task_status(self, task_id: str, request: web.Request=None) -> JSONResponse` — Get the status of a background task by its ID.
- `def add_route(self, method: str, path: str, handler: str)` — Instance method to add custom routes.
- `def create_temp_directory(self, name: str='documents')` — Create the temporary directory for saving Agent Documents.
- `async def get_user_session(self)` — Return the user session from the request.
- `def get_userid(self, session: Optional[Dict[str, Any]]=None, idx: str='user_id') -> Optional[str]` — Return the user ID from the session.
- `def service_auth(fn: Union[Any, Any]) -> Any` — Decorator to ensure the service is authenticated.
- `def get_agent(self) -> Any` — Return the agent instance.
- `async def send_notification(self, content: str, provider: str='telegram', recipients: Union[List[dict], dict]=None, **kwargs) -> Any` — Return the notification provider instance.
- `async def open_prompt(self, prompt_file: str=None) -> str` — Opens a prompt file and returns its content.
- `async def ask_agent(self, query: str=None, prompt_file: str=None, *args, **kwargs) -> Tuple[AgentResponse, AIMessage]` — Asks the agent a question and returns the response.
