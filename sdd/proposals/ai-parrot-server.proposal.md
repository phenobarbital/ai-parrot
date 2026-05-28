---
id: FEAT-203
title: "Extract server infrastructure into ai-parrot-server PEP 420 namespace package"
slug: ai-parrot-server
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-29
  summary_oneline: "Extract server infra (handlers, MCP/A2A servers, services, scheduler, autonomous, BotManager) into ai-parrot-server"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-203/
created: 2026-05-29
updated: 2026-05-29
---

# FEAT-203 — Extract server infrastructure into ai-parrot-server

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — user-provided architecture description
> **Audit**: [`sdd/state/FEAT-203/`](../state/FEAT-203/)

---

## 0. Origin

> Using PEP 420 implicit namespace convention: convert all infrastructure for
> running ai-parrot as aiohttp services into an independent package
> `ai-parrot-server`, centralizing the following sub-packages (currently in
> ai-parrot):
> - parrot/mcp: separate consuming MCP (stays in core) from running MCP servers
> - parrot/a2a: separate consuming A2A (stays in core) from running A2A servers
> - parrot/handlers: all REST HTTP services for operating with agents
> - parrot/services: services associated with the HTTP server
> - parrot/scheduler: APScheduler server infrastructure
> - parrot/autonomous: autonomous agent service
> - parrot/manager: BotManager (server orchestrator)
>
> AgentRegistry remains in ai-parrot core.

**Initial signals**:
- Architecture: PEP 420 namespace package extraction (follows FEAT-201 precedent)
- Scope: 6 full modules + server-side splits from 2 hybrid modules (MCP, A2A)
- Pattern: satellite package `ai-parrot-server` alongside `ai-parrot-embeddings`

---

## 1. Synthesis Summary

ai-parrot currently bundles all server infrastructure (HTTP handlers, MCP/A2A
servers, scheduling, autonomous orchestration, and the BotManager that wires
them together) inside the core package. This means any consumer that only needs
the agent/tool/client abstractions must install heavy server dependencies
(aiohttp views, APScheduler, navigator-auth, etc.).

This proposal extracts all server-side infrastructure into a new
`ai-parrot-server` satellite package using PEP 420 implicit namespace packages,
following the proven FEAT-201 (ai-parrot-embeddings) pattern. The core retains
agent abstractions, tool definitions, LLM clients, MCP/A2A consumer code, and
AgentRegistry. The satellite owns everything needed to expose agents as HTTP,
MCP, A2A, WebSocket, or autonomous services.

The extraction is structurally clean: all BotManager consumers are either
co-moving to the satellite or use TYPE_CHECKING-only imports. The MCP and A2A
modules have clear server/client boundaries. The main complexity lies in two
hybrid files (`mcp/integration.py`, `mcp/oauth.py`) that need splitting, and
relocating `vault_utils` to a shared core location.

---

## 2. Codebase Findings

> All entries grounded in research findings at `sdd/state/FEAT-203/findings/`.

### 2.1 Localization

| # | Module | Files | Role | Evidence |
|---|--------|-------|------|----------|
| 1 | `parrot/handlers/` | ~59 .py | All HTTP handlers (REST, WebSocket, SSE) | F001 |
| 2 | `parrot/manager/` | 3 .py | BotManager — central server orchestrator | F005 |
| 3 | `parrot/services/` | ~15 .py | AgentService, WhatsApp bridge, O365 auth, identity mapping | F004 |
| 4 | `parrot/services/mcp/` | 2 .py | ParrotMCPServer, SimpleMCPServer (aiohttp-integrated) | F002, F004 |
| 5 | `parrot/scheduler/` | 3 .py | AgentSchedulerManager + decorators + callback registry | F004 |
| 6 | `parrot/autonomous/` | ~15 .py | AutonomousOrchestrator + transport + deploy + CLI | F004 |
| 7 | `parrot/mcp/server.py` | 1 .py | MCPServer factory (transport selection) | F002 |
| 8 | `parrot/mcp/transports/` | 8 .py | stdio, HTTP, SSE, Unix, WebSocket, QUIC, gRPC transports | F002 |
| 9 | `parrot/mcp/adapter.py` | 1 .py | Tool-to-MCP adapter | F002 |
| 10 | `parrot/mcp/config.py` | 1 .py | MCPServerConfig | F002 |
| 11 | `parrot/mcp/cli.py` | 1 .py | Click CLI for `parrot mcp serve` | F002 |
| 12 | `parrot/mcp/wrapper.py` | 1 .py | YAML/Python config loading | F002 |
| 13 | `parrot/mcp/chrome.py` | 1 .py | Chrome process management for devtools MCP | F002 |
| 14 | `parrot/mcp/resources.py` | 1 .py | MCPResource data class | F002 |
| 15 | `parrot/mcp/integration.py` | 1 .py | **Hybrid** — MCPClient (core) + factory fns (satellite) | F002 |
| 16 | `parrot/mcp/oauth.py` | 1 .py | **Hybrid** — OAuthServer (satellite) + TokenStores (core) | F002 |
| 17 | `parrot/a2a/server.py` | 1 .py | A2AServer + A2AEnabledMixin | F003 |
| 18 | `parrot/a2a/security.py` | 1 .py | A2ASecurityMiddleware + auth (1984 lines) | F003 |

