---
type: Wiki Overview
title: 'TASK-1377: Satellite tests — wheel layout and namespace imports'
id: doc:sdd-tasks-completed-task-1377-satellite-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 13. Creates automated tests verifying PEP 420 compliance
  and cross-distribution import resolution for the ai-parrot-server satellite package.
relates_to:
- concept: mod:parrot.a2a
  rel: mentions
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.manager
  rel: mentions
- concept: mod:parrot.mcp.server
  rel: mentions
- concept: mod:parrot.scheduler
  rel: mentions
- concept: mod:parrot.services
  rel: mentions
---

# TASK-1377: Satellite tests — wheel layout and namespace imports

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1376
**Assigned-to**: unassigned

## Context
Implements Module 13. Creates automated tests verifying PEP 420 compliance and cross-distribution import resolution for the ai-parrot-server satellite package.

## Scope
- Create `packages/ai-parrot-server/tests/test_wheel_layout.py`:
  - Assert zero `__init__.py` at 8 namespace levels: `parrot/`, `parrot/mcp/`, `parrot/a2a/`, `parrot/handlers/`, `parrot/manager/`, `parrot/services/`, `parrot/scheduler/`, `parrot/autonomous/`
  - Assert presence of expected backend files (manager/manager.py, a2a/server.py, etc.)
- Create `packages/ai-parrot-server/tests/test_namespace_imports.py`:
  - Parametrized tests: `from parrot.handlers import ChatbotHandler`, `from parrot.manager import BotManager`, `from parrot.a2a import A2AServer`, `from parrot.mcp.server import MCPServer`, `from parrot.services import AgentService`, `from parrot.scheduler import AgentSchedulerManager`
  - Assert each resolves from satellite (`"ai-parrot-server"` in `__file__`)
  - Test lazy `__getattr__` from host `__init__.py`
- Create `packages/ai-parrot-server/tests/conftest.py`

**NOT in scope**: Implementation code changes.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/test_wheel_layout.py` | CREATE | PEP 420 compliance tests |
| `packages/ai-parrot-server/tests/test_namespace_imports.py` | CREATE | Cross-distribution import tests |
| `packages/ai-parrot-server/tests/conftest.py` | CREATE | Pytest configuration |

## Codebase Contract (Anti-Hallucination)

### Reference Patterns
```python
# Reference: packages/ai-parrot-embeddings/tests/test_wheel_layout.py
# Proven wheel test pattern — follow this structure for PEP 420 validation

# Reference: packages/ai-parrot-embeddings/tests/test_namespace_imports.py
# Proven import test pattern — follow this structure for cross-distribution assertions
```

### Expected Satellite Structure
```
packages/ai-parrot-server/src/parrot/
├── mcp/           # MCPServer, transports, adapter (TASK-1369)
├── a2a/           # A2AServer, cards (TASK-1370)
├── handlers/      # ChatbotHandler, AgentHandler (TASK-1371)
├── manager/       # BotManager (TASK-1372)
├── services/      # AgentService, client, delivery (TASK-1373)
├── scheduler/     # AgentSchedulerManager, models, functions (TASK-1374)
└── autonomous/    # AutonomousOrchestrator, transport, deploy (TASK-1375)
```
None of these directories should have `__init__.py` (PEP 420 namespace packages).

### 8 Namespace Levels to Verify
1. `parrot/` — top-level namespace
2. `parrot/mcp/` — MCP server namespace
3. `parrot/a2a/` — A2A server namespace
4. `parrot/handlers/` — HTTP handlers namespace
5. `parrot/manager/` — Bot manager namespace
6. `parrot/services/` — Services namespace
7. `parrot/scheduler/` — Scheduler namespace
8. `parrot/autonomous/` — Autonomous namespace

### 6 Cross-Distribution Import Assertions
1. `from parrot.handlers import ChatbotHandler`
2. `from parrot.manager import BotManager`
3. `from parrot.a2a import A2AServer`
4. `from parrot.mcp.server import MCPServer`
5. `from parrot.services import AgentService`
6. `from parrot.scheduler import AgentSchedulerManager`

## Implementation Notes

### Step-by-Step Procedure
1. Read the reference tests from ai-parrot-embeddings:
   ```bash
   cat packages/ai-parrot-embeddings/tests/test_wheel_layout.py
   cat packages/ai-parrot-embeddings/tests/test_namespace_imports.py
   cat packages/ai-parrot-embeddings/tests/conftest.py
   ```
2. Create `conftest.py` with any shared fixtures (sys.path adjustments, etc.)
3. Create `test_wheel_layout.py`:
   - Use `pathlib.Path` to locate the satellite `src/parrot/` directory
   - Parametrize over the 8 namespace directories
   - Assert no `__init__.py` exists at each level
   - Assert expected backend files exist (e.g., `manager/manager.py`, `a2a/server.py`, `mcp/server.py`)
4. Create `test_namespace_imports.py`:
   - Use `pytest.mark.parametrize` for the 6 import assertions
   - Each test imports the class and verifies `"ai-parrot-server"` appears in the resolved file path
   - Add a test for lazy `__getattr__` — import via the host stub and verify it delegates to satellite

### Key Constraints
- Tests must be runnable with `pytest packages/ai-parrot-server/tests/ -v`
- Tests must work in the uv workspace (both packages installed in dev mode)
- Do NOT import anything that requires external services (Redis, PostgreSQL, etc.) — use import-level assertions only
- Follow the exact patterns from ai-parrot-embeddings tests for consistency

## Acceptance Criteria
- [ ] `test_wheel_layout.py` passes
- [ ] `test_namespace_imports.py` passes
- [ ] All 8 namespace levels verified `__init__.py`-free
- [ ] At least 6 cross-distribution import assertions pass
- [ ] Tests runnable with `pytest packages/ai-parrot-server/tests/ -v`

## Test Specification
```python
# test_wheel_layout.py
import pathlib
import pytest

