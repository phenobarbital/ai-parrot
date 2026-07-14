---
type: Wiki Overview
title: 'Migration — FEAT-203: ai-parrot-server'
id: doc:docs-migration-feat-203-ai-parrot-server-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: BotManager, MCP/A2A server transports, scheduler, or autonomous orchestrator.
relates_to:
- concept: mod:parrot.a2a
  rel: mentions
- concept: mod:parrot.a2a.client
  rel: mentions
- concept: mod:parrot.a2a.mesh
  rel: mentions
- concept: mod:parrot.a2a.models
  rel: mentions
- concept: mod:parrot.a2a.orchestrator
  rel: mentions
- concept: mod:parrot.a2a.router
  rel: mentions
- concept: mod:parrot.a2a.security
  rel: mentions
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.core
  rel: mentions
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.handlers.bots
  rel: mentions
- concept: mod:parrot.handlers.credentials_utils
  rel: mentions
- concept: mod:parrot.handlers.vault_utils
  rel: mentions
- concept: mod:parrot.loaders
  rel: mentions
- concept: mod:parrot.manager
  rel: mentions
- concept: mod:parrot.mcp
  rel: mentions
- concept: mod:parrot.mcp.client
  rel: mentions
- concept: mod:parrot.mcp.config
  rel: mentions
- concept: mod:parrot.mcp.context
  rel: mentions
- concept: mod:parrot.mcp.integration
  rel: mentions
- concept: mod:parrot.mcp.oauth
  rel: mentions
- concept: mod:parrot.mcp.oauth_server
  rel: mentions
- concept: mod:parrot.mcp.parrot_server
  rel: mentions
- concept: mod:parrot.mcp.registry
  rel: mentions
- concept: mod:parrot.mcp.server
  rel: mentions
- concept: mod:parrot.mcp.simple_server
  rel: mentions
- concept: mod:parrot.memory
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.scheduler
  rel: mentions
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.security.credentials_utils
  rel: mentions
- concept: mod:parrot.security.vault_utils
  rel: mentions
- concept: mod:parrot.services
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
---

# Migration — FEAT-203: ai-parrot-server

**Feature**: FEAT-203
**Status**: merged (target: next release after dev integration)
**Affects**: anyone installing or vendoring AI-Parrot who uses HTTP handlers,
BotManager, MCP/A2A server transports, scheduler, or autonomous orchestrator.

## What changed

The server infrastructure layer moved from the `ai-parrot` core distribution
to a new sibling package `ai-parrot-server`.

**Import paths are unchanged** — code such as
`from parrot.handlers import ChatbotHandler` or
`from parrot.manager import BotManager` continues to work without modification,
but you must now install the satellite alongside `ai-parrot`.

The move uses **PEP 420 implicit namespace packages**: the satellite ships
no `__init__.py` at the namespace levels, so Python merges both distributions'
directories automatically.

## What moved to ai-parrot-server

| Module | Contents | Task |
|---|---|---|
| `parrot.handlers` | ~59 aiohttp HTTP handler classes (ChatbotHandler, BotHandler, ChatHandler, etc.) + all subdirectories (agents/, crew/, database/, jobs/, models/, scraping/, stores/) | TASK-1371 |
| `parrot.manager` | BotManager (2116 lines), EphemeralRegistry, EphemeralAgentStatus | TASK-1372 |
| `parrot.services` | AgentService, AgentServiceClient, delivery, heartbeat, redis_listener, task_queue, worker_pool, WhatsApp bridge, O365 remote auth, identity mapping, vault token sync | TASK-1373 |
| `parrot.scheduler` | AgentSchedulerManager, ScheduleType, `@schedule`, `@schedule_daily_report`, `@schedule_weekly_report`, models, functions | TASK-1374 |
| `parrot.autonomous` | AutonomousOrchestrator, redis_jobs, webhooks, scheduler, admin, CLI, EVB, deploy/, transport/ | TASK-1375 |
| `parrot.mcp` (server files) | MCPServer, MCPToolAdapter, MCPServerConfig, AuthMethod, transports (stdio, http, sse, unix, websocket, quic, gRPC), CLI, wrapper, chrome, resources | TASK-1369 |
| `parrot.mcp` (consolidated) | ParrotMCPServer (from services/mcp/server.py), SimpleMCPServer (from services/mcp/simple.py) | TASK-1369 |
| `parrot.mcp.oauth_server` | APIKeyStore, ExternalOAuthValidator, OAuthClient, ClientRegistry, OAuthAuthorizationServer, OAuthRoutesMixin | TASK-1368 |
| `parrot.a2a` (server files) | A2AServer, A2AEnabledMixin, A2ASecurityMiddleware, JWTAuthenticator, MTLSAuthenticator, SecureA2AClient | TASK-1370 |

