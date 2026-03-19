# TASK-236: Docker Compose Generator

**Feature**: Docker Toolkit (FEAT-033)
**Spec**: `sdd/specs/docker-toolkit.spec.md`
**Status**: in-progress
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-234
**Assigned-to**: claude-session

---

## Context

> Generates valid docker-compose YAML files from Pydantic `ComposeServiceDef` models. Writes to the configured `DOCKER_FILE_LOCATION` or a user-specified path.
> Implements spec Section 3 — Module 4.

---

## Scope

- Create `parrot/tools/docker/compose.py` with `ComposeGenerator` class.
- Methods:
  - `generate(project_name, services, output_path)` — build YAML dict from `ComposeServiceDef` models and write to file
  - `validate(compose_path)` — run `docker compose -f <path> config` to validate
  - `to_dict(project_name, services)` — return the compose dict without writing
- Use `pyyaml` for YAML serialization.
- Default output path uses `DOCKER_FILE_LOCATION` from `parrot/conf.py`.

**NOT in scope**: Executor (TASK-235), toolkit (TASK-237).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/docker/compose.py` | CREATE | `ComposeGenerator` class |

---

## Implementation Notes

### Pattern to Follow
```python
import os
from pathlib import Path
from typing import Dict
import yaml
from navconfig.logging import logging
from parrot.conf import DOCKER_FILE_LOCATION
from .models import ComposeServiceDef


class ComposeGenerator:
    """Generates docker-compose YAML from Pydantic models."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def to_dict(
        self,
        project_name: str,
        services: Dict[str, ComposeServiceDef]
    ) -> dict:
        """Convert service definitions to a compose dict."""
        compose = {
            "version": "3.8",
            "services": {}
        }
        for name, svc in services.items():
            svc_dict = {}
            svc_dict["image"] = svc.image
            if svc.ports:
                svc_dict["ports"] = svc.ports
            if svc.volumes:
                svc_dict["volumes"] = svc.volumes
            if svc.environment:
                svc_dict["environment"] = svc.environment
            if svc.depends_on:
                svc_dict["depends_on"] = svc.depends_on
            svc_dict["restart"] = svc.restart
            if svc.command:
                svc_dict["command"] = svc.command
            if svc.healthcheck:
                svc_dict["healthcheck"] = svc.healthcheck
            compose["services"][name] = svc_dict
        return compose

    async def generate(
        self,
        project_name: str,
        services: Dict[str, ComposeServiceDef],
        output_path: str = None
    ) -> str:
        """Generate and write docker-compose.yml."""
        if output_path is None:
            output_path = str(Path(DOCKER_FILE_LOCATION) / "docker-compose.yml")
        # Ensure directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        compose_dict = self.to_dict(project_name, services)
        with open(output_path, "w") as f:
            yaml.dump(compose_dict, f, default_flow_style=False, sort_keys=False)
        self.logger.info("Generated compose file: %s", output_path)
        return output_path
```

### Key Constraints
- Output valid docker-compose v3.8 YAML.
- Extract volumes from services into top-level `volumes:` section when using named volumes.
- Ensure directory creation before write.

### References in Codebase
- Spec Section 3 — Module 4
- `parrot/conf.py` — `DOCKER_FILE_LOCATION`

---

## Acceptance Criteria

- [ ] `ComposeGenerator` class exists in `parrot/tools/docker/compose.py`
- [ ] `to_dict()` returns valid compose dict structure
- [ ] `generate()` writes valid YAML to disk
- [ ] Default output path uses `DOCKER_FILE_LOCATION`
- [ ] Named volumes extracted to top-level `volumes:` section
- [ ] Generated YAML passes `docker compose config` validation
- [ ] No linting errors

---

## Test Specification

```python
# tests/tools/docker/test_compose.py
import pytest
import yaml
from pathlib import Path
from parrot.tools.docker.compose import ComposeGenerator
from parrot.tools.docker.models import ComposeServiceDef


class TestComposeGenerator:
    def test_to_dict_single_service(self):
        gen = ComposeGenerator()
        services = {
            "redis": ComposeServiceDef(image="redis:alpine", ports=["6379:6379"])
        }
        result = gen.to_dict("test", services)
        assert "services" in result
        assert "redis" in result["services"]
        assert result["services"]["redis"]["image"] == "redis:alpine"

    def test_to_dict_with_depends_on(self):
        gen = ComposeGenerator()
        services = {
            "db": ComposeServiceDef(image="postgres:16"),
            "app": ComposeServiceDef(image="myapp:latest", depends_on=["db"])
        }
        result = gen.to_dict("test", services)
        assert result["services"]["app"]["depends_on"] == ["db"]

    @pytest.mark.asyncio
    async def test_generate_writes_file(self, tmp_path):
        gen = ComposeGenerator()
        services = {
            "redis": ComposeServiceDef(image="redis:alpine")
        }
        output = str(tmp_path / "docker-compose.yml")
        path = await gen.generate("test", services, output_path=output)
        assert Path(path).exists()
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "services" in data

    def test_to_dict_with_healthcheck(self):
        gen = ComposeGenerator()
        services = {
            "redis": ComposeServiceDef(
                image="redis:alpine",
                healthcheck={"test": ["CMD", "redis-cli", "ping"], "interval": "10s"}
            )
        }
        result = gen.to_dict("test", services)
        assert "healthcheck" in result["services"]["redis"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-234 must be done
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-236-docker-compose-generator.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

Implemented `ComposeGenerator` in `parrot/tools/docker/compose.py` with:
- `to_dict(project_name, services)` — builds compose v3.8 dict from ComposeServiceDef models
- `generate(project_name, services, output_path)` — writes YAML to disk (defaults to DOCKER_FILE_LOCATION)
- `validate(compose_path)` — runs `docker compose config` for validation
- Named volumes automatically extracted to top-level `volumes:` section
- Host path mounts (starting with `/`, `./`, `~/`) correctly excluded from extraction
- Empty lists/dicts omitted from service output for clean YAML

14 tests pass covering: single/multi-service, depends_on, healthcheck, environment,
command, restart default, named volume extraction, host path exclusion, file write,
parent directory creation, and full multi-service compose from spec fixtures. No lint errors.
