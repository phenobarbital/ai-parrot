# TASK-054: Pulumi Configuration

**Feature**: Pulumi Toolkit for Container Deployment
**Spec**: `sdd/specs/pulumi-toolkit-deployment.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 1 from the spec: Pulumi Configuration.

The configuration module defines `PulumiConfig` extending `BaseExecutorConfig` with Pulumi-specific settings. This is the foundation for the executor and toolkit.

---

## Scope

- Create `parrot/tools/pulumi/` directory structure
- Implement `PulumiConfig` class extending `BaseExecutorConfig`
- Define Pydantic input models: `PulumiPlanInput`, `PulumiApplyInput`, `PulumiDestroyInput`, `PulumiStatusInput`
- Define output models: `PulumiResource`, `PulumiOperationResult`
- Write unit tests for all models

**NOT in scope**:
- Executor implementation (TASK-055)
- Toolkit implementation (TASK-056)
- CLI installation command (TASK-057)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/pulumi/__init__.py` | CREATE | Package init (empty for now) |
| `parrot/tools/pulumi/config.py` | CREATE | Configuration and data models |
| `tests/tools/pulumi/__init__.py` | CREATE | Test package init |
| `tests/tools/pulumi/test_config.py` | CREATE | Unit tests for config models |

---

## Implementation Notes

### Pattern to Follow
```python
# Reference: parrot/tools/security/base_executor.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from parrot.tools.security.base_executor import BaseExecutorConfig


class PulumiConfig(BaseExecutorConfig):
    """Configuration for Pulumi executor."""

    docker_image: str = Field(
        default="pulumi/pulumi:latest",
        description="Docker image for Pulumi execution"
    )
    default_stack: str = Field(
        default="dev",
        description="Default stack name if not specified"
    )
    # ... additional fields from spec
```

### Key Constraints
- Extend `BaseExecutorConfig` for Docker/CLI mode support
- Use Pydantic v2 syntax for all models
- Include comprehensive docstrings for LLM tool descriptions
- All fields must have `description` for schema generation

### References in Codebase
- `parrot/tools/security/base_executor.py` — BaseExecutorConfig to extend
- `parrot/tools/security/checkov/config.py` — Pattern for tool-specific config
- `parrot/tools/aws/ecs.py` — Input model patterns

---

## Acceptance Criteria

- [ ] `PulumiConfig` extends `BaseExecutorConfig` correctly
- [ ] All input models defined with proper Field descriptions
- [ ] All output models defined with proper Field descriptions
- [ ] Unit tests pass: `pytest tests/tools/pulumi/test_config.py -v`
- [ ] No linting errors: `ruff check parrot/tools/pulumi/`
- [ ] Import works: `from parrot.tools.pulumi.config import PulumiConfig`

---

## Test Specification

```python
# tests/tools/pulumi/test_config.py
import pytest
from parrot.tools.pulumi.config import (
    PulumiConfig,
    PulumiPlanInput,
    PulumiApplyInput,
    PulumiDestroyInput,
    PulumiStatusInput,
    PulumiResource,
    PulumiOperationResult,
)


class TestPulumiConfig:
    def test_default_values(self):
        """Config has sensible defaults."""
        config = PulumiConfig()
        assert config.docker_image == "pulumi/pulumi:latest"
        assert config.default_stack == "dev"
        assert config.auto_create_stack is True
        assert config.use_docker is True

    def test_custom_values(self):
        """Config accepts custom values."""
        config = PulumiConfig(
            docker_image="pulumi/pulumi:3.100.0",
            default_stack="staging",
            use_docker=False,
        )
        assert config.docker_image == "pulumi/pulumi:3.100.0"
        assert config.default_stack == "staging"


class TestPulumiInputModels:
    def test_plan_input_required_fields(self):
        """PulumiPlanInput requires project_path."""
        with pytest.raises(ValueError):
            PulumiPlanInput()

    def test_plan_input_valid(self):
        """PulumiPlanInput accepts valid input."""
        inp = PulumiPlanInput(project_path="/path/to/project")
        assert inp.project_path == "/path/to/project"
        assert inp.stack_name is None

    def test_apply_input_auto_approve_default(self):
        """PulumiApplyInput defaults auto_approve to True."""
        inp = PulumiApplyInput(project_path="/path")
        assert inp.auto_approve is True


class TestPulumiOutputModels:
    def test_resource_model(self):
        """PulumiResource captures resource state."""
        resource = PulumiResource(
            urn="urn:pulumi:dev::test::docker:Container::redis",
            type="docker:index/container:Container",
            name="redis",
            status="create",
        )
        assert resource.urn.startswith("urn:pulumi")

    def test_operation_result_success(self):
        """PulumiOperationResult captures successful operation."""
        result = PulumiOperationResult(
            success=True,
            operation="up",
            resources=[],
            outputs={"url": "http://localhost"},
            summary={"create": 1},
        )
        assert result.success is True
        assert result.operation == "up"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-054-pulumi-config.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
