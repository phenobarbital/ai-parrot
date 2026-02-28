# TASK-055: Pulumi Executor

**Feature**: Pulumi Toolkit for Container Deployment
**Spec**: `sdd/specs/pulumi-toolkit-deployment.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-054
**Assigned-to**: unassigned

---

## Context

> This task implements Module 2 from the spec: Pulumi Executor.

The executor handles CLI argument building, subprocess execution, and JSON output parsing. It extends `BaseExecutor` following the pattern established by Checkov, Prowler, and Trivy.

---

## Scope

- Implement `PulumiExecutor` class extending `BaseExecutor`
- Implement `_build_cli_args()` for preview/up/destroy/stack commands
- Implement JSON output parsing for Pulumi CLI output
- Add helper methods: `preview()`, `up()`, `destroy()`, `stack_output()`
- Handle stack initialization (select or create)
- Write unit tests with mocked subprocess

**NOT in scope**:
- Toolkit implementation (TASK-056)
- CLI installation (TASK-057)
- Integration tests with real Pulumi (TASK-058)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/pulumi/executor.py` | CREATE | PulumiExecutor implementation |
| `tests/tools/pulumi/test_executor.py` | CREATE | Unit tests for executor |

---

## Implementation Notes

### Pattern to Follow
```python
# Reference: parrot/tools/security/checkov/executor.py
from typing import Optional, Tuple
from parrot.tools.security.base_executor import BaseExecutor
from .config import PulumiConfig


class PulumiExecutor(BaseExecutor):
    """Executes Pulumi CLI commands via subprocess.

    Supports Docker execution mode or direct CLI invocation.
    Parses JSON output from Pulumi commands into structured models.
    """

    def __init__(self, config: Optional[PulumiConfig] = None):
        super().__init__(config or PulumiConfig())
        self.config: PulumiConfig = self.config

    def _default_cli_name(self) -> str:
        return "pulumi"

    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build Pulumi CLI arguments."""
        args = []
        command = kwargs.get("command", "preview")
        stack = kwargs.get("stack", self.config.default_stack)

        if command == "preview":
            args.extend(["preview", "--json", "--stack", stack])
        elif command == "up":
            args.extend(["up", "--yes", "--json", "--stack", stack])
        # ... etc

        return args

    async def preview(self, project_path: str, stack: Optional[str] = None) -> Tuple[str, str, int]:
        """Run pulumi preview."""
        ...

    async def up(self, project_path: str, stack: Optional[str] = None) -> Tuple[str, str, int]:
        """Run pulumi up."""
        ...
```

### Key Constraints
- Always use `--json` flag for parseable output
- Use `--yes` flag for `up` and `destroy` commands (non-interactive)
- Handle stack selection: `pulumi stack select <name>` or `pulumi stack init <name>`
- Set working directory to `project_path` for all operations
- Parse JSON output into `PulumiOperationResult`

### CLI Commands Reference
```bash
# Preview changes
pulumi preview --json --stack dev

# Apply changes
pulumi up --yes --json --stack dev

# Destroy resources
pulumi destroy --yes --json --stack dev

# Get stack outputs
pulumi stack output --json --stack dev

# Select/create stack
pulumi stack select dev || pulumi stack init dev
```

### References in Codebase
- `parrot/tools/security/base_executor.py` — BaseExecutor to extend
- `parrot/tools/security/checkov/executor.py` — CLI argument building pattern
- `parrot/tools/security/prowler/executor.py` — Docker execution pattern

---

## Acceptance Criteria

- [ ] `PulumiExecutor` extends `BaseExecutor`
- [ ] `_build_cli_args()` generates correct args for all operations
- [ ] `preview()` returns parsed `PulumiOperationResult`
- [ ] `up()` returns parsed `PulumiOperationResult`
- [ ] `destroy()` returns parsed `PulumiOperationResult`
- [ ] Stack selection/creation handled automatically
- [ ] Unit tests pass: `pytest tests/tools/pulumi/test_executor.py -v`
- [ ] No linting errors: `ruff check parrot/tools/pulumi/executor.py`

---

## Test Specification

```python
# tests/tools/pulumi/test_executor.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot.tools.pulumi.executor import PulumiExecutor
from parrot.tools.pulumi.config import PulumiConfig


@pytest.fixture
def executor():
    return PulumiExecutor(PulumiConfig(use_docker=False))


class TestPulumiExecutorArgs:
    def test_build_preview_args(self, executor):
        """Preview command builds correct args."""
        args = executor._build_cli_args(command="preview", stack="dev")
        assert "preview" in args
        assert "--json" in args
        assert "--stack" in args
        assert "dev" in args

    def test_build_up_args(self, executor):
        """Up command includes --yes flag."""
        args = executor._build_cli_args(command="up", stack="dev")
        assert "up" in args
        assert "--yes" in args
        assert "--json" in args

    def test_build_destroy_args(self, executor):
        """Destroy command includes --yes flag."""
        args = executor._build_cli_args(command="destroy", stack="dev")
        assert "destroy" in args
        assert "--yes" in args


class TestPulumiExecutorOperations:
    @pytest.mark.asyncio
    async def test_preview_parses_output(self, executor):
        """Preview parses JSON output correctly."""
        mock_output = '{"steps": [{"op": "create", "urn": "test"}]}'
        with patch.object(executor, 'run_command', new_callable=AsyncMock) as mock:
            mock.return_value = (mock_output, "", 0)
            result = await executor.preview("/path/to/project", "dev")
            assert result[2] == 0  # exit code

    @pytest.mark.asyncio
    async def test_up_handles_error(self, executor):
        """Up returns error info on failure."""
        with patch.object(executor, 'run_command', new_callable=AsyncMock) as mock:
            mock.return_value = ("", "error: resource failed", 1)
            result = await executor.up("/path/to/project", "dev")
            assert result[2] == 1  # non-zero exit code
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-055-pulumi-executor.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
