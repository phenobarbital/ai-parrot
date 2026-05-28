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
        "ai-parrot[agents,images,llms,integrations,db,bigquery,pdf,ocr,audio,finance,flowtask,reddit,mcp,charts,docling,visualizations]",
        "ai-parrot-embeddings[all]",
        "ai-parrot-integrations[all]",
        "ai-parrot-server[all]",
    ]
    ```
  - Audit and remove server-only dependencies from core `[project.dependencies]`
    that are only used by moved modules (candidates: `aiohttp-cors`, `aioquic`,
    `pylsqpack` — verify each has no remaining core consumers).
- **Depends on**: Modules 5-11 (all moves complete).

### Module 13: Tests

- **Path**: `packages/ai-parrot-server/tests/`
  - `test_wheel_layout.py` — PEP 420 compliance
  - `test_namespace_imports.py` — cross-distribution import verification
- **Responsibility**:
  - **Wheel-content test**: Assert zero `__init__.py` at namespace levels:
    `parrot/__init__.py`, `parrot/mcp/__init__.py`, `parrot/a2a/__init__.py`,
    `parrot/handlers/__init__.py`, `parrot/manager/__init__.py`,
    `parrot/services/__init__.py`, `parrot/scheduler/__init__.py`,
    `parrot/autonomous/__init__.py`.
  - **Namespace-import test**: Verify cross-distribution imports:
    - `from parrot.handlers import ChatbotHandler`
    - `from parrot.manager import BotManager`
    - `from parrot.a2a import A2AServer`
    - `from parrot.mcp.server import MCPServer`
    - `from parrot.services import AgentService`
    - `from parrot.scheduler import AgentSchedulerManager`
    Each assert resolves from satellite (`"ai-parrot-server" in mod.__file__`).
  - **Lazy-load test**: Verify host `__getattr__` resolves satellite classes.
  - **Missing-satellite test**: With satellite not installed, verify host
    `__getattr__` raises `ImportError` with helpful message.
- **Depends on**: Modules 5-11 (all moves complete).

### Module 14: Migration guide

- **Path**: `docs/migration/feat-203-ai-parrot-server.md`
- **Responsibility**: Document:
  - What moved, what stayed.
  - Install surface changes.
  - Backward-compatible import redirects.
  - Server-only bots (`github_reviewer`, `jira_specialist`).
  - `parrot-fs` entry point now in `ai-parrot-server`.
  - `vault_utils` relocation to `parrot/security/`.
- **Depends on**: Modules 5-11.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_wheel_no_init_files` | Module 13 | Satellite wheel contains zero `__init__.py` at 8 namespace levels |
| `test_namespace_imports_handlers` | Module 13 | `from parrot.handlers import ChatbotHandler` resolves from satellite |
| `test_namespace_imports_manager` | Module 13 | `from parrot.manager import BotManager` resolves from satellite |
| `test_namespace_imports_a2a_server` | Module 13 | `from parrot.a2a import A2AServer` resolves from satellite |
| `test_namespace_imports_mcp_server` | Module 13 | `from parrot.mcp.server import MCPServer` resolves from satellite |
| `test_namespace_imports_services` | Module 13 | `from parrot.services import AgentService` resolves from satellite |
| `test_namespace_imports_scheduler` | Module 13 | `from parrot.scheduler import AgentSchedulerManager` resolves |
| `test_lazy_getattr_a2a` | Module 13 | `parrot.a2a.__getattr__("A2AServer")` works |
| `test_lazy_getattr_mcp` | Module 13 | `parrot.mcp.__getattr__("MCPServerConfig")` works |
| `test_missing_satellite_error` | Module 13 | Without satellite, accessing server classes raises helpful ImportError |
| `test_vault_utils_redirect` | Module 2 | `from parrot.handlers.vault_utils import store_vault_credential` still works |
| `test_vault_utils_new_location` | Module 2 | `from parrot.security.vault_utils import store_vault_credential` works |
| `test_core_consumer_imports_unchanged` | Module 3 | All core MCP/A2A consumer imports unchanged |

### Integration Tests

| Test | Description |
|---|---|
| `test_app_startup` | `app.py` can import BotManager and start (with satellite installed) |
| `test_uv_sync` | `uv sync --all-packages` succeeds with both packages |
| `test_meta_extra_all` | `pip install ai-parrot[all]` pulls satellite |

### Test Data / Fixtures

```python
@pytest.fixture
def satellite_wheel(tmp_path):
    """Build satellite wheel for content inspection."""
    import subprocess
    subprocess.run(["uv", "build", "--wheel"], cwd="packages/ai-parrot-server")
    return next(tmp_path.glob("*.whl"))
```

