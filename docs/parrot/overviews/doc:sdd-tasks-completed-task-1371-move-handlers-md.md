---
type: Wiki Overview
title: 'TASK-1371: Move handlers/ to satellite'
id: doc:sdd-tasks-completed-task-1371-move-handlers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 7. Largest single move — ~59 Python files across 7 subdirectories.
  All are aiohttp BaseView subclasses for HTTP endpoints. The host `handlers/__init__.py`
  already has `extend_path` and lazy `__getattr__` (from TASK-1367), and `vault_utils.py`
  / `credentials_util
relates_to:
- concept: mod:parrot.auth.oauth2
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.clients.factory
  rel: mentions
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.handlers.agents
  rel: mentions
- concept: mod:parrot.handlers.credentials_utils
  rel: mentions
- concept: mod:parrot.handlers.vault_utils
  rel: mentions
- concept: mod:parrot.mcp.integration
  rel: mentions
- concept: mod:parrot.memory
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.registry.registry
  rel: mentions
- concept: mod:parrot.security.credentials_utils
  rel: mentions
- concept: mod:parrot.security.vault_utils
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

# TASK-1371: Move handlers/ to satellite

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1366, TASK-1367
**Assigned-to**: unassigned

## Context
Implements Module 7. Largest single move — ~59 Python files across 7 subdirectories. All are aiohttp BaseView subclasses for HTTP endpoints. The host `handlers/__init__.py` already has `extend_path` and lazy `__getattr__` (from TASK-1367), and `vault_utils.py` / `credentials_utils.py` have already been relocated to `parrot/security/` with redirect stubs left behind (from TASK-1366).

## Scope
- `git mv` the entire contents of `packages/ai-parrot/src/parrot/handlers/` to `packages/ai-parrot-server/src/parrot/handlers/`, EXCEPT:
  - `__init__.py` — stays in host (already updated with extend_path in TASK-1367)
  - `vault_utils.py` — stays as redirect stub (already relocated in TASK-1366)
  - `credentials_utils.py` — stays as redirect stub
- Move includes all subdirectories: agents/, crew/, database/, jobs/, models/, scraping/, stores/
- Verify internal handler imports still work (they reference each other heavily)
- Verify imports from core modules (parrot.bots.abstract, parrot.tools.manager, parrot.registry, etc.) still resolve

**NOT in scope**: Moving BotManager (TASK-1372), modifying handler code logic, changing handler imports of core modules.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/*.py` | CREATE (git mv) | ~56 handler files (all except __init__.py, vault_utils.py, credentials_utils.py) |
| `packages/ai-parrot-server/src/parrot/handlers/agents/` | CREATE (git mv) | Agent handler subdirectory |
| `packages/ai-parrot-server/src/parrot/handlers/crew/` | CREATE (git mv) | Crew handler subdirectory |
| `packages/ai-parrot-server/src/parrot/handlers/database/` | CREATE (git mv) | Database handler subdirectory |
| `packages/ai-parrot-server/src/parrot/handlers/jobs/` | CREATE (git mv) | Job management handler subdirectory |
| `packages/ai-parrot-server/src/parrot/handlers/models/` | CREATE (git mv) | Handler model subdirectory |
| `packages/ai-parrot-server/src/parrot/handlers/scraping/` | CREATE (git mv) | Scraping handler subdirectory |
| `packages/ai-parrot-server/src/parrot/handlers/stores/` | CREATE (git mv) | Vector store handler subdirectory |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# handlers/__init__.py uses __getattr__ for lazy loading (lines 5-52) — STAYS in host
# Example from __init__.py:
def __getattr__(name: str):
    if name == "ChatbotHandler":
        from parrot.handlers.chatbot import ChatbotHandler
        return ChatbotHandler
    ...

# handlers/vault_utils.py — redirect to parrot.security.vault_utils — STAYS in host
# handlers/credentials_utils.py — redirect to parrot.security.credentials_utils — STAYS in host