## What stayed in ai-parrot (core)

- `parrot.bots` — all bot/agent implementations (AbstractBot, Chatbot, Agent)
- `parrot.clients` — all LLM provider clients (AbstractClient, OpenAI, Anthropic, etc.)
- `parrot.tools` — all tool definitions and toolkits
- `parrot.loaders` — document loaders for RAG
- `parrot.memory` — conversation memory (Redis-backed)
- `parrot.registry` — AgentRegistry
- `parrot.mcp.client` — MCPClient, MCPEnabledMixin (consumer side)
- `parrot.mcp.oauth` — TokenStore, InMemoryTokenStore, RedisTokenStore, VaultTokenStore, OAuthManager, NetSuiteM2MAuth (consumer side)
- `parrot.mcp.integration` — MCPClient, MCPEnabledMixin, factory functions
- `parrot.mcp.context` — MCPSessionManager, ReadonlyContext
- `parrot.mcp.registry` — MCPServerRegistry
- `parrot.a2a.client` — A2AClient, A2AClientMixin
- `parrot.a2a.models` — AgentCard, Task, Message, etc.
- `parrot.a2a.mesh` — A2AMeshDiscovery
- `parrot.a2a.router` — A2AProxyRouter
- `parrot.a2a.orchestrator` — A2AOrchestrator
- `parrot.security` — prompt injection, query validator, + vault_utils (newly relocated here)
- `parrot.conf` — configuration
- `parrot.core` — core abstractions

## Install command mapping

| Before | After |
|---|---|
| `pip install ai-parrot` | `pip install ai-parrot` (core only, NO handlers/manager/scheduler/etc.) |
| `pip install ai-parrot[scheduler]` | `pip install ai-parrot-server[scheduler]` |
| `pip install ai-parrot[all]` | `pip install ai-parrot[all]` (unchanged — meta-extra now includes `ai-parrot-server[all]`) |
| n/a | `pip install ai-parrot[server]` (new convenience alias for `ai-parrot-server[all]`) |
| n/a | `pip install ai-parrot-server` (all server infrastructure) |
| n/a | `pip install ai-parrot-server[scheduler]` (+ APScheduler) |
| n/a | `pip install ai-parrot-server[mcp]` (+ QUIC/gRPC MCP transports) |
| n/a | `pip install ai-parrot-server[a2a]` (+ A2A server with JWT) |
| n/a | `pip install ai-parrot-server[autonomous]` (+ aiofiles for file transport) |
| n/a | `pip install ai-parrot-server[all]` (all server extras) |

## Code changes required

**None.** All existing import paths continue to work:

```python
# These continue to work unchanged:
from parrot.handlers import ChatbotHandler
from parrot.manager import BotManager
from parrot.services import AgentService
from parrot.scheduler import AgentSchedulerManager, schedule, ScheduleType
from parrot.autonomous.orchestrator import AutonomousOrchestrator
from parrot.mcp.server import MCPServer
from parrot.mcp.config import MCPServerConfig, AuthMethod
from parrot.a2a import A2AServer, A2AEnabledMixin
from parrot.a2a.security import A2ASecurityMiddleware
```

The host `parrot.*` `__init__.py` files use `pkgutil.extend_path` for namespace
merging and lazy `__getattr__` patterns so these imports resolve from the satellite
when installed.

## Backward compatibility

### Import redirects provided

These redirect stubs remain in `ai-parrot` (core) to preserve backward compatibility:

| Old import path | Redirects to |
|---|---|
| `from parrot.handlers.vault_utils import ...` | `from parrot.security.vault_utils import ...` |
| `from parrot.handlers.credentials_utils import ...` | `from parrot.security.credentials_utils import ...` |

### Missing-satellite error messages

If `ai-parrot-server` is NOT installed and code tries to access server classes
via the host stubs, a helpful `ImportError` is raised:

