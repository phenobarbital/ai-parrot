---
title: "Server Layer: BotManager and HTTP Handlers"
summary: "How the aiohttp server layer is wired: BotManager lifecycle and route registration, how chat/agent/crew/infographic/studio handlers resolve a bot, and how tenant and session identity are handled."
---

# Server Layer: BotManager and HTTP Handlers

## Purpose

The server layer turns registered bots, agents and crews into an HTTP API. It
ships in the `ai-parrot-server` distribution and contributes to the shared
`parrot.*` namespace (PEP 420 / `pkgutil.extend_path`): `parrot.manager`,
`parrot.handlers` and a small `parrot.server` package that only holds the
distribution version.

The stack is **aiohttp + navigator-api served by gunicorn** (aiohttp worker).
There is no ASGI stack: handlers are `BaseView` subclasses (aiohttp class
based views) registered with `router.add_view(...)`.

Two pieces cooperate:

- **`BotManager`** owns the in-memory bot collection (`_bots`), the agent
  registry, optional database bots and crews, and the shared Redis client. Its
  `setup(app)` method mounts every route and its startup hooks load the bots.
- **Handlers** are thin request adapters. They find the manager at
  `app["bot_manager"]`, resolve a bot by name, apply PBAC and tenant/session
  rules, then call the bot (`ask`, streaming, a named method, ...).

Use this page to understand where an incoming request goes before it reaches
an `AbstractBot`.

## Public API

- `parrot.manager` — package facade. Lazily exports `BotManager`, `EphemeralRegistry` and `EphemeralAgentStatus` (raises an install hint if `ai-parrot-server` is missing).
- [`parrot.manager.manager`](ref:parrot.manager.manager) — defines `BotManager`, `ReloadResult`, `AgentNotFoundError` and `AgentReloadError`.
- `parrot.handlers` — package with lazy exports such as `ChatbotHandler`, `BotConfigHandler`, `DatasetManagerHandler`, `VectorStoreHandler`.
- [`parrot.handlers.chat`](ref:parrot.handlers.chat) — `ChatHandler` (chat with a named chatbot), `BotHandler`, `BotManagement`.
- [`parrot.handlers.agent`](ref:parrot.handlers.agent) — `AgentTalk`, the universal agent conversation handler (POST chat, PATCH tool configuration).
- [`parrot.handlers.infographic`](ref:parrot.handlers.infographic) — `InfographicTalk(AgentTalk)`: infographic generation, templates, themes, render jobs.
- [`parrot.handlers.crew`](ref:parrot.handlers.crew) — `CrewHandler`, `CrewExecutionHandler`, `CrewExecutionHistoryHandler`, `CrewToolCatalogHandler`, `CrewSpecialNodeCatalogHandler`.
- [`parrot.handlers.studio`](ref:parrot.handlers.studio) — Agent Studio route registration: `setup_studio_routes`, `STUDIO_PREFIX`.
- [`parrot.handlers.scope`](ref:parrot.handlers.scope) — `RequestScope`, `ScopeResolver`, `SessionScopeResolver`, `get_scope_resolver`, `resolve_request_tenant`.
- `parrot.server` — distribution metadata only (`__version__`).

Key `BotManager` methods (all verified in `manager/manager.py`):

| Member | Role |
|---|---|
| `setup(app, *, agent_mount_config=None, ..., studio_routes=True)` | Registers hooks, shared Redis, all routes; stores `app["bot_manager"] = self`. |
| `load_bots(app)` | Called from `on_startup`; loads registry, database and (optionally) crew bots. |
| `get_bot(name, new=False, session_id="", request=None, **kwargs)` | Resolve a bot by name (async). |
| `get_user_bot(request, chatbot_id)` | Resolve a per-user bot: session cache, then `navigator.users_bots`. |
| `get_studio_bot(key, *, new=False, session_id="", request=None)` | Resolve an Agent Studio agent from the Studio runtime cache. |
| `add_bot(bot)` / `remove_bot(name)` / `create_bot(...)` / `get_bots()` | Programmatic management of the in-memory collection. |
| `get_crew(identifier, as_new=False, tenant=None)` / `add_crew(...)` / `load_crews()` | Crew lookup and persistence (Redis backed). |