# All handler files import from core (examples):
from parrot.bots.abstract import AbstractBot
from parrot.tools.manager import ToolManager
from parrot.mcp.integration import MCPIntegration
from parrot.memory import ConversationMemory
from parrot.registry.registry import AgentRegistry
from parrot.clients.factory import ClientFactory
from parrot.auth.oauth2 import OAuth2Handler

# Handler subdirectories have their own __init__.py files — these MOVE with the handlers
# (they are internal package init files, not namespace-level)

# Handler files reference each other:
from parrot.handlers.credentials_utils import encrypt_credential  # via redirect stub
from parrot.handlers.base import BaseHandler
```

### Existing Signatures to Use
```python
# Key handler classes (partial list):
# handlers/chatbot.py — ChatbotHandler (BaseView)
# handlers/bot.py — BotHandler (BaseView)
# handlers/chat.py — ChatHandler (BaseView)
# handlers/integrations.py — IntegrationsHandler (BaseView)
# handlers/agent_talk.py — AgentTalk (BaseView)
# handlers/base.py — BaseHandler (utility base)
# handlers/agents/ — subdirectory with agent-specific handlers
# handlers/crew/ — subdirectory with crew/orchestration handlers
# handlers/database/ — subdirectory with DB handlers
# handlers/jobs/ — subdirectory with job management handlers
# handlers/models/ — subdirectory with handler-specific models
# handlers/scraping/ — subdirectory with scraping handlers
# handlers/stores/ — subdirectory with vector store handlers
```

### Does NOT Exist
- ~~`handlers/__init__.py` in satellite~~ — PEP 420 forbids it; host __init__.py stays
- ~~`handlers/vault_utils.py` in satellite~~ — stays as redirect in host
- ~~`handlers/credentials_utils.py` in satellite~~ — stays as redirect in host
- ~~Handler files in satellite~~ — satellite handlers/ directory does not exist yet

## Implementation Notes

### Step-by-Step Procedure
1. Ensure satellite directory exists: `packages/ai-parrot-server/src/parrot/handlers/`
2. List all files and subdirectories in host handlers/, excluding the three that stay:
   ```bash
   # Get list of all files to move (excluding __init__.py, vault_utils.py, credentials_utils.py)
   find packages/ai-parrot/src/parrot/handlers/ -type f -name "*.py" \
     ! -name "__init__.py" \
     ! -name "vault_utils.py" \
     ! -name "credentials_utils.py"
   ```
3. Move subdirectories first (they contain their own `__init__.py` which is fine to move):
   ```bash
   git mv packages/ai-parrot/src/parrot/handlers/agents/ packages/ai-parrot-server/src/parrot/handlers/agents/
   git mv packages/ai-parrot/src/parrot/handlers/crew/ packages/ai-parrot-server/src/parrot/handlers/crew/
   git mv packages/ai-parrot/src/parrot/handlers/database/ packages/ai-parrot-server/src/parrot/handlers/database/
   git mv packages/ai-parrot/src/parrot/handlers/jobs/ packages/ai-parrot-server/src/parrot/handlers/jobs/
   git mv packages/ai-parrot/src/parrot/handlers/models/ packages/ai-parrot-server/src/parrot/handlers/models/
   git mv packages/ai-parrot/src/parrot/handlers/scraping/ packages/ai-parrot-server/src/parrot/handlers/scraping/
   git mv packages/ai-parrot/src/parrot/handlers/stores/ packages/ai-parrot-server/src/parrot/handlers/stores/
   ```
4. Move individual handler files (each .py file except the three that stay):
   ```bash
   # Move each .py file individually, e.g.:
   git mv packages/ai-parrot/src/parrot/handlers/chatbot.py packages/ai-parrot-server/src/parrot/handlers/chatbot.py
   git mv packages/ai-parrot/src/parrot/handlers/bot.py packages/ai-parrot-server/src/parrot/handlers/bot.py
   # ... repeat for all remaining .py files
   ```
5. Verify host handlers/ directory retains only: `__init__.py`, `vault_utils.py`, `credentials_utils.py`
6. Verify handler imports from core modules resolve (no changes needed — core paths unchanged)
7. Verify handler cross-references work (e.g., `from parrot.handlers.base import BaseHandler`)

### Key Constraints
- Do NOT create `__init__.py` in satellite `handlers/` — PEP 420 namespace package
- Do NOT move host `handlers/__init__.py` — it has extend_path and lazy __getattr__
- Do NOT move `vault_utils.py` or `credentials_utils.py` — they are redirect stubs that stay
- Subdirectory `__init__.py` files (e.g., `agents/__init__.py`) DO move — they are internal package init files
- Handler files that import `from parrot.handlers.credentials_utils import ...` will still work via the redirect stub in host
- No import path changes needed in handler code — they all use absolute `parrot.handlers.*` or `parrot.*` imports

### Post-Move Verification
```bash
# Verify host retains only the expected files
ls packages/ai-parrot/src/parrot/handlers/
# Expected: __init__.py  vault_utils.py  credentials_utils.py