```python
>>> from parrot.manager import BotManager
ImportError: 'BotManager' requires the ai-parrot-server package.
Install it with: pip install ai-parrot-server
```

## Security module — vault_utils relocation

`vault_utils.py` and `credentials_utils.py` were moved from `parrot/handlers/`
to `parrot/security/` (TASK-1366). Both paths continue to work:

```python
# New canonical path (preferred):
from parrot.security.vault_utils import store_vault_credential, retrieve_vault_credential
from parrot.security.credentials_utils import encrypt_credential, decrypt_credential

# Legacy path (still works via redirect stub):
from parrot.handlers.vault_utils import store_vault_credential
from parrot.handlers.credentials_utils import encrypt_credential
```

## MCP consolidation

`parrot/services/mcp/` was eliminated. Both server implementations are now in
`parrot/mcp/` in the satellite (TASK-1369):

| Old import | New import |
|---|---|
| `from parrot.services.mcp.server import ParrotMCPServer` | `from parrot.mcp.parrot_server import ParrotMCPServer` |
| `from parrot.services.mcp.simple import SimpleMCPServer` | `from parrot.mcp.simple_server import SimpleMCPServer` |

## Server-only bots

These bots import scheduler decorators and **require `ai-parrot-server`**:

- `github_reviewer.py` — imports `@schedule_daily_report` / `@schedule_weekly_report`
- `jira_specialist.py` — imports scheduler decorators

Without `ai-parrot-server[scheduler]` installed, these bots will fail at import
with an informative `ImportError`.

**Fix**: `pip install ai-parrot-server[scheduler]` or remove the scheduler decorator usage.

## parrot-fs CLI entry point

The `parrot-fs` command-line tool (autonomous filesystem transport) moved to
the satellite's `[project.scripts]`:

```bash
# Before: installed with ai-parrot
# After: install ai-parrot-server to get parrot-fs
pip install ai-parrot-server

# Then use as before:
parrot-fs --help
```

## uv workspace

If you use the uv workspace (`packages/` directory), the new package is
automatically discovered:

```bash
uv sync --all-packages   # installs both ai-parrot and ai-parrot-server in editable mode
```

## FAQ

### Q: I only use the agent/tool/client abstractions — do I need ai-parrot-server?

No. `pip install ai-parrot` gives you the full framework for building agents,
tools, and LLM clients without any server infrastructure.

### Q: My `app.py` imports `BotManager` — do I need to change anything?

No code changes required. But you must install `ai-parrot-server`:

```bash
pip install ai-parrot-server
```

`from parrot.manager import BotManager` will then resolve from the satellite
via PEP 420 namespace merging.

### Q: What happens if I have `pip install ai-parrot[all]`?

Nothing changes — the `all` meta-extra now includes `ai-parrot-server[all]`,
so you automatically get all server infrastructure.

### Q: I was using `pip install ai-parrot[scheduler]` — what's the equivalent?

```bash
pip install ai-parrot-server[scheduler]
# or
pip install ai-parrot[server]  # installs all server extras
```

### Q: Can I verify the PEP 420 namespace merging is working?

```python
import parrot.handlers.bots as m
print(m.__file__)  # should contain "ai-parrot-server"
```

## Known Issues / Potential Breaking Changes

### `TaskStatus` name collision

`parrot.services` and `parrot.a2a` both define a `TaskStatus` enum. They are
**different types** and are not interchangeable. If you import both in the
same module you must use explicit aliases to avoid shadowing:

```python
from parrot.services import TaskStatus as ServiceTaskStatus
from parrot.a2a import TaskStatus as A2ATaskStatus
```

`ServiceTaskStatus` represents an internal scheduler/worker job state, while
`A2ATaskStatus` is defined by the A2A protocol for remote task lifecycle
tracking.

---

### Q: Why is there a parrot.mcp.oauth_server alongside parrot.mcp.oauth?

`parrot.mcp.oauth` (in core) contains the consumer-side token management:
`TokenStore`, `OAuthManager`, `NetSuiteM2MAuth`, etc.

`parrot.mcp.oauth_server` (in satellite) contains the server-side OAuth
implementation: `APIKeyStore`, `OAuthAuthorizationServer`, `OAuthRoutesMixin`, etc.

This split keeps the consumer/server boundary clean while preserving all
import paths.