---

## 5. Acceptance Criteria

- [ ] `pip install ai-parrot` (without server) installs cleanly; importing
      `parrot.bots`, `parrot.tools`, `parrot.clients`, `parrot.mcp.client`
      works; importing `parrot.handlers` or `parrot.manager` raises helpful
      ImportError
- [ ] `pip install ai-parrot-server` installs cleanly; all existing
      `from parrot.handlers import X`, `from parrot.manager import BotManager`
      imports work unchanged
- [ ] `pip install ai-parrot[all]` yields same functional stack as before
- [ ] `pip install ai-parrot[server]` is equivalent to `pip install ai-parrot-server[all]`
- [ ] Satellite wheel contains zero `__init__.py` at namespace levels
      (verified by `test_wheel_layout.py`)
- [ ] All namespace-import tests pass
- [ ] `app.py` and `appauto.py` start successfully with satellite installed
- [ ] `parrot-fs` CLI works from satellite's console_scripts
- [ ] `from parrot.security.vault_utils import store_vault_credential` works
- [ ] Backward-compat redirects work: `from parrot.handlers.vault_utils import ...`
- [ ] `uv sync --all-packages` succeeds in the workspace
- [ ] No circular import regressions
- [ ] Migration guide exists at `docs/migration/feat-203-ai-parrot-server.md`

---

## 6. Codebase Contract

### Verified Imports

