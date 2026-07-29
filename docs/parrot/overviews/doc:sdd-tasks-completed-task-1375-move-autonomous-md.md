---
type: Wiki Overview
title: 'TASK-1375: Move autonomous/ to satellite'
id: doc:sdd-tasks-completed-task-1375-move-autonomous-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 11. Moves the autonomous orchestrator, transport layer,
  deployment tools, and CLI to the satellite package.
relates_to:
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.cli
  rel: mentions
- concept: mod:parrot.core.events
  rel: mentions
- concept: mod:parrot.core.hooks
  rel: mentions
---

# TASK-1375: Move autonomous/ to satellite

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1367
**Assigned-to**: unassigned

## Context
Implements Module 11. Moves the autonomous orchestrator, transport layer, deployment tools, and CLI to the satellite package.

## Scope
- `git mv` entire contents of `packages/ai-parrot/src/parrot/autonomous/` to satellite (except `__init__.py`):
  - orchestrator.py, redis_jobs.py, webhooks.py, scheduler.py, admin.py, cli.py, evb.py, example.py
  - deploy/ directory (installer.py, templates.py)
  - transport/ directory (base.py, filesystem/ with channel.py, cli.py, config.py, feed.py, hook.py, inbox.py, registry.py, reservation.py, transport.py)
- Move `parrot-fs` console_script to satellite's pyproject.toml
- Remove `parrot-fs` entry from host's pyproject.toml `[project.scripts]`
- Host `autonomous/__init__.py` retains `extend_path` only (from TASK-1367)

**NOT in scope**: Modifying orchestrator internals. Host pyproject.toml `parrot-fs` removal deferred to TASK-1376.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py` | CREATE (git mv) | AutonomousOrchestrator |
| `packages/ai-parrot-server/src/parrot/autonomous/redis_jobs.py` | CREATE (git mv) | Redis job queue |
| `packages/ai-parrot-server/src/parrot/autonomous/webhooks.py` | CREATE (git mv) | Webhook handlers |
| `packages/ai-parrot-server/src/parrot/autonomous/scheduler.py` | CREATE (git mv) | Autonomous scheduler |
| `packages/ai-parrot-server/src/parrot/autonomous/admin.py` | CREATE (git mv) | Admin interface |
| `packages/ai-parrot-server/src/parrot/autonomous/cli.py` | CREATE (git mv) | CLI commands |
| `packages/ai-parrot-server/src/parrot/autonomous/evb.py` | CREATE (git mv) | Event bridge |
| `packages/ai-parrot-server/src/parrot/autonomous/example.py` | CREATE (git mv) | Example usage |
| `packages/ai-parrot-server/src/parrot/autonomous/deploy/` | CREATE (git mv) | Deploy tools (installer.py, templates.py) |
| `packages/ai-parrot-server/src/parrot/autonomous/transport/` | CREATE (git mv) | Transport layer + filesystem/ subdirectory |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/autonomous/__init__.py — currently empty; gets extend_path in TASK-1367

# parrot/autonomous/orchestrator.py:
# - AutonomousOrchestrator class (line 112)
# - ExecutionTarget enum (line 40)
# - ExecutionRequest dataclass (line 47)
# Imports: parrot.core.events, parrot.core.hooks
# TYPE_CHECKING: ..scheduler, ..manager, ..registry, ..bots.orchestration, ..bots.abstract
from parrot.autonomous.orchestrator import AutonomousOrchestrator

# parrot/autonomous/transport/filesystem/cli.py:
# - main() function — the parrot-fs entry point
# Host pyproject.toml [project.scripts]:
#   parrot-fs = "parrot.autonomous.transport.filesystem.cli:main" (line 99)
```

### Does NOT Exist
- ~~Runtime imports of autonomous from core~~ — only examples reference it
- ~~autonomous/__init__.py with real content~~ — currently empty

## Implementation Notes

### Step-by-Step Procedure
1. Ensure satellite directories exist:
   ```bash
   mkdir -p packages/ai-parrot-server/src/parrot/autonomous/
   mkdir -p packages/ai-parrot-server/src/parrot/autonomous/deploy/
   mkdir -p packages/ai-parrot-server/src/parrot/autonomous/transport/
   mkdir -p packages/ai-parrot-server/src/parrot/autonomous/transport/filesystem/
   ```
