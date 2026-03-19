# TASK-235: Docker Executor

**Feature**: Docker Toolkit (FEAT-033)
**Spec**: `sdd/specs/docker-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-233, TASK-234
**Assigned-to**: claude-opus-4-6

---

## Context

> Core execution engine for Docker CLI operations. Wraps `docker` and `docker compose` commands via async subprocess, parses JSON output, and detects daemon availability.
> Implements spec Section 3 — Module 3.

---

## Scope

- Create `parrot/tools/docker/executor.py` with `DockerExecutor(BaseExecutor)`.
- Methods:
  - `check_daemon()` — verify Docker daemon is running via `docker info`
  - `check_compose()` — detect compose v2 availability
  - `run_command(args)` — async subprocess execution with timeout
  - `parse_ps_output(raw)` — parse `docker ps --format json` to `ContainerInfo` list
  - `parse_images_output(raw)` — parse `docker images --format json` to `ImageInfo` list
  - `build_run_args(input: ContainerRunInput)` — construct `docker run` CLI args including resource limits
  - `build_exec_args(input: DockerExecInput)` — construct `docker exec` CLI args
  - `build_build_args(input: DockerBuildInput)` — construct `docker build` CLI args
- All methods async. Use `asyncio.create_subprocess_exec`.
- Parse errors into actionable `DockerOperationResult` with `error` field.

**NOT in scope**: Compose YAML generation (TASK-236), toolkit methods (TASK-237).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/docker/executor.py` | CREATE | `DockerExecutor` class |

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
import json
from typing import List, Optional
from navconfig.logging import logging
from parrot.tools.security.base_executor import BaseExecutor
from .config import DockerConfig
from .models import (
    ContainerInfo, ImageInfo, ContainerRunInput,
    DockerOperationResult, DockerBuildInput, DockerExecInput
)


class DockerExecutor(BaseExecutor):
    """Async executor for Docker CLI commands."""

    def __init__(self, config: DockerConfig = None):
        self.config = config or DockerConfig()
        self.logger = logging.getLogger(__name__)

    async def check_daemon(self) -> bool:
        """Check if Docker daemon is running."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.config.docker_cli, "info", "--format", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=10
            )
            return proc.returncode == 0
        except Exception:
            return False
```

### Key Constraints
- Always check daemon before operations; return clear error if not running.
- Use `--format '{{json .}}'` for `docker ps` and `docker images`.
- Handle both single-line JSON (one per line) and JSON array output.
- Resource limits: pass `--cpus` and `--memory` flags when set on config or input.
- Timeout from `DockerConfig.timeout`.

### References in Codebase
- `parrot/tools/security/base_executor.py` — `BaseExecutor` base class
- `parrot/tools/pulumi/executor.py` — `PulumiExecutor` as pattern
- `parrot/tools/security/trivy/executor.py` — Trivy executor as pattern

---

## Acceptance Criteria

- [ ] `DockerExecutor` class exists in `parrot/tools/docker/executor.py`
- [ ] `check_daemon()` returns bool, detects missing Docker daemon
- [ ] `run_command()` executes async subprocess with configurable timeout
- [ ] `parse_ps_output()` parses JSON lines into `ContainerInfo` list
- [ ] `parse_images_output()` parses JSON lines into `ImageInfo` list
- [ ] `build_run_args()` includes port, volume, env, restart, and resource limit flags
- [ ] `build_exec_args()` includes workdir, user, and env flags
- [ ] `build_build_args()` includes tag, build-args, and no-cache flags
- [ ] Errors produce `DockerOperationResult` with actionable messages
- [ ] No linting errors

---

## Test Specification

```python
# tests/tools/docker/test_executor.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot.tools.docker.executor import DockerExecutor
from parrot.tools.docker.config import DockerConfig
from parrot.tools.docker.models import ContainerRunInput, PortMapping, DockerBuildInput


class TestDockerExecutor:
    def test_build_run_args_basic(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(image="redis:alpine", name="test-redis", detach=True)
        args = executor.build_run_args(inp)
        assert "redis:alpine" in args
        assert "--name" in args
        assert "-d" in args

    def test_build_run_args_with_ports(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(
            image="nginx",
            ports=[PortMapping(host_port=8080, container_port=80)]
        )
        args = executor.build_run_args(inp)
        assert "-p" in args
        assert "8080:80/tcp" in args or "8080:80" in args

    def test_build_run_args_with_limits(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(image="python:3.12", cpu_limit="2", memory_limit="4g")
        args = executor.build_run_args(inp)
        assert "--cpus" in args
        assert "--memory" in args

    def test_build_build_args(self):
        executor = DockerExecutor()
        inp = DockerBuildInput(tag="myapp:v1", no_cache=True)
        args = executor.build_build_args(inp)
        assert "--no-cache" in args
        assert "-t" in args

    def test_parse_ps_output(self):
        executor = DockerExecutor()
        raw = '{"ID":"abc123","Names":"redis","Image":"redis:alpine","Status":"Up","Ports":"6379","CreatedAt":"now"}'
        result = executor.parse_ps_output(raw)
        assert len(result) == 1
        assert result[0].name == "redis"

    @pytest.mark.asyncio
    async def test_check_daemon_not_running(self):
        executor = DockerExecutor(DockerConfig(docker_cli="/nonexistent/docker"))
        result = await executor.check_daemon()
        assert result is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-233 and TASK-234 must be done
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-235-docker-executor.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-4-6
**Date**: 2026-03-09
**Notes**: Created `DockerExecutor(BaseExecutor)` with full implementation:
- `check_daemon()` / `check_compose()` for availability detection
- `run_command()` / `run_compose_command()` for async subprocess execution with timeout
- `parse_ps_output()` / `parse_images_output()` for JSON line parsing
- `build_run_args()` with ports, volumes, env, restart, CPU/memory limits, network
- `build_exec_args()` with workdir, user, env vars
- `build_build_args()` with tag, build-args, no-cache
- `make_error_result()` / `make_success_result()` helpers
All linting passes. All sync and async tests verified.

**Deviations from spec**: Added `run_compose_command()` for compose operations and `make_error_result()`/`make_success_result()` helpers to reduce boilerplate in toolkit.