**Stays in core (MCP consumer)**:
- `parrot/mcp/client.py` — MCPClientConfig, AuthCredential, AuthScheme
- `parrot/mcp/context.py` — ReadonlyContext, MCPSessionManager
- `parrot/mcp/filtering.py` — Tool predicates
- `parrot/mcp/registry.py` — MCPServerRegistry, catalog descriptors

**Stays in core (A2A consumer)**:
- `parrot/a2a/client.py` — A2AClient, A2ARemoteAgentTool, A2ARemoteSkillTool
- `parrot/a2a/mixin.py` — A2AClientMixin
- `parrot/a2a/mesh.py` — A2AMeshDiscovery
- `parrot/a2a/router.py` — A2AProxyRouter
- `parrot/a2a/orchestrator.py` — A2AOrchestrator
- `parrot/a2a/models.py` — All A2A data models (pure dataclasses)

**Stays in core (AgentRegistry)**:
- `parrot/registry/` — entire module

### 2.2 Constraints Discovered

- **BotManager imports ~25 handler classes directly** in `manager.py` (lines
  27-81) and registers 200+ routes in `setup()` (lines 1334-1585). Since
  BotManager now moves to satellite, this coupling is internal to the satellite
  and requires no refactoring. *Evidence*: F005

- **vault_utils cross-dependency.** `parrot/handlers/vault_utils.py` is
  imported by `parrot/mcp/oauth.py:14` (moving to satellite) AND
  `parrot/auth/oauth2_base.py:166` (stays in core). Must be relocated to a
  shared core location before extraction. *Evidence*: F001

- **MCP hybrid files.** `integration.py` mixes MCPClient (consumer) with
  server factory functions (`create_*_mcp_server`). `oauth.py` mixes
  OAuthAuthorizationServer (server) with OAuthManager + TokenStore impls
  (consumer). Both need splitting. *Evidence*: F002

- **Scheduler decorators used by core bots.** `@schedule_daily_report` is
  imported by `parrot/bots/github_reviewer.py:51` and
  `@schedule_weekly_report` by `parrot/bots/jira_specialist.py:51`. Since the
  entire scheduler moves to satellite, these bots become server-only bots
  (they only make sense when scheduled). *Evidence*: F004

- **PEP 420 requires NO `__init__.py`** at namespace levels in the satellite.
  Host `__init__.py` files call `extend_path(__path__, __name__)` to merge
  namespace contributions. This is already proven for `parrot/embeddings/`,
  `parrot/stores/`, `parrot/rerankers/`. Must be added for new namespaces:
  `parrot/handlers/`, `parrot/manager/`, `parrot/services/`, `parrot/scheduler/`,
  `parrot/autonomous/`. *Evidence*: F006

- **`parrot/services/mcp/` overlaps with `parrot/mcp/server.py`.** Two separate
  MCP server implementations exist: `MCPServer` (standalone, transport-selection)
  and `ParrotMCPServer`/`SimpleMCPServer` (aiohttp-integrated). These should be
  consolidated during extraction into a unified `parrot/mcp/` namespace in the
  satellite. *Evidence*: F002, F004

- **Entry points**: `app.py` and `appauto.py` stay in the repo root as standalone
  scripts that import BotManager from the satellite. The `parrot-fs` CLI entry
  point (`parrot.autonomous.transport.filesystem.cli:main`) moves to the
  satellite's console_scripts. *Evidence*: F004

- **A2A is self-contained.** No core module imports from `parrot.a2a` — only
  examples and tests. The server/client split is clean: `server.py` +
  `security.py` use only TYPE_CHECKING imports to `..bots.abstract`. *Evidence*: F003

### 2.3 Recent History (Relevant)