2. `git mv` all top-level autonomous files:
   ```bash
   git mv packages/ai-parrot/src/parrot/autonomous/orchestrator.py packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py
   git mv packages/ai-parrot/src/parrot/autonomous/redis_jobs.py packages/ai-parrot-server/src/parrot/autonomous/redis_jobs.py
   git mv packages/ai-parrot/src/parrot/autonomous/webhooks.py packages/ai-parrot-server/src/parrot/autonomous/webhooks.py
   git mv packages/ai-parrot/src/parrot/autonomous/scheduler.py packages/ai-parrot-server/src/parrot/autonomous/scheduler.py
   git mv packages/ai-parrot/src/parrot/autonomous/admin.py packages/ai-parrot-server/src/parrot/autonomous/admin.py
   git mv packages/ai-parrot/src/parrot/autonomous/cli.py packages/ai-parrot-server/src/parrot/autonomous/cli.py
   git mv packages/ai-parrot/src/parrot/autonomous/evb.py packages/ai-parrot-server/src/parrot/autonomous/evb.py
   git mv packages/ai-parrot/src/parrot/autonomous/example.py packages/ai-parrot-server/src/parrot/autonomous/example.py
   ```
3. `git mv` subdirectories:
   ```bash
   git mv packages/ai-parrot/src/parrot/autonomous/deploy/ packages/ai-parrot-server/src/parrot/autonomous/deploy/
   git mv packages/ai-parrot/src/parrot/autonomous/transport/ packages/ai-parrot-server/src/parrot/autonomous/transport/
   ```
4. Add `parrot-fs` console_script to satellite's `pyproject.toml`:
   ```toml
   [project.scripts]
   parrot-fs = "parrot.autonomous.transport.filesystem.cli:main"
   ```
5. Verify host `autonomous/__init__.py` retains only `extend_path` (from TASK-1367)

### Key Constraints
- Do NOT create `__init__.py` in satellite `autonomous/` — PEP 420 namespace package
- Do NOT modify host `autonomous/__init__.py` — already updated with `extend_path` in TASK-1367
- `deploy/` and `transport/` are internal packages — preserve their `__init__.py` files
- `transport/filesystem/` is an internal package — preserve its `__init__.py`
- `orchestrator.py` uses `TYPE_CHECKING` for most imports — these do not need updating since they are string-based

## Acceptance Criteria
- [ ] `from parrot.autonomous.orchestrator import AutonomousOrchestrator` resolves from satellite
- [ ] `parrot-fs` CLI works from satellite console_scripts
- [ ] `transport/` and `deploy/` subdirectories exist in satellite
- [ ] Host `autonomous/` retains only `__init__.py` with `extend_path`
- [ ] No `__init__.py` in satellite `autonomous/` (PEP 420)
- [ ] Existing test suite passes

## Test Specification
```python
def test_orchestrator_import():
    """AutonomousOrchestrator resolves from satellite."""
    from parrot.autonomous.orchestrator import AutonomousOrchestrator
    assert AutonomousOrchestrator is not None

def test_execution_target_import():
    """ExecutionTarget enum resolves from satellite."""
    from parrot.autonomous.orchestrator import ExecutionTarget
    assert ExecutionTarget is not None

def test_transport_filesystem_import():
    """Transport filesystem module resolves from satellite."""
    from parrot.autonomous.transport.filesystem import cli
    assert hasattr(cli, "main")

def test_deploy_directory_in_satellite():
    """deploy/ directory exists in satellite."""
    import pathlib
    deploy = pathlib.Path("packages/ai-parrot-server/src/parrot/autonomous/deploy")
    assert deploy.exists(), "deploy/ missing from satellite"

def test_transport_directory_in_satellite():
    """transport/ directory exists in satellite."""
    import pathlib
    transport = pathlib.Path("packages/ai-parrot-server/src/parrot/autonomous/transport")
    assert transport.exists(), "transport/ missing from satellite"
    filesystem = transport / "filesystem"
    assert filesystem.exists(), "transport/filesystem/ missing from satellite"

def test_host_autonomous_minimal():
    """Host autonomous/ retains only __init__.py."""
    import pathlib
    host = pathlib.Path("packages/ai-parrot/src/parrot/autonomous")
    py_files = list(host.glob("*.py"))
    assert len(py_files) == 1, f"Expected only __init__.py, found: {py_files}"
    assert py_files[0].name == "__init__.py"
```

## Agent Instructions
1. Read the full list of files in host `autonomous/` before making changes.
2. Follow the step-by-step procedure in Implementation Notes exactly.
3. After moving files, grep the satellite `autonomous/` directory for stale relative imports and fix them.
4. Run `python -c "from parrot.autonomous.orchestrator import AutonomousOrchestrator"` to verify namespace merging works.
5. Update satellite `pyproject.toml` with the `parrot-fs` console_script entry.
6. Commit with message: `sdd: move autonomous to satellite for ai-parrot-server`

## Completion Note
*(Agent fills this in when done)*
