# TASK-234: Docker Data Models

**Feature**: Docker Toolkit (FEAT-033)
**Spec**: `sdd/specs/docker-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> Defines all Pydantic models for Docker operations: container info, image info, port/volume mappings, compose service definitions, and operation results.
> Implements spec Section 3 — Module 2.

---

## Scope

- Create `parrot/tools/docker/models.py` with all data models from the spec.
- Models: `ContainerInfo`, `ImageInfo`, `PortMapping`, `VolumeMapping`, `ContainerRunInput`, `ComposeServiceDef`, `ComposeGenerateInput`, `DockerOperationResult`, `PruneResult`, `DockerBuildInput`, `DockerExecInput`.
- All fields must use `Field(...)` with descriptions and constraints.

**NOT in scope**: Config (TASK-233), executor logic (TASK-235), toolkit methods (TASK-237).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/docker/models.py` | CREATE | All Pydantic data models |

---

## Implementation Notes

### Pattern to Follow
Follow the models defined in spec Section 2 "Data Models", plus add:

```python
class DockerBuildInput(BaseModel):
    """Input for docker_build operation."""

    dockerfile_path: str = Field(
        default=".", description="Path to directory containing Dockerfile"
    )
    tag: str = Field(..., description="Image tag (e.g., 'myapp:latest')")
    build_args: Dict[str, str] = Field(
        default_factory=dict, description="Build arguments"
    )
    no_cache: bool = Field(default=False, description="Build without cache")


class DockerExecInput(BaseModel):
    """Input for docker_exec operation."""

    container: str = Field(..., description="Container name or ID")
    command: str = Field(..., description="Command to execute")
    workdir: Optional[str] = Field(None, description="Working directory inside container")
    env_vars: Dict[str, str] = Field(
        default_factory=dict, description="Additional environment variables"
    )
    user: Optional[str] = Field(None, description="User to run command as")
```

### Key Constraints
- Standalone Pydantic models — no external dependencies beyond pydantic.
- Resource limit fields on `ContainerRunInput`: `cpu_limit` (Optional[str]), `memory_limit` (Optional[str]).

### References in Codebase
- `parrot/tools/pulumi/config.py` — Pulumi models as pattern
- Spec Section 2 "Data Models"

---

## Acceptance Criteria

- [ ] All 11 models defined in `parrot/tools/docker/models.py`
- [ ] `ContainerRunInput` includes `cpu_limit` and `memory_limit` fields
- [ ] `DockerBuildInput` and `DockerExecInput` models added for new requirements
- [ ] All fields have proper types, defaults, and descriptions
- [ ] `model_json_schema()` works for all models
- [ ] No linting errors

---

## Test Specification

```python
# tests/tools/docker/test_models.py
import pytest
from parrot.tools.docker.models import (
    ContainerInfo, ImageInfo, PortMapping, VolumeMapping,
    ContainerRunInput, ComposeServiceDef, DockerOperationResult,
    PruneResult, DockerBuildInput, DockerExecInput
)


class TestDockerModels:
    def test_container_info(self):
        info = ContainerInfo(
            container_id="abc123", name="redis", image="redis:alpine", status="Up"
        )
        assert info.container_id == "abc123"

    def test_port_mapping_defaults(self):
        pm = PortMapping(host_port=8080, container_port=80)
        assert pm.protocol == "tcp"

    def test_compose_service_def(self):
        svc = ComposeServiceDef(image="nginx:latest", ports=["80:80"])
        assert svc.restart == "unless-stopped"

    def test_container_run_with_limits(self):
        run = ContainerRunInput(image="python:3.12", cpu_limit="2", memory_limit="4g")
        assert run.cpu_limit == "2"

    def test_docker_build_input(self):
        build = DockerBuildInput(tag="myapp:v1")
        assert build.dockerfile_path == "."
        assert build.no_cache is False

    def test_docker_exec_input(self):
        ex = DockerExecInput(container="redis", command="redis-cli ping")
        assert ex.user is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-234-docker-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

All 11 Pydantic models implemented in `parrot/tools/docker/models.py`:
- `ContainerInfo`, `ImageInfo`, `PortMapping`, `VolumeMapping`
- `ContainerRunInput` (with `cpu_limit` and `memory_limit` fields)
- `ComposeServiceDef`, `ComposeGenerateInput`
- `DockerOperationResult`, `PruneResult`
- `DockerBuildInput`, `DockerExecInput`

All fields have proper types, defaults, and descriptions via `Field(...)`.
24 tests pass (13 unit + 11 parametrized schema tests). No lint errors.