The FEAT-201 (ai-parrot-embeddings) extraction was completed recently and
provides the proven pattern for this extraction. Key artifacts:
- Spec: `sdd/specs/ai-parrot-embeddings.spec.md`
- Proposal: `sdd/proposals/ai-parrot-embeddings.proposal.md`
- Migration guide: `docs/migration/feat-201-ai-parrot-embeddings.md`

---

## 3. Probable Scope

### What's New

- **`packages/ai-parrot-server/`** — New satellite package directory with
  `pyproject.toml`, tests, and PEP 420 namespace structure
- **`parrot/mcp/oauth_server.py`** — Split from `oauth.py`, contains
  `OAuthAuthorizationServer`, `OAuthRoutesMixin`
- **`parrot/mcp/server_factories.py`** — Split from `integration.py`, contains
  `create_*_mcp_server` factory functions
- **`parrot/security/vault_utils.py`** — Relocated from `parrot/handlers/vault_utils.py`
- **`parrot/security/credentials_utils.py`** — Relocated from `parrot/handlers/credentials_utils.py`
- **`docs/migration/feat-203-ai-parrot-server.md`** — Migration guide
- **Host `__init__.py` updates** — Add `extend_path` calls to `parrot/handlers/__init__.py`,
  `parrot/manager/__init__.py`, `parrot/services/__init__.py`,
  `parrot/scheduler/__init__.py`, `parrot/autonomous/__init__.py`,
  `parrot/mcp/__init__.py`, `parrot/a2a/__init__.py`

### What Changes

- **`parrot/mcp/integration.py`** — Remove server factory functions (moved to
  `server_factories.py` in satellite). Keep MCPClient, MCPToolProxy,
  MCPEnabledMixin (consumer side). Add `__getattr__` lazy re-exports for
  backward compatibility of factory function imports. *Evidence*: F002

- **`parrot/mcp/oauth.py`** — Remove OAuthAuthorizationServer, OAuthRoutesMixin
  (moved to `oauth_server.py` in satellite). Keep OAuthManager, TokenStore
  implementations, NetSuiteM2MAuth (consumer side). *Evidence*: F002

- **`parrot/mcp/__init__.py`** — Add `extend_path` call. Update exports:
  keep consumer exports, add lazy `__getattr__` for server exports that
  resolve from satellite. *Evidence*: F006

- **`parrot/a2a/__init__.py`** — Add `extend_path` call. Update exports:
  keep consumer exports, add lazy `__getattr__` for A2AServer,
  A2AEnabledMixin, security classes. *Evidence*: F003, F006

- **`parrot/handlers/__init__.py`** — Add `extend_path` call. All handler
  classes resolve from satellite via namespace merging. *Evidence*: F001, F006

- **`parrot/handlers/vault_utils.py`** — Replace with import redirect to
  `parrot.security.vault_utils` for backward compat during transition.

- **`parrot/handlers/credentials_utils.py`** — Same redirect pattern.

- **`packages/ai-parrot/pyproject.toml`** — Add `server` and `all` meta-extras
  that pull `ai-parrot-server`. Remove server-only dependencies from core
  (APScheduler, navigator-auth views, etc.).

- **`app.py` / `appauto.py`** — Update imports: `from parrot.manager import BotManager`
  now resolves via namespace merging to the satellite.

### What's Untouched (Non-Goals)

- **AgentRegistry** (`parrot/registry/`) — stays in core unchanged
- **Bot/Agent abstractions** (`parrot/bots/`) — stays in core
- **LLM clients** (`parrot/clients/`) — stays in core
- **Tool framework** (`parrot/tools/`) — stays in core
- **Memory** (`parrot/memory/`) — stays in core
- **Embeddings/Stores/Rerankers** — already in ai-parrot-embeddings satellite
- **Core config** (`parrot/conf.py`, `parrot/core/`) — stays in core

### Patterns to Follow

- **FEAT-201 PEP 420 structure**: No `__init__.py` in satellite namespace dirs.
  Host `__init__.py` uses `extend_path(__path__, __name__)`. Satellite
  `pyproject.toml` sets `namespaces = true`. *Evidence*: F006

- **Lazy `__getattr__` in host `__init__.py`**: For backward-compatible imports
  of server classes that now live in satellite. Pattern proven in
  `parrot/rerankers/__init__.py`. *Evidence*: F006

- **String-dispatch via `importlib.import_module`**: For dynamic resolution
  across distribution boundaries. Pattern proven in
  `parrot/embeddings/registry.py`. *Evidence*: F006

- **Wheel-content test**: Satellite must include a test asserting zero
  `__init__.py` files at namespace levels. Pattern proven in
  `packages/ai-parrot-embeddings/tests/test_wheel_layout.py`. *Evidence*: F006

