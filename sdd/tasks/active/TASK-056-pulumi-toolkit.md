# TASK-056: Pulumi Toolkit

**Feature**: Pulumi Toolkit for Container Deployment
**Spec**: `sdd/specs/pulumi-toolkit-deployment.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-054, TASK-055
**Assigned-to**: unassigned

---

## Context

> This task implements Module 3 from the spec: Pulumi Toolkit.

The toolkit is the main user-facing class that exposes `pulumi_plan`, `pulumi_apply`, `pulumi_destroy`, and `pulumi_status` as agent tools. It inherits from `AbstractToolkit` and uses `PulumiExecutor` internally.

---

## Scope

- Implement `PulumiToolkit` class extending `AbstractToolkit`
- Implement `pulumi_plan()` async method (exposed as tool)
- Implement `pulumi_apply()` async method (exposed as tool)
- Implement `pulumi_destroy()` async method (exposed as tool)
- Implement `pulumi_status()` async method (exposed as tool)
- Add project validation (check Pulumi.yaml exists)
- Convert executor results to `PulumiOperationResult`
- Write unit tests with mocked executor

**NOT in scope**:
- CLI installation command (TASK-057)
- Integration tests with real Pulumi (TASK-058)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/pulumi/toolkit.py` | CREATE | PulumiToolkit implementation |
| `tests/tools/pulumi/test_toolkit.py` | CREATE | Unit tests for toolkit |

---

## Implementation Notes

### Pattern to Follow
```python
# Reference: parrot/tools/aws/ecs.py
from typing import Optional, Dict, Any
from ..toolkit import AbstractToolkit
from ..decorators import tool_schema
from .config import (
    PulumiConfig,
    PulumiPlanInput,
    PulumiApplyInput,
    PulumiDestroyInput,
    PulumiStatusInput,
    PulumiOperationResult,
)
from .executor import PulumiExecutor


class PulumiToolkit(AbstractToolkit):
    """Toolkit for infrastructure deployment using Pulumi.

    Each public async method is exposed as a separate tool with the `pulumi_` prefix.

    Available Operations:
    - pulumi_plan: Preview infrastructure changes without applying
    - pulumi_apply: Apply infrastructure changes
    - pulumi_destroy: Tear down infrastructure
    - pulumi_status: Check current stack state

    Example:
        toolkit = PulumiToolkit()
        tools = toolkit.get_tools()
        agent = Agent(tools=tools)
    """

    def __init__(self, config: Optional[PulumiConfig] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or PulumiConfig()
        self.executor = PulumiExecutor(self.config)

    @tool_schema(PulumiPlanInput)
    async def pulumi_plan(
        self,
        project_path: str,
        stack_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> PulumiOperationResult:
        """Preview infrastructure changes without applying.

        Args:
            project_path: Path to Pulumi project directory
            stack_name: Stack name (defaults to 'dev')
            config: Configuration values to set

        Returns:
            Preview result with resources to be created/updated/deleted
        """
        ...
```

### Key Constraints
- Validate `project_path` exists and contains `Pulumi.yaml`
- Return `PulumiOperationResult` with `success=False` on errors (not exceptions)
- Use `self.logger` for operation logging
- Handle JSON parsing errors gracefully

### References in Codebase
- `parrot/tools/toolkit.py` — AbstractToolkit base class
- `parrot/tools/aws/ecs.py` — Async toolkit method patterns
- `parrot/tools/decorators.py` — `@tool_schema` decorator

---

## Acceptance Criteria

- [ ] `PulumiToolkit` extends `AbstractToolkit`
- [ ] `get_tools()` returns 4 tools (plan, apply, destroy, status)
- [ ] `pulumi_plan()` validates project path and returns preview
- [ ] `pulumi_apply()` applies changes with auto-approve
- [ ] `pulumi_destroy()` tears down resources safely
- [ ] `pulumi_status()` returns current stack state
- [ ] All methods return `PulumiOperationResult`
- [ ] Errors return `success=False` with error message
- [ ] Unit tests pass: `pytest tests/tools/pulumi/test_toolkit.py -v`
- [ ] No linting errors: `ruff check parrot/tools/pulumi/toolkit.py`

---

## Test Specification

```python
# tests/tools/pulumi/test_toolkit.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from parrot.tools.pulumi.toolkit import PulumiToolkit
from parrot.tools.pulumi.config import PulumiConfig


@pytest.fixture
def toolkit():
    return PulumiToolkit(PulumiConfig(use_docker=False))


@pytest.fixture
def mock_project(tmp_path):
    """Create a minimal Pulumi project."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    (project_dir / "Pulumi.yaml").write_text("name: test\nruntime: yaml\n")
    return project_dir


class TestPulumiToolkitInit:
    def test_toolkit_initializes(self, toolkit):
        """Toolkit initializes with default config."""
        assert toolkit.config is not None
        assert toolkit.executor is not None

    def test_get_tools_returns_four(self, toolkit):
        """get_tools() returns 4 tools."""
        tools = toolkit.get_tools()
        tool_names = [t.name for t in tools]
        assert "pulumi_plan" in tool_names
        assert "pulumi_apply" in tool_names
        assert "pulumi_destroy" in tool_names
        assert "pulumi_status" in tool_names


class TestPulumiToolkitOperations:
    @pytest.mark.asyncio
    async def test_plan_validates_project_path(self, toolkit, tmp_path):
        """Plan fails gracefully for missing project."""
        result = await toolkit.pulumi_plan(str(tmp_path / "nonexistent"))
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_plan_checks_pulumi_yaml(self, toolkit, tmp_path):
        """Plan fails if Pulumi.yaml is missing."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = await toolkit.pulumi_plan(str(empty_dir))
        assert result.success is False
        assert "Pulumi.yaml" in result.error

    @pytest.mark.asyncio
    async def test_plan_success(self, toolkit, mock_project):
        """Plan succeeds with valid project."""
        mock_output = '{"steps": []}'
        with patch.object(toolkit.executor, 'preview', new_callable=AsyncMock) as mock:
            mock.return_value = (mock_output, "", 0)
            result = await toolkit.pulumi_plan(str(mock_project))
            assert result.success is True
            assert result.operation == "preview"

    @pytest.mark.asyncio
    async def test_apply_calls_executor(self, toolkit, mock_project):
        """Apply calls executor.up()."""
        mock_output = '{"steps": [{"op": "create"}]}'
        with patch.object(toolkit.executor, 'up', new_callable=AsyncMock) as mock:
            mock.return_value = (mock_output, "", 0)
            result = await toolkit.pulumi_apply(str(mock_project))
            mock.assert_called_once()
            assert result.operation == "up"

    @pytest.mark.asyncio
    async def test_destroy_calls_executor(self, toolkit, mock_project):
        """Destroy calls executor.destroy()."""
        mock_output = '{"steps": []}'
        with patch.object(toolkit.executor, 'destroy', new_callable=AsyncMock) as mock:
            mock.return_value = (mock_output, "", 0)
            result = await toolkit.pulumi_destroy(str(mock_project))
            mock.assert_called_once()
            assert result.operation == "destroy"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-056-pulumi-toolkit.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
