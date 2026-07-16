---
type: Wiki Entity
title: BotManager
id: class:parrot.manager.manager.BotManager
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: BotManager.
---

# BotManager

Defined in [`parrot.manager.manager`](../summaries/mod:parrot.manager.manager.md).

```python
class BotManager
```

BotManager.

Manage Bots/Agents and interact with them through via aiohttp App.
Deploy and manage chatbots and agents using a RESTful API.

## Methods

- `def get_bot_class(self, bot_name: str) -> Optional[Type]` — Get bot class by name, searching in:
- `def get_or_create_bot(self, bot_name: str, **kwargs)` — Get existing bot or create new one from class name.
- `async def load_bots(self, app: web.Application) -> None` — Load and register all bots using the registry and optional database.
- `def create_bot(self, class_name: Any=None, name: str=None, **kwargs) -> AbstractBot` — Create a Bot and add it to the manager.
- `def add_bot(self, bot: AbstractBot) -> None` — Add a Bot to the manager.
- `async def get_bot(self, name: str, new: bool=False, session_id: str='', request: Optional[web.Request]=None, **kwargs) -> AbstractBot` — Get a Bot by name.
- `def remove_bot(self, name: str) -> None` — Remove a Bot by name.
- `async def get_user_bot(self, request: web.Request, chatbot_id: Any) -> Optional[AbstractBot]` — Resolve a user-defined bot via session cache → DB load → instantiate.
- `def invalidate_user_bot(cls, session: Any, chatbot_id: Any) -> None` — Drop a user-bot from the session cache (used after PATCH/DELETE).
- `def get_bots(self) -> Dict[str, AbstractBot]` — Get all Bots declared on Manager.
- `async def create_agent(self, class_name: Any=None, name: str=None, **kwargs) -> AbstractBot`
- `def add_agent(self, agent: AbstractBot) -> None` — Add a Agent to the manager.
- `def remove_agent(self, agent: AbstractBot) -> None` — Remove a Bot by name.
- `async def create_ephemeral_user_bot(self, user_id: Optional[int]=None, config: Optional[Dict[str, Any]]=None, uploaded_paths: Optional[List[dict]]=None, *, owner_id: Optional[str]=None, owner_kind: str='user', ttl_seconds: int=86400)` — Create an ephemeral (in-memory-only) user bot and schedule warm-up.
- `async def save_user_bot(self, model: 'UserBotModel') -> 'UserBotModel'` — INSERT a ``UserBotModel`` row into ``navigator.users_bots``.
- `async def promote_user_bot(self, chatbot_id: str, user_id: int) -> 'UserBotModel'` — Promote an ephemeral bot to a persisted ``navigator.users_bots`` row.
- `def get_ephemeral_status(self, chatbot_id: str, user_id: Optional[int]=None, *, owner_id: Optional[str]=None)` — Return the ``EphemeralAgentStatus`` for *chatbot_id* owned by the given owner.
- `async def discard_ephemeral_user_bot(self, chatbot_id: str, user_id: Optional[int]=None, *, owner_id: Optional[str]=None) -> bool` — Remove an ephemeral bot from memory and clean up its resources.
- `async def save_agent(self, name: str, **kwargs) -> None` — Save a Agent to the DB.
- `def get_app(self) -> web.Application` — Get the app.
- `def setup(self, app: web.Application) -> web.Application`
- `async def on_startup(self, app: web.Application) -> None` — On startup.
- `async def on_shutdown(self, app: web.Application) -> None` — On shutdown.
- `async def add_crew(self, name: str, crew: AgentCrew, crew_def: CrewDefinition) -> None` — Register a crew in the manager and persist to Redis.
- `async def get_crew(self, identifier: str, as_new: bool=False, tenant: Optional[str]=None) -> Optional[Tuple[AgentCrew, CrewDefinition]]` — Get a crew by name or ID. Loads from Redis if not in memory.
- `def list_crews(self, tenant: Optional[str]=None) -> Dict[str, Tuple[AgentCrew, CrewDefinition]]` — List all registered crews.
- `async def remove_crew(self, identifier: str, tenant: Optional[str]=None) -> bool` — Remove a crew from the manager and Redis.
- `def update_crew(self, identifier: str, crew: AgentCrew, crew_def: CrewDefinition) -> bool` — Update an existing crew.
- `async def load_crews(self) -> None` — Load all crews from Redis on startup.
- `async def sync_crews(self) -> None` — Synchronize in-memory crews with Redis.
- `def get_crew_stats(self) -> Dict[str, Any]` — Get statistics about registered crews.