# Verify satellite has all handler files
find packages/ai-parrot-server/src/parrot/handlers/ -name "*.py" | wc -l
# Expected: ~56 files
```

## Acceptance Criteria
- [ ] All handler files exist in satellite under `packages/ai-parrot-server/src/parrot/handlers/`
- [ ] `from parrot.handlers import ChatbotHandler` resolves from satellite (via host __getattr__ + namespace merging)
- [ ] Handler internal imports work (e.g., `from parrot.handlers.base import BaseHandler`)
- [ ] Handler imports of redirect stubs work (e.g., `from parrot.handlers.credentials_utils import encrypt_credential`)
- [ ] Handler imports of core modules work (e.g., `from parrot.bots.abstract import AbstractBot`)
- [ ] Host handlers/ directory retains only: `__init__.py`, `vault_utils.py` (redirect), `credentials_utils.py` (redirect)
- [ ] No `__init__.py` in satellite `handlers/` root (PEP 420)
- [ ] Subdirectory `__init__.py` files exist in satellite (agents/, crew/, etc.)
- [ ] Existing test suite passes

## Test Specification
```python
def test_handler_import_via_getattr():
    """ChatbotHandler resolves via host __getattr__ + satellite namespace."""
    from parrot.handlers import ChatbotHandler
    assert ChatbotHandler is not None

def test_handler_direct_import():
    """Direct import from handler module works."""
    from parrot.handlers.chatbot import ChatbotHandler
    assert ChatbotHandler is not None

def test_handler_subdirectory_import():
    """Subdirectory handler imports work."""
    from parrot.handlers.agents import AgentHandler  # or whatever the actual class is
    assert AgentHandler is not None

def test_credentials_redirect_still_works():
    """Redirect stubs in host still resolve."""
    from parrot.handlers.credentials_utils import encrypt_credential
    assert callable(encrypt_credential)

def test_vault_redirect_still_works():
    """Redirect stubs in host still resolve."""
    from parrot.handlers.vault_utils import store_vault_credential
    assert callable(store_vault_credential)

def test_host_handlers_only_stubs():
    """Host handlers/ retains only __init__.py and redirect stubs."""
    import pathlib
    host_handlers = pathlib.Path("packages/ai-parrot/src/parrot/handlers")
    py_files = {f.name for f in host_handlers.glob("*.py")}
    assert py_files == {"__init__.py", "vault_utils.py", "credentials_utils.py"}
```

## Agent Instructions
1. Read the host `handlers/__init__.py` to understand the lazy __getattr__ pattern before moving files.
2. List ALL files in `handlers/` (including subdirectories) to build the complete move list.
3. Move subdirectories first, then individual files.
4. After moving, verify the host directory retains only the three expected files.
5. Run a quick import test to verify namespace merging works.
6. Commit with message: `sdd: move handlers to satellite for ai-parrot-server`

## Completion Note
*(Agent fills this in when done)*
