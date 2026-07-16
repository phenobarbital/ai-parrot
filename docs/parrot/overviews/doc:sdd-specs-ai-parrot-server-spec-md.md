---
type: Wiki Overview
title: 'Feature Specification: ai-parrot-server — extract server infrastructure into
  a PEP 420 satellite package'
id: doc:sdd-specs-ai-parrot-server-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: ai-parrot currently bundles all server infrastructure — HTTP handlers, MCP/A2A
relates_to:
- concept: mod:parrot.a2a
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.cli
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.handlers.credentials_utils
  rel: mentions
- concept: mod:parrot.handlers.vault_utils
  rel: mentions
- concept: mod:parrot.manager
  rel: mentions
- concept: mod:parrot.mcp
  rel: mentions
- concept: mod:parrot.mcp.client
  rel: mentions
- concept: mod:parrot.mcp.oauth
  rel: mentions
- concept: mod:parrot.mcp.parrot_server
  rel: mentions
- concept: mod:parrot.mcp.server
  rel: mentions
- concept: mod:parrot.mcp.simple_server
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.rerankers.local
  rel: mentions
- concept: mod:parrot.scheduler
  rel: mentions
- concept: mod:parrot.security.vault_utils
  rel: mentions
- concept: mod:parrot.server
  rel: mentions
- concept: mod:parrot.services
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: ai-parrot-server — extract server infrastructure into a PEP 420 satellite package

**Feature ID**: FEAT-203
**Date**: 2026-05-29
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.0
**Proposal**: `sdd/proposals/ai-parrot-server.proposal.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

ai-parrot currently bundles all server infrastructure — HTTP handlers, MCP/A2A
server transports, APScheduler runtime, autonomous orchestration, BotManager,
and associated services — inside the core distribution. This forces every
consumer that only needs the agent/tool/client abstractions to install heavy
server dependencies (aiohttp views, APScheduler, navigator-auth view classes,
QUIC/gRPC transports, etc.).

The FEAT-201 extraction of `ai-parrot-embeddings` proved that PEP 420 implicit
namespace packages can cleanly split backend implementations from core
abstractions with zero import-path changes. FEAT-203 applies the same pattern
to the server layer.

### Goals

1. **One new distributable package**: `ai-parrot-server` under
   `packages/ai-parrot-server/`, with optional extras per server subsystem.
2. **PEP 420 namespace contribution**: the satellite ships **no `__init__.py`**
   at namespace levels — Python merges its directory contents into the host's
   regular `parrot.*` packages at import time.
3. **Byte-identical import surface**: every existing
   `from parrot.handlers import X`, `from parrot.manager import BotManager`,
   etc. continues to work unchanged after the split.
4. **Server isolation**: `pip install ai-parrot` (core only) installs the
   framework without any server infrastructure; users opt in via
   `pip install ai-parrot-server` or `pip install ai-parrot[server]`.
5. **No host-pyproject regression**: meta-extra `all` must continue to yield
   the same functional stack as today.
6. **Clean MCP/A2A separation**: MCP and A2A consumer code (clients, mixins,
   discovery) stays in core; server code (transports, adapters, HTTP
   endpoints) moves to satellite.

### Non-Goals (explicitly out of scope)

- **Retrofitting** `ai-parrot-tools`, `-loaders`, `-pipelines`, or
  `parrot-formdesigner` to the PEP 420 convention.
- **Modifying AgentRegistry** (`parrot/registry/`) — stays in core unchanged.
- **Moving bot/agent abstractions** (`parrot/bots/`) — stays in core.
- **Moving LLM clients** (`parrot/clients/`) — stays in core.
- **Moving the tool framework** (`parrot/tools/`) — stays in core.
- **Moving memory** (`parrot/memory/`) — stays in core.
- **Moving core config** (`parrot/conf.py`, `parrot/core/`) — stays in core.
- **Moving the CLI framework** (`parrot/cli/`) — stays in core; CLI is
  general-purpose (setup, conf, install, agent REPL). The `mcp` and
  `autonomous` subcommands lazy-import from satellite and fail gracefully
  if not installed.
- **Splitting `parrot/mcp/integration.py`** — research confirmed it is
  entirely consumer-side (factory functions create connection configs, not
  server infrastructure). It stays in core unchanged.
- **Changing any runtime API** — signatures, return types, async semantics
  all preserved.

---

## 2. Architectural Design

### Overview

Create a new uv-workspace member `ai-parrot-server` under
`packages/ai-parrot-server/`. Its `src/` tree contains the server-side
modules at the same dotted-path locations they occupy today in the host —
but **no `__init__.py` files** at the namespace levels. Python's PEP 420
implicit-namespace-package mechanism merges the satellite's directory entries
with the host's regular packages at import time.

The host's `__init__.py` files at affected levels are updated to add
`extend_path(__path__, __name__)` calls (currently only `parrot/__init__.py`
has one). This enables the satellite's modules to be discovered via namespace
merging.

For modules where the host `__init__.py` currently eagerly imports server
classes (e.g., `parrot/a2a/__init__.py` imports `A2AServer`), the imports
are converted to lazy `__getattr__` patterns that resolve from the satellite
when accessed — providing a helpful error message if `ai-parrot-server` is
not installed.

### Component Diagram

```
                                        ┌─ pip install ai-parrot
                                        │     core framework: agents, tools, clients, MCP/A2A consumers
                                        │     NO handlers, NO server transports, NO scheduler
                                        │
                                        └─ pip install ai-parrot-server
                                              server layer on top via PEP 420
                                              imports unchanged: from parrot.handlers import ChatbotHandler

