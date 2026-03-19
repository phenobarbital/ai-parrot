# TASK-237: Docker Toolkit (AbstractToolkit)

**Feature**: Docker Toolkit (FEAT-033)
**Spec**: `sdd/specs/docker-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: XL (8-12h)
**Depends-on**: TASK-233, TASK-234, TASK-235, TASK-236
**Assigned-to**: claude-session

---

## Context

> The main toolkit class that exposes all Docker operations as agent tools. This is the primary user-facing component.
> Implements spec Section 3 — Module 5.

---

## Scope

- Create `parrot/tools/docker/toolkit.py` with `DockerToolkit(AbstractToolkit)`.
- Expose 14 tools with `docker_` prefix:
  - **Inspect**: `docker_ps`, `docker_images`, `docker_inspect`, `docker_logs`
  - **Lifecycle**: `docker_run`, `docker_stop`, `docker_rm`
  - **Build**: `docker_build`
  - **Exec**: `docker_exec`
  - **Compose**: `docker_compose_generate`, `docker_compose_up`, `docker_compose_down`
  - **Ops**: `docker_prune`, `docker_test`
- Each method delegates to `DockerExecutor` or `ComposeGenerator`.
- All methods async, return `DockerOperationResult` or `PruneResult`.
- Check daemon availability before each operation.

**NOT in scope**: Tests (TASK-239), package init (TASK-238).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/docker/toolkit.py` | CREATE | `DockerToolkit` class with all tool methods |

---

## Implementation Notes

### Pattern to Follow
```python
from typing import Dict, List, Optional, Any
from navconfig.logging import logging
from parrot.tools.toolkit import AbstractToolkit
from .config import DockerConfig
from .executor import DockerExecutor
from .compose import ComposeGenerator
from .models import (
    PortMapping, VolumeMapping, ComposeServiceDef,
    DockerOperationResult, PruneResult
)


class DockerToolkit(AbstractToolkit):
    """Toolkit for managing Docker containers and compose stacks."""

    name: str = "docker"
    description: str = "Docker container and compose management tools"

    def __init__(self, config: DockerConfig = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or DockerConfig()
        self.executor = DockerExecutor(self.config)
        self.compose_gen = ComposeGenerator()
        self.logger = logging.getLogger(__name__)

    async def docker_ps(self, all: bool = False, filters: Optional[Dict[str, str]] = None) -> DockerOperationResult:
        """List Docker containers."""
        ...

    async def docker_run(self, image: str, name: Optional[str] = None, ...) -> DockerOperationResult:
        """Launch a new Docker container."""
        ...

    async def docker_build(self, tag: str, dockerfile_path: str = ".", ...) -> DockerOperationResult:
        """Build a Docker image from a Dockerfile."""
        ...

    async def docker_exec(self, container: str, command: str, ...) -> DockerOperationResult:
        """Execute a command inside a running container."""
        ...
    # ... all other methods per spec
```

### Key Constraints
- Every method must check `await self.executor.check_daemon()` first.
- Resource limits from `ContainerRunInput` override defaults from `DockerConfig`.
- `docker_prune` with `volumes=True` must log a warning before executing.
- `docker_build` wraps `docker build -t <tag> <path>` with optional `--build-arg` and `--no-cache`.
- `docker_exec` wraps `docker exec [-w workdir] [-u user] [-e K=V] <container> <command>`.

### References in Codebase
- `parrot/tools/toolkit.py` — `AbstractToolkit` base class
- `parrot/tools/pulumi/toolkit.py` — `PulumiToolkit` as pattern
- Spec Section 2 "New Public Interfaces"

---

## Acceptance Criteria

- [ ] `DockerToolkit` inherits from `AbstractToolkit`
- [ ] 14 tool methods exposed: ps, images, run, stop, rm, logs, inspect, prune, build, exec, compose_generate, compose_up, compose_down, test
- [ ] `get_tools()` returns all 14 tools
- [ ] Each method checks Docker daemon availability
- [ ] `docker_run` supports ports, volumes, env, restart, CPU/memory limits
- [ ] `docker_build` supports tag, build-args, no-cache
- [ ] `docker_exec` supports command, workdir, user, env
- [ ] `docker_prune` logs warning when volumes=True
- [ ] All methods return `DockerOperationResult` or `PruneResult`
- [ ] Errors produce actionable messages
- [ ] No linting errors

---

## Test Specification

```python
# tests/tools/docker/test_toolkit.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.tools.docker.toolkit import DockerToolkit
from parrot.tools.docker.config import DockerConfig


class TestDockerToolkit:
    def test_get_tools_count(self):
        toolkit = DockerToolkit()
        tools = toolkit.get_tools()
        assert len(tools) == 14

    def test_tool_names(self):
        toolkit = DockerToolkit()
        tools = toolkit.get_tools()
        names = [t.name for t in tools]
        assert "docker_ps" in names
        assert "docker_run" in names
        assert "docker_build" in names
        assert "docker_exec" in names
        assert "docker_compose_generate" in names

    @pytest.mark.asyncio
    async def test_ps_checks_daemon(self):
        toolkit = DockerToolkit()
        with patch.object(toolkit.executor, 'check_daemon', new_callable=AsyncMock, return_value=False):
            result = await toolkit.docker_ps()
            assert result.success is False
            assert "daemon" in result.error.lower()

    @pytest.mark.asyncio
    async def test_prune_warns_on_volumes(self):
        toolkit = DockerToolkit()
        with patch.object(toolkit.executor, 'check_daemon', new_callable=AsyncMock, return_value=True):
            with patch.object(toolkit.executor, 'run_command', new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (0, '{"SpaceReclaimed": 0}', '')
                # Should log warning but proceed
                result = await toolkit.docker_prune(volumes=True)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-233, TASK-234, TASK-235, TASK-236 must be done
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-237-docker-toolkit.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-09

Implemented `DockerToolkit(AbstractToolkit)` in `parrot/tools/docker/toolkit.py` with 14 tool methods:

**Inspect**: `docker_ps`, `docker_images`, `docker_inspect`, `docker_logs`
**Lifecycle**: `docker_run`, `docker_stop`, `docker_rm`
**Build**: `docker_build`
**Exec**: `docker_exec`
**Compose**: `docker_compose_generate`, `docker_compose_up`, `docker_compose_down`
**Ops**: `docker_prune`, `docker_test`

Key features:
- Every method checks daemon availability before executing
- `docker_run` supports ports, volumes, env vars, restart policy, CPU/memory limits
- `docker_build` supports tag, build-args, no-cache
- `docker_exec` supports workdir, user, env vars
- `docker_prune` logs warning when volumes=True
- `docker_test` checks container state + optional TCP port/HTTP endpoint checks
- Port conflict and missing image errors produce actionable messages
- All methods return `DockerOperationResult` or `PruneResult`

29 tests pass. 67 total tests across all docker modules pass. No lint errors.
