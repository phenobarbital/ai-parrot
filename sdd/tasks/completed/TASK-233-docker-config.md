# TASK-233: Docker Configuration & Environment Variable

**Feature**: Docker Toolkit (FEAT-033)
**Spec**: `sdd/specs/docker-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-opus-4-6

---

## Context

> Foundation task for FEAT-033. Defines the `DockerConfig` extending `BaseExecutorConfig` and adds the `DOCKER_FILE_LOCATION` environment variable to `parrot/conf.py`.
> Implements spec Section 3 — Module 1.

---

## Scope

- Create `parrot/tools/docker/config.py` with `DockerConfig(BaseExecutorConfig)`.
- Fields: `docker_cli` (str, default "docker"), `compose_cli` (str, default "docker compose"), `default_network` (Optional[str]), `cpu_limit` (Optional[str]), `memory_limit` (Optional[str]).
- Add `DOCKER_FILE_LOCATION` to `parrot/conf.py` defaulting to `BASE_DIR / "docker"`.
- All fields must use `Field(...)` with descriptions.

**NOT in scope**: Data models (TASK-234), executor (TASK-235), toolkit (TASK-237).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/docker/__init__.py` | CREATE | Empty init, will be populated in TASK-238 |
| `parrot/tools/docker/config.py` | CREATE | `DockerConfig` class |
| `parrot/conf.py` | MODIFY | Add `DOCKER_FILE_LOCATION` env variable |

---

## Implementation Notes

### Pattern to Follow
```python
from pydantic import Field
from typing import Optional
from parrot.tools.security.base_executor import BaseExecutorConfig


class DockerConfig(BaseExecutorConfig):
    """Configuration for Docker executor."""

    docker_cli: str = Field(
        default="docker",
        description="Path to docker CLI binary"
    )
    compose_cli: str = Field(
        default="docker compose",
        description="Docker compose command (v2 plugin)"
    )
    default_network: Optional[str] = Field(
        default=None,
        description="Default Docker network to attach containers"
    )
    cpu_limit: Optional[str] = Field(
        default=None,
        description="CPU limit (e.g., '0.5', '2')"
    )
    memory_limit: Optional[str] = Field(
        default=None,
        description="Memory limit (e.g., '512m', '2g')"
    )
```

### Key Constraints
- Reuse `BaseExecutorConfig` from `parrot/tools/security/base_executor.py`.
- `DOCKER_FILE_LOCATION` must use `os.environ.get()` pattern consistent with other conf variables.

### References in Codebase
- `parrot/tools/security/base_executor.py` — `BaseExecutorConfig`
- `parrot/tools/pulumi/config.py` — `PulumiConfig` as pattern
- `parrot/conf.py` — existing environment variables

---

## Acceptance Criteria

- [ ] `DockerConfig` class exists in `parrot/tools/docker/config.py`
- [ ] `DockerConfig` inherits from `BaseExecutorConfig`
- [ ] All fields defined with proper types, defaults, and descriptions
- [ ] `DOCKER_FILE_LOCATION` variable added to `parrot/conf.py`
- [ ] No linting errors: `ruff check parrot/tools/docker/config.py`

---

## Test Specification

```python
# tests/tools/docker/test_config.py
import pytest
from parrot.tools.docker.config import DockerConfig


class TestDockerConfig:
    def test_defaults(self):
        config = DockerConfig()
        assert config.docker_cli == "docker"
        assert config.compose_cli == "docker compose"
        assert config.default_network is None

    def test_custom_cli(self):
        config = DockerConfig(docker_cli="/usr/local/bin/docker")
        assert config.docker_cli == "/usr/local/bin/docker"

    def test_resource_limits(self):
        config = DockerConfig(cpu_limit="2", memory_limit="4g")
        assert config.cpu_limit == "2"
        assert config.memory_limit == "4g"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-233-docker-config.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-4-6
**Date**: 2026-03-09
**Notes**: Created `DockerConfig(BaseExecutorConfig)` with 5 Docker-specific fields (docker_cli, compose_cli, default_network, cpu_limit, memory_limit). Added `DOCKER_FILE_LOCATION` to `parrot/conf.py` defaulting to `BASE_DIR / "docker"`. All fields use `Field(...)` with descriptions. Linting passes.

**Deviations from spec**: none