## Configuration & Parameters

`BotManager.__init__` flags (defaults come from `parrot.conf`):

| Argument | Default source | Effect |
|---|---|---|
| `enable_database_bots` | `ENABLE_DATABASE_BOTS` (False) | Load bots from the database during startup. |
| `enable_crews` | `ENABLE_CREWS` (False) | Create `CrewRedis` and call `load_crews()`. |
| `enable_registry_bots` | `ENABLE_REGISTRY_BOTS` (True) | Run the `AgentRegistry` discovery/instantiation pipeline. |
| `enable_experts` | `True` | Load domain experts during registry discovery. |
| `enable_swagger_api` | `ENABLE_SWAGGER` (False) | Register OpenAPI/Swagger routes. |

Note that the crew routes inside `setup()` are guarded by the module level
`ENABLE_CREWS` constant, not by the instance flag.

Route registration inside `BotManager.setup()` (selected, verified):

| Route | View |
|---|---|
| `/api/v1/chats`, `/api/v1/chat/{chatbot_name}`, `/api/v1/chat/{chatbot_name}/{method_name}` | `ChatHandler` |
| `/api/v1/agents/chat/{agent_id}`, `/api/v1/agents/chat/{agent_id}/{method_name}` | `AgentTalk` |
| `/api/v1/agents/infographic/{agent_id}` plus `{resource:templates}`, `{resource:themes}`, `{resource:render}` shapes | `InfographicTalk` |
| `/api/v1/infographic_recipes`, `/{name}`, `/{name}/run` | `RecipeHandler` |
| `/api/v1/chatbots`, `/api/v1/chatbots/{name}` | `BotHandler` |
| `/api/v1/agents/config`, `/api/v1/agents/config/{agent_name}` | `BotConfigHandler` |
| `/api/v1/crew`, `/api/v1/crews`, `/api/v1/crew/executions` (when `ENABLE_CREWS`) | `CrewHandler.configure`, `CrewExecutionHandler.configure`, `CrewExecutionHistoryHandler.configure` |
| `/api/v1/astudio/*` (unless `studio_routes=False`) | `setup_studio_routes(app)` |

Literal sub-routes are registered before catch-all patterns on purpose: the
crew special-node and execution-history routes precede `CrewHandler.configure`
because its `{id:.*}` pattern would otherwise swallow them, and the infographic
literal `templates`/`themes`/`render` routes precede `{agent_id}`.

Agent Studio is mounted under `STUDIO_PREFIX = "/api/v1/astudio"`.
`setup_studio_routes(app, *, prefix=None, view_wrapper=None)` accepts a prefix
containing `{tenant}`, so a host can mount Studio itself under a tenant prefix
(call `BotManager.setup(app, studio_routes=False)` first). Mounting the same
prefix twice is a logged no-op.

## Usage Examples

Mount the manager on an aiohttp application:

```python
from aiohttp import web
from parrot.manager import BotManager


def create_app() -> web.Application:
    app = web.Application()
    manager = BotManager(enable_crews=False, enable_registry_bots=True)
    manager.setup(app)  # registers routes, startup/cleanup hooks, app["bot_manager"]
    return app
```

Resolve a bot programmatically from inside a handler or startup hook (no
`request`, so no PBAC check is applied):

```python
from parrot.manager import BotManager


async def ask_agent(manager: BotManager, name: str, question: str):
    bot = await manager.get_bot(name)
    if bot is None:
        raise LookupError(f"Agent {name!r} not found")
    return await bot.ask(question)
```

Call an agent over HTTP with `aiohttp` (body keys as documented on
`AgentTalk.post`):