```python
# Host parrot/__init__.py — extend_path (line 12)
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

# Host parrot/mcp/__init__.py — current imports (NO extend_path yet)
from .integration import MCPEnabledMixin, MCPServerConfig, MCPClient  # line 3-10
from .config import AuthMethod  # line 12
from .oauth import APIKeyStore, ExternalOAuthValidator, ...  # lines 13-23
from .client import AuthScheme, AuthCredential  # line 24
from .context import ReadonlyContext, MCPSessionManager, ...  # lines 25-30
from .registry import MCPServerRegistry, ...  # lines 31-38

# Host parrot/a2a/__init__.py — current imports (NO extend_path yet)
from .server import A2AServer, A2AEnabledMixin  # line 117-118
from .client import A2AClient, ...  # lines 120-125
from .mixin import A2AClientMixin  # line 128
from .models import AgentCard, ...  # lines 130-142
from .mesh import A2AMeshDiscovery, ...  # lines 145-151
from .router import A2AProxyRouter, ...  # lines 154-161
from .orchestrator import A2AOrchestrator, ...  # lines 164-172
from .security import AuthScheme, ...  # lines 174-184

# Host parrot/handlers/__init__.py — __getattr__ (lines 5-52, NO extend_path)
# Host parrot/manager/__init__.py — from .manager import BotManager (line 1)
# Host parrot/services/__init__.py — explicit imports (lines 5-16)
# Host parrot/scheduler/__init__.py — 1740 lines, entire implementation
# Host parrot/autonomous/__init__.py — empty file

# Host parrot/security/__init__.py — existing exports (lines 4-14)
from .prompt_injection import PromptInjectionDetector, SecurityEventLogger, ThreatLevel, PromptInjectionException
from .query_validator import QueryLanguage, QueryValidator

# Cross-module imports that must keep working:
from parrot.handlers.vault_utils import store_vault_credential, retrieve_vault_credential, delete_vault_credential, load_vault_keys  # parrot/mcp/oauth.py:14, parrot/auth/oauth2_base.py:166
from parrot.handlers.credentials_utils import encrypt_credential, decrypt_credential  # parrot/handlers/vault_utils.py:5
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/mcp/oauth.py
class APIKeyStore:  # line 41 — MOVES to satellite
class ExternalOAuthValidator:  # line 211 — MOVES to satellite
class OAuthClient:  # line 329 — MOVES to satellite
class ClientRegistry:  # line 339 — MOVES to satellite
class OAuthAuthorizationServer:  # line 374 — MOVES to satellite
class TokenStore:  # line 566 — STAYS in core (abstract)
class InMemoryTokenStore(TokenStore):  # line 572 — STAYS
class RedisTokenStore(TokenStore):  # line 586 — STAYS
class VaultTokenStore(TokenStore):  # line 607 — STAYS
class NetSuiteM2MAuth:  # line 712 — STAYS
class OAuthManager:  # line 819 — STAYS
class OAuthRoutesMixin:  # line 1003 — MOVES to satellite

# packages/ai-parrot/src/parrot/mcp/integration.py
class MCPToolProxy(AbstractTool):  # line 45 — STAYS
class MCPClient:  # line 310 — STAYS
class MCPEnabledMixin:  # line 1264 — STAYS
class MCPValidationError(Exception):  # line 1735 — STAYS
async def validate_mcp_http(): ...  # line 1743 — STAYS

# packages/ai-parrot/src/parrot/mcp/config.py
class AuthMethod(Enum):  # line 6 — MOVES to satellite
@dataclass class MCPServerConfig:  # line 16 — MOVES to satellite

# packages/ai-parrot/src/parrot/a2a/server.py
class A2AServer:  # MOVES to satellite
class A2AEnabledMixin:  # MOVES to satellite

# packages/ai-parrot/src/parrot/a2a/security.py (1984 lines)
class A2ASecurityMiddleware:  # MOVES to satellite
class JWTAuthenticator:  # MOVES to satellite
class MTLSAuthenticator:  # MOVES to satellite
class SecureA2AClient:  # MOVES to satellite

# packages/ai-parrot/src/parrot/manager/manager.py
class BotManager:  # line 90 — MOVES to satellite

# packages/ai-parrot/src/parrot/handlers/vault_utils.py (175 lines)
def load_vault_keys(): ...  # line 44 — RELOCATES to parrot/security/
async def store_vault_credential(): ...  # line 69
async def retrieve_vault_credential(): ...  # line 116
async def delete_vault_credential(): ...  # line 149
def oauth2_vault_name(): ...  # line 168

# packages/ai-parrot/src/parrot/handlers/credentials_utils.py (81 lines)
def encrypt_credential(): ...  # line 19 — RELOCATES to parrot/security/
def decrypt_credential(): ...  # line 52

# packages/ai-parrot/src/parrot/services/mcp/server.py
class ParrotMCPServer:  # line 25 — MOVES to satellite as parrot.mcp.parrot_server

# packages/ai-parrot/src/parrot/services/mcp/simple.py
class SimpleMCPServer:  # line 53 — MOVES to satellite as parrot.mcp.simple_server
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Satellite `mcp/oauth_server.py` | Core `mcp/oauth.py` TokenStore | cross-distribution import | `parrot/mcp/oauth.py:566` |
| Satellite `a2a/server.py` | Core `bots/abstract.py` AbstractBot | TYPE_CHECKING import | `parrot/a2a/server.py` |
| Satellite `manager/manager.py` | Satellite `handlers/*` | direct import (both in satellite) | `parrot/manager/manager.py:27-81` |
| Host `mcp/__init__.py` | Satellite `mcp/config.py` MCPServerConfig | lazy `__getattr__` | to be created |
| Host `a2a/__init__.py` | Satellite `a2a/server.py` A2AServer | lazy `__getattr__` | to be created |
| `app.py` (repo root) | Satellite `manager/manager.py` BotManager | namespace merging | `app.py:10` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.server`~~ — there is no top-level `parrot.server` module; the
  package is `ai-parrot-server` but contributes to `parrot.*` namespaces.
- ~~`parrot.mcp.__init__.py` extend_path~~ — does NOT exist yet; must be added.
- ~~`parrot.a2a.__init__.py` extend_path~~ — does NOT exist yet.
- ~~`parrot.handlers.__init__.py` extend_path~~ — does NOT exist yet.
- ~~`parrot.manager.BotManager.register_routes()`~~ — route registration is in
  `BotManager.setup(app)` method, not a separate method.
- ~~`parrot.services.mcp.__init__.py`~~ — this subdirectory has an `__init__.py`
  but it will be removed after consolidation into `parrot.mcp/` in satellite.
- ~~`parrot.scheduler.AgentSchedulerManager`~~ — the class is defined INSIDE
  `scheduler/__init__.py` (line 284), not in a separate `manager.py`. The
  extraction creates `manager.py` in the satellite.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **FEAT-201 PEP 420 pattern**: No `__init__.py` in satellite namespace dirs.
  Host `__init__.py` uses `extend_path(__path__, __name__)`.
  `pyproject.toml` with `namespaces = true`. See
  `packages/ai-parrot-embeddings/` for verified reference.
- **Lazy `__getattr__` in host `__init__.py`**: For backward-compatible
  imports of server classes. Pattern from `parrot/rerankers/__init__.py`:
  ```python
  def __getattr__(name: str):
      if name == "LocalCrossEncoderReranker":
          from parrot.rerankers.local import LocalCrossEncoderReranker
          return LocalCrossEncoderReranker
      raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
  ```
- **Wheel-content test**: Enforce PEP 420 compliance. Pattern from
  `packages/ai-parrot-embeddings/tests/test_wheel_layout.py`.
- **Import redirect for backward compat**:
  ```python
  # parrot/handlers/vault_utils.py (host stub)
  from parrot.security.vault_utils import *  # noqa: F401,F403
  from parrot.security.vault_utils import (
      load_vault_keys, store_vault_credential,
      retrieve_vault_credential, delete_vault_credential,
      oauth2_vault_name,
  )
  ```

### Known Risks / Gotchas

- **MCP consolidation**: Merging `parrot/services/mcp/` into `parrot/mcp/`
  requires reconciling two server implementations (ParrotMCPServer vs
  MCPServer). They serve different use cases: ParrotMCPServer is aiohttp-
  lifecycle-integrated; MCPServer is standalone. Both move but remain
  separate files (`parrot_server.py`, `simple_server.py`).
- **Scheduler `__init__.py` is 1740 lines**: The entire
  `AgentSchedulerManager` + decorators live in `__init__.py`. Must be
  carefully refactored into `manager.py` in the satellite, then the host
  `__init__.py` becomes a slim stub.
- **Server-only bots**: `github_reviewer.py:51` and `jira_specialist.py:51`
  import `@schedule_daily_report`/`@schedule_weekly_report`. These bots
  will `ImportError` without `ai-parrot-server`. Document in migration guide.
- **Navigator-auth is in core deps**: Navigator is deeply integrated (66 files,
  178 imports). It stays in core `[project.dependencies]`. The satellite
  inherits it via `dependencies = ["ai-parrot"]`.
- **Circular imports within satellite**: BotManager imports handlers which
  may import BotManager (via TYPE_CHECKING). Since all move to the same
  satellite, the topology is preserved. No new circularity.

### External Dependencies

| Package | Version | Where | Notes |
|---|---|---|---|
| `apscheduler` | `==3.11.2` | satellite `[scheduler]` extra | Currently in host `[scheduler]` extra |
| `aioquic` | `==1.3.0` | satellite `[mcp]` extra or core dep | QUIC transport; check if core still needs it |
| `pylsqpack` | `==0.3.23` | satellite `[mcp]` extra or core dep | QUIC dependency |
| `click` | `>=8.1.7` | stays in core | Used by CLI (core) and MCP CLI (satellite) |
| `aiohttp-cors` | `>=0.8.1` | stays in core | Used by scheduler handlers AND other core components |
| `navigator-auth` | `>0.20.9` | stays in core | Deeply integrated across 66 files |
| `aiohttp-swagger3` | `==0.10.0` | stays in core | Used by core HTTP infrastructure |
| `aiofiles` | `>=23.0` | satellite `[autonomous]` extra | Currently in host `[filesystem-transport]` extra |

---

## 8. Open Questions

### Resolved (from proposal phase)

- [x] **Should BotManager stay in core or move to satellite?** — *Resolved in proposal*: Move to satellite. All consumers are co-moving or TYPE_CHECKING.
- [x] **Should app.py/appauto.py move to satellite?** — *Resolved in proposal*: Stay in repo root as standalone scripts.
- [x] **How to handle scheduler decorators in core bots?** — *Resolved in proposal*: Move entire scheduler to satellite. github_reviewer and jira_specialist become server-only bots.
- [x] **Should services/mcp/ be consolidated with mcp/ in satellite?** — *Resolved in proposal*: Yes, consolidated as parrot_server.py and simple_server.py.
- [x] **Should the parrot CLI move to satellite?** — *Resolved in spec research*: No. CLI is general-purpose (setup, conf, install, agent REPL). The `mcp` and `autonomous` subcommands lazy-import and fail gracefully if satellite not installed. Only `parrot-fs` moves.
- [x] **Does integration.py need splitting?** — *Resolved in spec research*: No. Factory functions create connection configs (consumer-side), not server infrastructure. It stays in core entirely.
- [x] **Where to put vault_utils?** — *Resolved in spec research*: `parrot/security/` already exists with prompt_injection and query_validator. Add vault_utils and credentials_utils there.

### Unresolved (defer to implementation)

- [x] **Which core deps can be removed after extraction?** — *Owner*: Module 12 implementer. Candidates: `aioquic`, `pylsqpack`. Must verify no remaining core consumer exists before removing.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (single worktree, sequential tasks).
- **Rationale**: The modules have cross-dependencies (e.g., Module 7 depends on
  Module 2; Module 8 depends on Module 7). Running in sequence avoids
  merge conflicts in shared files like `__init__.py` files.
- **Cross-feature dependencies**: None — FEAT-203 is self-contained.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-29 | Jesus Lara / Claude | Initial draft from FEAT-203 proposal |