- **Namespace-import test**: Satellite must verify cross-distribution imports
  work correctly. *Evidence*: F006

### Integration Risks

- **Import path breakage**: Any third-party code or deployment script that does
  `from parrot.handlers import X` will fail unless `ai-parrot-server` is
  installed. Mitigated by: (a) meta-extras in core's `all` extra, (b) helpful
  error message in host `__getattr__`, (c) migration guide. *Evidence*: F001

- **Circular imports**: BotManager imports handlers which may import from
  BotManager. Since all move to the same satellite, the circular import
  topology is preserved. No new circularity introduced. *Evidence*: F005

- **MCP consolidation complexity**: Merging `parrot/services/mcp/` into
  `parrot/mcp/` in the satellite requires reconciling two implementations
  (ParrotMCPServer vs MCPServer). This is the highest-risk subtask.
  *Evidence*: F002, F004

- **Scheduler decorator migration**: `github_reviewer.py` and
  `jira_specialist.py` import scheduler decorators. These bots become
  server-only — users who import them without `ai-parrot-server` get an
  ImportError. Mitigated by documenting in migration guide. *Evidence*: F004

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | FEAT-201 PEP 420 pattern is directly replicable | F006 | **high** | Proven, tested, documented precedent |
| C2 | A2A server/client split is clean (TYPE_CHECKING only) | F003 | **high** | Direct code inspection, no runtime cross-deps |
| C3 | MCP server/client split requires hybrid file splitting | F002 | **high** | integration.py and oauth.py have both sides |
| C4 | BotManager moves cleanly (all consumers co-move or TYPE_CHECKING) | F005 | **high** | Verified: autonomous, handlers, services all move |
| C5 | handlers/ is entirely server-side infrastructure | F001 | **high** | 59 files, all aiohttp BaseView subclasses |
| C6 | vault_utils must be relocated to shared core location | F001 | **high** | auth/oauth2_base.py:166 imports it (stays in core) |
| C7 | Scheduler decorators in 2 core bots become server-only | F004 | **high** | github_reviewer:51, jira_specialist:51 |
| C8 | services/mcp/ consolidation into mcp/ is feasible | F002, F004 | **medium** | Two implementations with different integration patterns |
| C9 | No other core module imports BotManager at runtime | F005 | **high** | All imports are TYPE_CHECKING |
| C10 | app.py/appauto.py continue working via namespace merging | F005, F006 | **high** | extend_path makes satellite modules transparent |

Distribution: **8** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Should BotManager stay in core or move to satellite?** — *Resolved*:
  Move to satellite. All BotManager consumers are co-moving or TYPE_CHECKING.
  *Resolves claims*: C4, C9

- [x] **Should app.py/appauto.py move to satellite?** — *Resolved*: Stay in
  repo root as standalone scripts importing from satellite via namespace merging.
  *Resolves claims*: C10

- [x] **How to handle scheduler decorators in core bots?** — *Resolved*: Move
  entire scheduler to satellite. github_reviewer and jira_specialist become
  server-only bots.
  *Resolves claims*: C7

- [x] **Should services/mcp/ be consolidated with mcp/ in satellite?** —
  *Resolved*: Yes, consolidate into unified parrot/mcp/ namespace in satellite.
  *Resolves claims*: C8

### Unresolved (defer to spec / implementation)

- [ ] **What server-specific dependencies can be removed from core's
  pyproject.toml?** — *Owner*: spec phase. Requires auditing which deps are
  used only by server modules (APScheduler, navigator-auth views, aiohttp-cors,
  etc.).

- [ ] **Should the `parrot` CLI entry point move to satellite?** — *Owner*: spec
  phase. Currently `parrot.cli:cli` in core — check if CLI commands are
  server-specific or general-purpose.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-203`** — *Rationale*: High overall confidence (8/9 high
claims). The extraction scope is well-defined, the FEAT-201 precedent provides
a proven template, and all architectural decisions are resolved. The spec should
detail the file-by-file migration plan, pyproject.toml configuration, and test
strategy.

### Alternatives

- **`/sdd-brainstorm FEAT-203`** — if you want to explore alternative
  separation boundaries (e.g., keeping some handlers in core, different
  MCP consolidation strategies).
- **`/sdd-task FEAT-203`** — premature — this is a large extraction requiring
  a detailed spec first.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-203/state.json` |