```python
import aiohttp


async def chat(base_url: str, token: str, agent_id: str, query: str) -> dict:
    url = f"{base_url}/api/v1/agents/chat/{agent_id}"
    payload = {"query": query, "session_id": "conv-123", "output_mode": "json"}
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as http:
        async with http.post(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()
```

### How a handler resolves and calls a bot

`AgentTalk.post` (`POST /api/v1/agents/chat/{agent_id}`):

1. PBAC guard via `_check_pbac_agent_access` (action `agent:chat`; fails open when PBAC is not configured).
2. Body is read from a multipart upload (`handle_upload`) or falls back to JSON.
3. `_get_user_session(data)` yields `(user_id, session_id)`; `session_id` comes from the body, otherwise a new one is generated (the browser session is deliberately not reused, to avoid mixing histories).
4. `_resolve_bot(data)` first tries `manager.get_user_bot(request, name)` and then `manager.get_bot(name)`; a missing manager returns 500, a missing bot returns 404.
5. The tenant is resolved server side (see below), session scoped tools from a prior PATCH are swapped in, then the bot is invoked with `query`, `output_mode`, `stream`, `search_type`, and similar keys popped from the body.

`ChatHandler.post` follows the same shape: `app["bot_manager"]`, then
`get_user_bot` and `get_bot`, a required request session (400 otherwise), and
`async with chatbot.session(request=..., app=..., llm=...)` around the call.

Inside `BotManager.get_bot`, names starting with a Studio prefix return `None`
(Studio ids never resolve on the legacy path). Otherwise it checks `_bots`,
then the `AgentRegistry` (`registry.get_instance`, configured on demand and
added via `add_bot`), and finally a global Studio fallback. `new=True` clones
LLM, tools and vector store configuration from the base bot into a temporary
instance named `{name}_{session_id}` that expires after one hour. When
`request` is supplied, `enforce_agent_access` runs PBAC before the bot is
returned; `AgentAccessDenied` propagates.

### Tenant and session handling

- The tenant is **never** taken from client input. Both `ChatHandler` and `AgentTalk` pop a client supplied `tenant` from the body, log a warning and call `resolve_request_tenant(app, request)`.
- `resolve_request_tenant` returns `None` (global view) unless a host installed a resolver at `app["scope_resolver"]` (legacy key `app["ui_surfaces_scope_resolver"]`). Denials (`web.HTTPException`) are re-raised; other resolver errors fall back to `None`.
- The default `SessionScopeResolver` reads the navigator-auth session object and yields a tenant only when `programs` has exactly one entry.
- `BotManager` itself keys crews as `"{tenant}:{name}"` with `"global"` as the default tenant.

## Gotchas

- `BotManager.get_bot` is a coroutine; forgetting `await` returns a coroutine, not a bot.
- Without `request`, `get_bot` skips PBAC. Pass the request in any HTTP path.
- `get_bot` returns `None` for unknown names rather than raising; handlers convert that to a 404. `PBAC` denial raises `AgentAccessDenied`.
- `new=True` bots are registered in `_bots` with a one hour expiry; they leak into `get_bots()` until cleaned up.
- Studio agents live only in the Studio runtime cache. `add_bot` raises `ValueError` for them.
- Route order matters in aiohttp: register literal paths before `{name}` or `{id:.*}` patterns, as `setup()` does.
- Deprecated: passing `tools`, `mcp_servers` or `tool_config` in the `AgentTalk` POST body is stripped with a warning; configure them with PATCH on the same URL.
- `parrot.handlers.__init__` exports lazily to avoid circular imports; import from the concrete module (for example `parrot.handlers.chat`) in new code.
- Installing only core `ai-parrot` makes `parrot.manager.BotManager` raise an install hint for `ai-parrot-server`.

## Related

- [Infographic Handler Frontend API Contract](infographic_handler_api.md) — full endpoint map for `InfographicTalk`.
- [Admin UI](admin-ui.md) — the web UI that consumes these endpoints.
- [API Endpoints](API_ENDPOINTS.md) — HTTP endpoint notes for the server.