┌────────────────── ai-parrot (host) ──────────────────┐  ┌───────────── ai-parrot-server (satellite) ──────────┐
│ src/parrot/                                           │  │ src/parrot/                                         │
│   __init__.py   (extend_path; STAYS)                  │  │   ── NO __init__.py ──                              │
│                                                       │  │                                                     │
│   mcp/                                                │  │   mcp/                                              │
│     __init__.py (extend_path + lazy server exports)   │  │     ── NO __init__.py ──                            │
│     client.py       (MCPClientConfig; STAYS)          │  │     server.py         (MCPServer factory)           │
│     context.py      (MCPSessionManager; STAYS)        │  │     adapter.py        (MCPToolAdapter)              │
│     filtering.py    (Tool predicates; STAYS)          │  │     config.py         (MCPServerConfig, AuthMethod) │
│     integration.py  (MCPClient, MCPEnabledMixin; STAYS│  │     cli.py            (Click CLI)                   │
│     oauth.py        (OAuthManager, TokenStores; STAYS)│  │     wrapper.py        (Config loading)              │
│     registry.py     (MCPServerRegistry; STAYS)        │  │     chrome.py         (Chrome management)           │
│                                                       │  │     resources.py      (MCPResource)                 │
│   a2a/                                                │  │     oauth_server.py   (OAuthAuthorizationServer)    │
│     __init__.py (extend_path + lazy server exports)   │  │     parrot_server.py  (from services/mcp/)         │
│     client.py       (A2AClient; STAYS)                │  │     simple_server.py  (from services/mcp/)         │
│     mixin.py        (A2AClientMixin; STAYS)           │  │     transports/                                    │
│     mesh.py         (A2AMeshDiscovery; STAYS)         │  │       base.py, stdio.py, http.py, sse.py           │
│     router.py       (A2AProxyRouter; STAYS)           │  │       unix.py, websocket.py, quic.py, grpc.py     │
│     orchestrator.py (A2AOrchestrator; STAYS)          │  │                                                     │
│     models.py       (AgentCard, Task, ...; STAYS)     │  │   a2a/                                              │
│                                                       │  │     ── NO __init__.py ──                            │
│   handlers/                                           │  │     server.py         (A2AServer, A2AEnabledMixin)  │
│     __init__.py (extend_path + lazy exports)          │  │     security.py       (A2ASecurityMiddleware)       │
│                                                       │  │                                                     │
│   manager/                                            │  │   handlers/           ── NO __init__.py ──          │
│     __init__.py (extend_path + lazy export)           │  │     agent.py, bots.py, chat.py, ...  (~59 files)   │
│                                                       │  │     agents/, crew/, database/, jobs/, models/       │
│   services/                                           │  │     scraping/, stores/                              │
│     __init__.py (extend_path + lazy exports)          │  │                                                     │
│                                                       │  │   manager/            ── NO __init__.py ──          │
│   scheduler/                                          │  │     manager.py        (BotManager)                  │
│     __init__.py (extend_path + lazy exports)          │  │     ephemeral.py      (EphemeralRegistry)           │
│                                                       │  │                                                     │
│   autonomous/                                         │  │   services/           ── NO __init__.py ──          │
│     __init__.py (extend_path)                         │  │     agent_service.py, client.py, delivery.py, ...   │
│                                                       │  │     models.py, whatsapp.py, ...                     │
│   security/                                           │  │                                                     │
│     __init__.py (STAYS — prompt injection + vault)    │  │   scheduler/          ── NO __init__.py ──          │
│     prompt_injection.py (STAYS)                       │  │     manager.py        (AgentSchedulerManager)       │
│     query_validator.py  (STAYS)                       │  │     models.py         (AgentSchedule ORM)           │
│     vault_utils.py      (NEW — relocated)             │  │     functions/        (Callback registry)           │
│     credentials_utils.py (NEW — relocated)            │  │                                                     │
│                                                       │  │   autonomous/         ── NO __init__.py ──          │
│   registry/   (STAYS entirely)                        │  │     orchestrator.py, redis_jobs.py, webhooks.py     │
│   bots/       (STAYS entirely)                        │  │     admin.py, cli.py, evb.py, scheduler.py          │
│   clients/    (STAYS entirely)                        │  │     deploy/, transport/                              │
│   tools/      (STAYS entirely)                        │  │                                                     │
│   memory/     (STAYS entirely)                        │  │ pyproject.toml                                      │
│   conf.py     (STAYS)                                 │  │   name = "ai-parrot-server"                         │
│   core/       (STAYS entirely)                        │  │   dependencies = ["ai-parrot"]                      │
└───────────────────────────────────────────────────────┘  └─────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/__init__.py` `extend_path` (line 12) | unchanged | Already enables namespace merging |
| `parrot/mcp/__init__.py` | modified | Add `extend_path`; convert server imports to lazy `__getattr__` |
| `parrot/a2a/__init__.py` | modified | Add `extend_path`; convert server imports to lazy `__getattr__` |
| `parrot/handlers/__init__.py` | modified | Add `extend_path`; existing `__getattr__` continues to work via namespace merging |
| `parrot/manager/__init__.py` | modified | Add `extend_path`; convert BotManager import to lazy `__getattr__` |
| `parrot/services/__init__.py` | modified | Add `extend_path`; convert imports to lazy `__getattr__` |
| `parrot/scheduler/__init__.py` | modified | Add `extend_path`; entire file moves but host stub remains |
| `parrot/autonomous/__init__.py` | modified | Add `extend_path`; currently empty so minimal change |
| `parrot/security/__init__.py` | modified | Add exports for vault_utils, credentials_utils |
| Root `pyproject.toml` `[tool.uv.workspace]` | none | `members = ["packages/*"]` auto-includes the new package |
| Host `pyproject.toml` extras | modified | Add `server` extra; rewrite `all` meta-extra |
| `app.py` / `appauto.py` | unchanged | `from parrot.manager import BotManager` resolves via namespace merging |

### Data Models

No new Pydantic models. The split is purely a packaging boundary; all
existing data models are preserved at their current import paths.

### New Public Interfaces

None at runtime. The only public-surface change is the **install surface**:

```bash
pip install ai-parrot                     # core, no server
pip install ai-parrot-server              # + all server infrastructure
pip install ai-parrot-server[scheduler]   # + APScheduler
pip install ai-parrot-server[mcp]         # + MCP server transports
pip install ai-parrot-server[a2a]         # + A2A server
pip install ai-parrot-server[autonomous]  # + autonomous orchestrator
pip install ai-parrot-server[all]         # everything

pip install ai-parrot[all]               # unchanged — meta-extra now reaches satellite
pip install ai-parrot[server]            # new convenience alias
```

---

## 3. Module Breakdown

### Module 1: Package scaffold

- **Path**:
  - `packages/ai-parrot-server/pyproject.toml`
  - `packages/ai-parrot-server/README.md`
  - `packages/ai-parrot-server/src/parrot/` (directory only; **no `__init__.py`**)
  - Namespace subdirectories: `mcp/`, `a2a/`, `handlers/`, `manager/`,
    `services/`, `scheduler/`, `autonomous/` (all **no `__init__.py`**,
    only `.gitkeep`)
  - `packages/ai-parrot-server/tests/`
- **Responsibility**: Scaffold the empty satellite package — pyproject with
  `name = "ai-parrot-server"`, `dependencies = ["ai-parrot"]`,
  `[tool.setuptools.packages.find]` with `where = ["src"]`,
  `include = ["parrot*"]`, `namespaces = true`,
  `[tool.uv.sources] ai-parrot = { workspace = true }`.
  Define optional extras: `scheduler` (apscheduler==3.11.2),
  `mcp` (aioquic, click, yaml), `a2a` (PyJWT optional),
  `autonomous` (aiofiles), `all` (aggregator).
  Dynamic version via `parrot.handlers.version.__version__` or similar.
  Verify `uv sync --all-packages` installs the empty package in editable
  mode without error.
- **Depends on**: none.

### Module 2: Relocate vault_utils and credentials_utils to parrot/security/

- **Path**:
  - `packages/ai-parrot/src/parrot/security/vault_utils.py` (new location)
  - `packages/ai-parrot/src/parrot/security/credentials_utils.py` (new location)
  - `packages/ai-parrot/src/parrot/security/__init__.py` (updated exports)
  - `packages/ai-parrot/src/parrot/handlers/vault_utils.py` (becomes redirect)
  - `packages/ai-parrot/src/parrot/handlers/credentials_utils.py` (becomes redirect)
- **Responsibility**: Move `vault_utils.py` (175 lines) and
  `credentials_utils.py` (81 lines) from `parrot/handlers/` to
  `parrot/security/`. Update `parrot/security/__init__.py` to export the
  new modules. Replace the original files with backward-compatible import
  redirects. Update all internal imports:
  - `parrot/mcp/oauth.py:14` → `from parrot.security.vault_utils import ...`
  - `parrot/auth/oauth2_base.py:166` → `from parrot.security.vault_utils import ...`
  - All internal handlers imports via redirect (transparent).
- **Depends on**: none (can run in parallel with Module 1).

### Module 3: Add extend_path to host __init__.py files

- **Path**: 7 host `__init__.py` files:
  - `packages/ai-parrot/src/parrot/mcp/__init__.py`
  - `packages/ai-parrot/src/parrot/a2a/__init__.py`
  - `packages/ai-parrot/src/parrot/handlers/__init__.py`
  - `packages/ai-parrot/src/parrot/manager/__init__.py`
  - `packages/ai-parrot/src/parrot/services/__init__.py`
  - `packages/ai-parrot/src/parrot/scheduler/__init__.py`
  - `packages/ai-parrot/src/parrot/autonomous/__init__.py`
- **Responsibility**: Add `from pkgutil import extend_path; __path__ = extend_path(__path__, __name__)` at the top of each file. Convert eager imports of classes that will move to satellite into lazy `__getattr__` patterns with helpful error messages when `ai-parrot-server` is not installed. Specifically:
  - **`mcp/__init__.py`**: Keep consumer exports (MCPClient, MCPEnabledMixin, etc.) as eager imports. Convert server exports (MCPServerConfig from `.config`, APIKeyStore/ExternalOAuthValidator/OAuthAuthorizationServer/OAuthRoutesMixin from `.oauth`) to lazy `__getattr__`.
  - **`a2a/__init__.py`**: Keep consumer exports (A2AClient, A2AClientMixin, mesh, router, orchestrator, models) as eager imports. Convert `A2AServer`, `A2AEnabledMixin` (from `.server`) and all security exports (from `.security`) to lazy `__getattr__`.
  - **`handlers/__init__.py`**: Add `extend_path` before existing `__getattr__`. The existing lazy load pattern continues to work via namespace merging.
  - **`manager/__init__.py`**: Convert `from .manager import BotManager` to lazy `__getattr__`.
  - **`services/__init__.py`**: Convert all imports to lazy `__getattr__`.
  - **`scheduler/__init__.py`**: Replace the entire 1740-line file with a slim stub: `extend_path` + lazy `__getattr__` that imports `ScheduleType`, `schedule`, `schedule_daily_report`, `schedule_weekly_report`, `AgentSchedulerManager` from the satellite. The original file moves entirely to satellite.
  - **`autonomous/__init__.py`**: Add `extend_path` (currently empty file).
- **Depends on**: Module 1 (satellite must exist for lazy imports to resolve during testing).

### Module 4: Split mcp/oauth.py (server parts to satellite)

- **Path**:
  - `packages/ai-parrot-server/src/parrot/mcp/oauth_server.py` (new file in satellite)
  - `packages/ai-parrot/src/parrot/mcp/oauth.py` (trimmed: consumer only)
- **Responsibility**: Extract server-side classes from `oauth.py` into
  `oauth_server.py` in the satellite:
  - **Move to satellite** (`oauth_server.py`):
    - `APIKeyRecord` (dataclass, lines 30-39)
    - `APIKeyStore` (lines 41-207)
    - `ExternalOAuthValidator` (lines 211-325)
    - `OAuthClient` + `ClientRegistry` (lines 329-372)
    - `OAuthAuthorizationServer` (lines 374-564)
    - `OAuthRoutesMixin` (lines 1003-1137)
  - **Keep in core** (`oauth.py`):
    - Helper functions `_b64url`, `_now` (lines 19-27)
    - `TokenStore` abstract + `InMemoryTokenStore` + `RedisTokenStore` + `VaultTokenStore` (lines 566-707)
    - `NetSuiteM2MAuth` (lines 712-817)
    - `OAuthManager` (lines 819-1001)
  - The satellite's `oauth_server.py` imports `TokenStore` and friends from
    `parrot.mcp.oauth` (core) — cross-distribution import via namespace merging.
- **Depends on**: Module 2 (vault_utils relocation must happen first since
  oauth.py imports from vault_utils).

### Module 5: Move MCP server files to satellite

- **Path** (satellite targets):
  - `packages/ai-parrot-server/src/parrot/mcp/server.py`
  - `packages/ai-parrot-server/src/parrot/mcp/adapter.py`
  - `packages/ai-parrot-server/src/parrot/mcp/config.py`
  - `packages/ai-parrot-server/src/parrot/mcp/cli.py`
  - `packages/ai-parrot-server/src/parrot/mcp/wrapper.py`
  - `packages/ai-parrot-server/src/parrot/mcp/chrome.py`
  - `packages/ai-parrot-server/src/parrot/mcp/resources.py`
  - `packages/ai-parrot-server/src/parrot/mcp/transports/` (entire directory)
  - `packages/ai-parrot-server/src/parrot/mcp/parrot_server.py` (from `services/mcp/server.py`)
  - `packages/ai-parrot-server/src/parrot/mcp/simple_server.py` (from `services/mcp/simple.py`)
- **Responsibility**: `git mv` the MCP server files from host to satellite.
  Consolidate `services/mcp/server.py` → `mcp/parrot_server.py` and
  `services/mcp/simple.py` → `mcp/simple_server.py`. Update internal imports
  within moved files (e.g., `parrot.services.mcp.server` → `parrot.mcp.parrot_server`).
  Verify `from parrot.mcp.server import MCPServer` resolves from satellite.
- **Depends on**: Module 3, Module 4.

### Module 6: Move A2A server files to satellite

- **Path** (satellite targets):
  - `packages/ai-parrot-server/src/parrot/a2a/server.py`
  - `packages/ai-parrot-server/src/parrot/a2a/security.py`
- **Responsibility**: `git mv` the two A2A server files. They use only
  TYPE_CHECKING imports to `..bots.abstract.AbstractBot` and
  `..tools.abstract.AbstractTool` — no runtime cross-deps to resolve.
  Verify `from parrot.a2a import A2AServer` resolves from satellite via
  the host's lazy `__getattr__`.
- **Depends on**: Module 3.

### Module 7: Move handlers/ to satellite

- **Path**: `packages/ai-parrot-server/src/parrot/handlers/` (~59 files)
- **Responsibility**: `git mv` the entire `handlers/` directory contents
  (except `__init__.py`, `vault_utils.py`, `credentials_utils.py` which
  stay as stubs in core). The satellite gets all handler files including
  subdirectories (`agents/`, `crew/`, `database/`, `jobs/`, `models/`,
  `scraping/`, `stores/`). The handler files' internal imports of each other
  remain unchanged. Their imports of core modules (`parrot.bots.abstract`,
  `parrot.tools.manager`, `parrot.registry`, etc.) resolve via namespace
  merging.
- **Depends on**: Module 2 (vault_utils must be relocated first), Module 3.

### Module 8: Move manager/ to satellite

- **Path**: `packages/ai-parrot-server/src/parrot/manager/`
  - `manager.py` (BotManager)
  - `ephemeral.py` (EphemeralRegistry)
- **Responsibility**: `git mv` manager.py and ephemeral.py to satellite.
  BotManager imports ~25 handler classes — since handlers also move to
  satellite, this coupling is internal. All external consumers of BotManager
  use TYPE_CHECKING imports, so no runtime breakage.
  Verify `from parrot.manager import BotManager` resolves via namespace merging.
- **Depends on**: Module 7 (handlers must move first since BotManager imports them).

### Module 9: Move services/ to satellite

- **Path**: `packages/ai-parrot-server/src/parrot/services/`
  - `agent_service.py`, `client.py`, `delivery.py`, `heartbeat.py`,
    `redis_listener.py`, `task_queue.py`, `worker_pool.py`, `models.py`,
    `whatsapp.py`, `o365_remote_auth.py`, `identity_mapping.py`,
    `vault_token_sync.py`
- **Responsibility**: `git mv` all service files to satellite. The
  `services/mcp/` subdirectory is NOT moved here — it was consolidated
  into `parrot/mcp/` in Module 5. Remove the empty `services/mcp/` directory
  from core.
- **Depends on**: Module 3, Module 5 (MCP consolidation).

### Module 10: Move scheduler/ to satellite

- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/`
  - `manager.py` (renamed from the original `__init__.py` content)
  - `models.py`
  - `functions/` (entire directory)
- **Responsibility**: The current `scheduler/__init__.py` is a 1740-line file
  containing the entire `AgentSchedulerManager` implementation. Move its
  content to `manager.py` in the satellite. The host's `scheduler/__init__.py`
  becomes a slim stub with `extend_path` + lazy exports.
  Move `models.py` and `functions/` as-is.
  Note: `github_reviewer.py` and `jira_specialist.py` import
  `@schedule_daily_report`/`@schedule_weekly_report` — these bots become
  server-only (require `ai-parrot-server` to be installed).
- **Depends on**: Module 3.

### Module 11: Move autonomous/ to satellite

- **Path**: `packages/ai-parrot-server/src/parrot/autonomous/`
  - `orchestrator.py`, `redis_jobs.py`, `webhooks.py`, `scheduler.py`,
    `admin.py`, `cli.py`, `evb.py`, `example.py`
  - `deploy/` (entire directory)
  - `transport/` (entire directory)
- **Responsibility**: `git mv` all autonomous files. The `parrot-fs`
  console_script (`parrot.autonomous.transport.filesystem.cli:main`) moves
  to the satellite's `[project.scripts]`. Remove it from the host's
  pyproject.toml.
- **Depends on**: Module 3.

### Module 12: Update host pyproject.toml

- **Path**: `packages/ai-parrot/pyproject.toml`
- **Responsibility**:
  - Remove the `scheduler` optional extra (line 163-165: `apscheduler==3.11.2`)
    — moves to satellite.
  - Remove the `parrot-fs` console_script entry.
  - Add new convenience extra:
    ```toml
    server = ["ai-parrot-server[all]"]
    ```
  - Rewrite `all` meta-extra to include `ai-parrot-server[all]`:
    ```toml
    all = [

…(truncated)…