SATELLITE_ROOT = pathlib.Path(__file__).parent.parent / "src" / "parrot"

NAMESPACE_DIRS = [
    "",           # parrot/
    "mcp",        # parrot/mcp/
    "a2a",        # parrot/a2a/
    "handlers",   # parrot/handlers/
    "manager",    # parrot/manager/
    "services",   # parrot/services/
    "scheduler",  # parrot/scheduler/
    "autonomous", # parrot/autonomous/
]

@pytest.mark.parametrize("subdir", NAMESPACE_DIRS)
def test_no_init_py(subdir):
    """PEP 420: namespace directories must not contain __init__.py."""
    d = SATELLITE_ROOT / subdir if subdir else SATELLITE_ROOT
    init = d / "__init__.py"
    assert not init.exists(), f"__init__.py found in {d}"

EXPECTED_FILES = [
    "manager/manager.py",
    "a2a/server.py",
    "mcp/server.py",
    "services/agent_service.py",
    "scheduler/manager.py",
    "autonomous/orchestrator.py",
    "handlers/chatbot.py",
]

@pytest.mark.parametrize("relpath", EXPECTED_FILES)
def test_expected_file_exists(relpath):
    """Expected backend files exist in satellite."""
    assert (SATELLITE_ROOT / relpath).exists(), f"{relpath} missing"


# test_namespace_imports.py
import pytest

IMPORT_CASES = [
    ("parrot.handlers", "ChatbotHandler"),
    ("parrot.manager", "BotManager"),
    ("parrot.a2a", "A2AServer"),
    ("parrot.mcp.server", "MCPServer"),
    ("parrot.services", "AgentService"),
    ("parrot.scheduler", "AgentSchedulerManager"),
]

@pytest.mark.parametrize("module,name", IMPORT_CASES)
def test_cross_distribution_import(module, name):
    """Import resolves from satellite (ai-parrot-server in path)."""
    import importlib
    mod = importlib.import_module(module)
    obj = getattr(mod, name)
    assert obj is not None
    # Verify resolved from satellite
    source_file = getattr(mod, "__file__", "") or ""
    assert "ai-parrot-server" in source_file, (
        f"{module}.{name} did not resolve from satellite: {source_file}"
    )
```

## Agent Instructions
1. Read the reference test files from ai-parrot-embeddings first.
2. Follow the exact patterns and adjust for ai-parrot-server's namespace structure.
3. Create all three files (`conftest.py`, `test_wheel_layout.py`, `test_namespace_imports.py`).
4. Run `source .venv/bin/activate && pytest packages/ai-parrot-server/tests/ -v` to verify.
5. Commit with message: `sdd: add satellite tests for ai-parrot-server`

## Completion Note
*(Agent fills this in when done)*