| Source (raw) | `sdd/state/FEAT-203/source.md` |
| Finding: handlers structure | `sdd/state/FEAT-203/findings/F001-handlers-structure.md` |
| Finding: MCP server/client split | `sdd/state/FEAT-203/findings/F002-mcp-server-client-split.md` |
| Finding: A2A server/client split | `sdd/state/FEAT-203/findings/F003-a2a-server-client-split.md` |
| Finding: services/scheduler/autonomous | `sdd/state/FEAT-203/findings/F004-services-scheduler-autonomous.md` |
| Finding: BotManager coupling | `sdd/state/FEAT-203/findings/F005-botmanager-coupling.md` |
| Finding: FEAT-201 precedent | `sdd/state/FEAT-203/findings/F006-feat201-precedent.md` |

**Budget consumed** (loose profile):
- Files read: ~85 / 100 (via 6 parallel research agents)
- Grep calls: ~50 / 60
- Git calls: ~5 / 20
- Wall time: ~120s / 900s
- Truncated: **no**

**Mode determination**: `enrichment` (architecture extraction, not bug investigation)

---

## 8. Satellite Package Structure (Reference)

```
packages/ai-parrot-server/
├── pyproject.toml
├── README.md
├── src/parrot/
│   ├── .gitkeep                          (NO __init__.py — PEP 420)
│   │
│   ├── manager/                          (NO __init__.py)
│   │   ├── manager.py                    BotManager
│   │   └── ephemeral.py                  EphemeralRegistry
│   │
│   ├── handlers/                         (NO __init__.py)
│   │   ├── agent.py, bots.py, chat.py, chat_interaction.py, ...
│   │   ├── agents/                       AgentHandler, UserAgentHandler
│   │   ├── crew/                         CrewHandler, CrewExecutionHandler
│   │   ├── database/                     DB schema handlers
│   │   ├── jobs/                         JobManager, RedisJobStore
│   │   ├── models/                       Handler data models
│   │   ├── scraping/                     ScrapingHandler
│   │   └── stores/                       VectorStoreHandler
│   │
│   ├── mcp/                              (NO __init__.py)
│   │   ├── server.py                     MCPServer (consolidated)
│   │   ├── server_factories.py           create_*_mcp_server (split from integration.py)
│   │   ├── oauth_server.py               OAuthAuthorizationServer (split from oauth.py)
│   │   ├── adapter.py                    MCPToolAdapter
│   │   ├── cli.py                        Click CLI
│   │   ├── wrapper.py                    Config loading
│   │   ├── chrome.py                     Chrome management
│   │   ├── resources.py                  MCPResource
│   │   ├── parrot_server.py              ParrotMCPServer (from services/mcp/server.py)
│   │   ├── simple_server.py              SimpleMCPServer (from services/mcp/simple.py)
│   │   └── transports/
│   │       ├── base.py, stdio.py, http.py, sse.py
│   │       ├── unix.py, websocket.py, quic.py, grpc_session.py
│   │       └── __init__.py
│   │
│   ├── a2a/                              (NO __init__.py)
│   │   ├── server.py                     A2AServer, A2AEnabledMixin
│   │   └── security.py                   A2ASecurityMiddleware
│   │
│   ├── services/                         (NO __init__.py)
│   │   ├── agent_service.py              AgentService
│   │   ├── client.py                     AgentServiceClient
│   │   ├── delivery.py                   DeliveryRouter
│   │   ├── heartbeat.py                  HeartbeatScheduler
│   │   ├── redis_listener.py             RedisTaskListener
│   │   ├── task_queue.py                 TaskQueue
│   │   ├── worker_pool.py               WorkerPool
│   │   ├── whatsapp.py                   WhatsApp bridge
│   │   ├── o365_remote_auth.py           O365 remote auth
│   │   ├── identity_mapping.py           Identity mapping
│   │   ├── vault_token_sync.py           Token sync
│   │   └── models.py                     Service models
│   │
│   ├── scheduler/                        (NO __init__.py)
│   │   ├── manager.py                    AgentSchedulerManager
│   │   ├── models.py                     AgentSchedule ORM
│   │   └── functions/                    Callback registry
│   │
│   └── autonomous/                       (NO __init__.py)
│       ├── orchestrator.py               AutonomousOrchestrator
│       ├── redis_jobs.py, webhooks.py, scheduler.py
│       ├── admin.py, cli.py, evb.py
│       ├── deploy/                       Installer, templates
│       └── transport/                    Filesystem transport
│
└── tests/
    ├── test_wheel_layout.py              PEP 420 compliance
    ├── test_namespace_imports.py          Cross-distribution imports
    └── ...
```

---

## 9. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Research method | 6 parallel Explore agents (handlers, MCP, A2A, services/scheduler/autonomous, FEAT-201 precedent, cross-cutting deps) |
| Operator | jlara@trocglobal.com |
