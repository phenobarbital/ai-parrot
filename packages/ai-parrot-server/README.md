# ai-parrot-server

Server infrastructure for the [AI-Parrot](https://github.com/phenobarbital/ai-parrot) framework, extracted as a PEP 420 implicit namespace satellite package.

## Overview

`ai-parrot-server` contributes server-side modules to the `parrot.*` namespace alongside the core `ai-parrot` package. All existing import paths remain unchanged — `from parrot.handlers import ChatbotHandler` works identically whether using the combined install or the split install.

## What's Included

| Module | Contents |
|---|---|
| `parrot.handlers` | ~59 aiohttp HTTP handler files (ChatbotHandler, BotHandler, etc.) |
| `parrot.manager` | BotManager, EphemeralRegistry |
| `parrot.services` | AgentService, delivery, heartbeat, worker pool, WhatsApp bridge, etc. |
| `parrot.scheduler` | AgentSchedulerManager, schedule decorators, models, functions |
| `parrot.autonomous` | AutonomousOrchestrator, transport layer (parrot-fs), deploy tools |
| `parrot.mcp` (server) | MCPServer, MCPToolAdapter, MCPServerConfig, transports, CLI |
| `parrot.a2a` (server) | A2AServer, A2AEnabledMixin, A2ASecurityMiddleware |

## Installation

```bash
# Core framework only (no server infrastructure)
pip install ai-parrot

# Core + all server infrastructure
pip install ai-parrot-server

# Core + server with specific extras
pip install ai-parrot-server[scheduler]    # + APScheduler
pip install ai-parrot-server[mcp]          # + MCP server transports (QUIC, gRPC)
pip install ai-parrot-server[a2a]          # + A2A server (JWT auth)
pip install ai-parrot-server[autonomous]   # + autonomous orchestrator (aiofiles)
pip install ai-parrot-server[all]          # everything

# Via host meta-extra
pip install ai-parrot[server]             # convenience alias for ai-parrot-server[all]
pip install ai-parrot[all]               # includes ai-parrot-server[all]
```

## How It Works

This package uses [PEP 420 implicit namespace packages](https://peps.python.org/pep-0420/). It contributes to the same `parrot.*` namespace as `ai-parrot` without any `__init__.py` files at the namespace levels. Python's import system merges the two distributions' directory trees transparently.

The host `parrot.*` `__init__.py` files use `pkgutil.extend_path` and lazy `__getattr__` patterns to expose server classes when this satellite is installed, and provide helpful `ImportError` messages when it is not.

## Migration

See [`docs/migration/feat-203-ai-parrot-server.md`](../../docs/migration/feat-203-ai-parrot-server.md) for the full migration guide.
