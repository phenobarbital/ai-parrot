# TASK-058: Pulumi Integration Tests & Package Export

**Feature**: Pulumi Toolkit for Container Deployment
**Spec**: `sdd/specs/pulumi-toolkit-deployment.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-054, TASK-055, TASK-056
**Assigned-to**: unassigned

---

## Context

> This task implements Module 5 from the spec: Package Init & Integration Tests.

Finalize the package exports and write integration tests that verify the full Pulumi workflow with a real Docker project (using mocked Pulumi CLI if necessary).

---

## Scope

- Update `parrot/tools/pulumi/__init__.py` with proper exports
- Register `PulumiToolkit` with toolkit registry
- Write integration tests for Docker project deployment
- Create test fixtures (sample Pulumi Docker project)
- Verify all acceptance criteria from spec

**NOT in scope**:
- Testing with real cloud providers
- Testing with real Pulumi Cloud backend
- Performance benchmarks

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/pulumi/__init__.py` | MODIFY | Add exports and registration |
| `tests/tools/pulumi/test_integration.py` | CREATE | Integration tests |
| `tests/fixtures/pulumi_docker_project/` | CREATE | Test fixture directory |
| `tests/fixtures/pulumi_docker_project/Pulumi.yaml` | CREATE | Project manifest |
| `tests/fixtures/pulumi_docker_project/Main.yaml` | CREATE | Resources definition |

---

## Implementation Notes

### Package Exports
```python
# parrot/tools/pulumi/__init__.py
"""Pulumi Toolkit for infrastructure deployment.

Provides agent tools for Pulumi operations:
- pulumi_plan: Preview changes
- pulumi_apply: Apply changes
- pulumi_destroy: Tear down resources
- pulumi_status: Check stack state

Example:
    from parrot.tools.pulumi import PulumiToolkit

    toolkit = PulumiToolkit()
    agent = Agent(tools=toolkit.get_tools())
"""

from .config import (
    PulumiConfig,
    PulumiPlanInput,
    PulumiApplyInput,
    PulumiDestroyInput,
    PulumiStatusInput,
    PulumiResource,
    PulumiOperationResult,
)
from .executor import PulumiExecutor
from .toolkit import PulumiToolkit

__all__ = [
    "PulumiConfig",
    "PulumiPlanInput",
    "PulumiApplyInput",
    "PulumiDestroyInput",
    "PulumiStatusInput",
    "PulumiResource",
    "PulumiOperationResult",
    "PulumiExecutor",
    "PulumiToolkit",
]

# Register with toolkit registry
try:
    from ..registry import ToolkitRegistry
    ToolkitRegistry.register("pulumi", PulumiToolkit)
except ImportError:
    pass
```

### Test Fixture (Pulumi Docker Project)
```yaml
# tests/fixtures/pulumi_docker_project/Pulumi.yaml
name: test-docker-project
runtime: yaml
description: Test project for Pulumi toolkit

# tests/fixtures/pulumi_docker_project/Pulumi.dev.yaml
config: {}

# tests/fixtures/pulumi_docker_project/Main.yaml
resources:
  redis:
    type: docker:Container
    properties:
      name: test-redis
      image: redis:alpine
      ports:
        - internal: 6379
          external: 16379
outputs:
  containerId: ${redis.id}
  containerName: ${redis.name}
```

### Key Constraints
- Integration tests should work without real Pulumi CLI (mock subprocess)
- Test fixtures must be valid Pulumi YAML syntax
- Verify full lifecycle: plan → apply → status → destroy

### References in Codebase
- `tests/integration/` — integration test patterns
- `tests/fixtures/` — test fixture patterns
- `parrot/tools/security/__init__.py` — package export pattern

---

## Acceptance Criteria

- [ ] `from parrot.tools.pulumi import PulumiToolkit` works
- [ ] `from parrot.tools.pulumi import PulumiConfig` works
- [ ] Toolkit registered in registry (if registry exists)
- [ ] Test fixture is valid Pulumi YAML
- [ ] Integration test covers plan operation
- [ ] Integration test covers apply operation
- [ ] Integration test covers destroy operation
- [ ] Integration test covers status operation
- [ ] All tests pass: `pytest tests/tools/pulumi/ -v`
- [ ] No linting errors: `ruff check parrot/tools/pulumi/`

---

## Test Specification

```python
# tests/tools/pulumi/test_integration.py
import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
from parrot.tools.pulumi import PulumiToolkit, PulumiConfig


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "pulumi_docker_project"


@pytest.fixture
def toolkit():
    return PulumiToolkit(PulumiConfig(use_docker=False))


class TestPulumiImports:
    def test_import_toolkit(self):
        """PulumiToolkit is importable."""
        from parrot.tools.pulumi import PulumiToolkit
        assert PulumiToolkit is not None

    def test_import_config(self):
        """PulumiConfig is importable."""
        from parrot.tools.pulumi import PulumiConfig
        assert PulumiConfig is not None

    def test_import_models(self):
        """All models are importable."""
        from parrot.tools.pulumi import (
            PulumiPlanInput,
            PulumiApplyInput,
            PulumiDestroyInput,
            PulumiStatusInput,
            PulumiResource,
            PulumiOperationResult,
        )
        assert all([
            PulumiPlanInput,
            PulumiApplyInput,
            PulumiDestroyInput,
            PulumiStatusInput,
            PulumiResource,
            PulumiOperationResult,
        ])


class TestPulumiFixture:
    def test_fixture_exists(self, fixtures_dir):
        """Test fixture directory exists."""
        assert fixtures_dir.exists()

    def test_pulumi_yaml_valid(self, fixtures_dir):
        """Pulumi.yaml is valid YAML."""
        import yaml
        pulumi_yaml = fixtures_dir / "Pulumi.yaml"
        assert pulumi_yaml.exists()
        data = yaml.safe_load(pulumi_yaml.read_text())
        assert data["name"] == "test-docker-project"
        assert data["runtime"] == "yaml"


class TestPulumiFullLifecycle:
    @pytest.mark.asyncio
    async def test_plan_apply_destroy_lifecycle(self, toolkit, fixtures_dir):
        """Full lifecycle: plan → apply → destroy."""
        preview_output = json.dumps({
            "steps": [{"op": "create", "urn": "urn:pulumi:dev::test::docker:Container::redis"}]
        })
        up_output = json.dumps({
            "steps": [{"op": "create", "urn": "urn:pulumi:dev::test::docker:Container::redis"}],
            "outputs": {"containerId": "abc123"}
        })
        destroy_output = json.dumps({
            "steps": [{"op": "delete", "urn": "urn:pulumi:dev::test::docker:Container::redis"}]
        })

        with patch.object(toolkit.executor, 'preview', new_callable=AsyncMock) as mock_preview:
            with patch.object(toolkit.executor, 'up', new_callable=AsyncMock) as mock_up:
                with patch.object(toolkit.executor, 'destroy', new_callable=AsyncMock) as mock_destroy:
                    mock_preview.return_value = (preview_output, "", 0)
                    mock_up.return_value = (up_output, "", 0)
                    mock_destroy.return_value = (destroy_output, "", 0)

                    # Plan
                    plan_result = await toolkit.pulumi_plan(str(fixtures_dir))
                    assert plan_result.success is True
                    assert plan_result.operation == "preview"

                    # Apply
                    apply_result = await toolkit.pulumi_apply(str(fixtures_dir))
                    assert apply_result.success is True
                    assert apply_result.operation == "up"

                    # Destroy
                    destroy_result = await toolkit.pulumi_destroy(str(fixtures_dir))
                    assert destroy_result.success is True
                    assert destroy_result.operation == "destroy"


class TestPulumiToolRegistration:
    def test_tools_have_descriptions(self, toolkit):
        """All tools have descriptions for LLM."""
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} missing description"
            assert len(tool.description) > 20, f"Tool {tool.name} description too short"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-058-pulumi-integration-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
