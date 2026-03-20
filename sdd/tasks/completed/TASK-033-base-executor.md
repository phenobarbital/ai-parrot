# TASK-033: Base Executor

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-032
**Assigned-to**: claude-session

---

## Context

The Base Executor provides a reusable abstraction for running CLI-based security scanners via Docker or direct process execution. All scanner executors (Prowler, Trivy, Checkov) will inherit from this base class.

Reference: Spec Section 3.2 (Base Executor) and Section 3 (Module 2).

---

## Scope

- Implement `parrot/tools/security/base_executor.py`
- Create `BaseExecutorConfig` Pydantic model with cloud credential fields
- Create abstract `BaseExecutor` class with:
  - `_build_env_vars()` — cloud credential injection
  - `_build_docker_command()` — Docker run command builder
  - `_build_direct_command()` — CLI fallback
  - `execute()` — async subprocess execution with timeout
  - `_mask_command()` — credential masking for logs
- Write unit tests

**NOT in scope**:
- Scanner-specific executors (separate tasks)
- Parser logic
- Report generation

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/base_executor.py` | CREATE | Abstract base executor |
| `parrot/tools/security/__init__.py` | MODIFY | Add BaseExecutor export |
| `tests/test_security_base_executor.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/tools/security/base_executor.py
from abc import ABC, abstractmethod
from typing import Optional
import asyncio
import os
from pydantic import BaseModel, Field
from navconfig.logging import logging


class BaseExecutorConfig(BaseModel):
    """Base configuration shared by all scanner executors."""
    use_docker: bool = Field(default=True, description="Run via Docker or direct CLI")
    docker_image: str = Field(default="", description="Docker image to use")
    cli_path: Optional[str] = Field(default=None, description="Path to CLI binary")
    timeout: int = Field(default=600, description="Execution timeout in seconds")
    results_dir: Optional[str] = Field(default=None, description="Results directory")

    # AWS credentials
    aws_access_key_id: Optional[str] = Field(default=None)
    aws_secret_access_key: Optional[str] = Field(default=None)
    aws_session_token: Optional[str] = Field(default=None)
    aws_profile: Optional[str] = Field(default=None)
    aws_region: str = Field(default="us-east-1")

    # GCP credentials
    gcp_credentials_file: Optional[str] = Field(default=None)
    gcp_project_id: Optional[str] = Field(default=None)

    # Azure credentials
    azure_client_id: Optional[str] = Field(default=None)
    azure_client_secret: Optional[str] = Field(default=None)
    azure_tenant_id: Optional[str] = Field(default=None)
    azure_subscription_id: Optional[str] = Field(default=None)


class BaseExecutor(ABC):
    """Abstract base executor — Docker or CLI process management."""

    def __init__(self, config: BaseExecutorConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build CLI arguments specific to the scanner."""
        ...

    @abstractmethod
    def _default_cli_name(self) -> str:
        """Return the default CLI binary name."""
        ...
```

### Key Constraints

- All execution methods must be async
- Credentials must NEVER appear in logs — use `_mask_command()`
- Timeout must be enforced with `asyncio.wait_for()`
- Support both Docker and direct CLI execution modes
- Kill process on timeout, don't leave zombies

### References in Codebase

- `parrot/tools/cloudsploit/executor.py` — similar pattern

---

## Acceptance Criteria

- [x] `BaseExecutorConfig` includes all cloud credential fields (AWS, GCP, Azure)
- [x] `BaseExecutor._build_env_vars()` correctly builds environment dict
- [x] `BaseExecutor._build_docker_command()` builds valid docker run command
- [x] `BaseExecutor.execute()` runs async subprocess with timeout
- [x] `BaseExecutor._mask_command()` masks secrets in logged output
- [x] All tests pass: `pytest tests/test_security_base_executor.py -v`
- [x] Import works: `from parrot.tools.security.base_executor import BaseExecutor`

---

## Test Specification

```python
# tests/test_security_base_executor.py
import pytest
from parrot.tools.security.base_executor import BaseExecutor, BaseExecutorConfig


class ConcreteExecutor(BaseExecutor):
    """Test implementation of BaseExecutor."""

    def _build_cli_args(self, **kwargs) -> list[str]:
        return ["--test", kwargs.get("param", "default")]

    def _default_cli_name(self) -> str:
        return "test-scanner"


class TestBaseExecutorConfig:
    def test_default_values(self):
        """Config has sensible defaults."""
        config = BaseExecutorConfig()
        assert config.use_docker is True
        assert config.timeout == 600
        assert config.aws_region == "us-east-1"

    def test_aws_credentials(self):
        """AWS credentials can be set."""
        config = BaseExecutorConfig(
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret123",
            aws_region="eu-west-1",
        )
        assert config.aws_access_key_id == "AKIATEST"


class TestBaseExecutor:
    @pytest.fixture
    def executor(self):
        config = BaseExecutorConfig(
            use_docker=True,
            docker_image="test/scanner:latest",
            aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
            aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        return ConcreteExecutor(config)

    def test_build_env_vars(self, executor):
        """Environment variables are built correctly."""
        env = executor._build_env_vars()
        assert env["AWS_ACCESS_KEY_ID"] == "AKIAIOSFODNN7EXAMPLE"
        assert "AWS_SECRET_ACCESS_KEY" in env
        assert env["AWS_DEFAULT_REGION"] == "us-east-1"

    def test_build_docker_command(self, executor):
        """Docker command is built correctly."""
        args = ["--check", "s3"]
        cmd = executor._build_docker_command(args)
        assert cmd[0] == "docker"
        assert "run" in cmd
        assert "--rm" in cmd
        assert "test/scanner:latest" in cmd
        assert "--check" in cmd

    def test_build_direct_command(self, executor):
        """Direct CLI command is built correctly."""
        executor.config.use_docker = False
        args = ["--check", "s3"]
        cmd = executor._build_direct_command(args)
        assert cmd[0] == "test-scanner"
        assert "--check" in cmd

    def test_mask_command_hides_secrets(self, executor):
        """Secrets are masked in command output."""
        cmd = [
            "docker", "run", "-e",
            "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG",
            "-e", "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
        ]
        masked = executor._mask_command(cmd)
        assert "wJalrXUtnFEMI" not in masked
        assert "***" in masked
        # Access key ID should show first 3 chars only
        assert "AKI***" in masked


class TestExecutorExecution:
    @pytest.fixture
    def echo_executor(self):
        """Executor that runs echo command."""
        config = BaseExecutorConfig(use_docker=False, cli_path="echo")
        return ConcreteExecutor(config)

    @pytest.mark.asyncio
    async def test_execute_success(self, echo_executor):
        """Execute returns stdout, stderr, exit code."""
        # Override to run simple echo
        stdout, stderr, code = await echo_executor.execute(["hello", "world"])
        assert "hello world" in stdout or code == 0

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        """Execution times out correctly."""
        config = BaseExecutorConfig(use_docker=False, cli_path="sleep", timeout=1)
        executor = ConcreteExecutor(config)
        stdout, stderr, code = await executor.execute(["10"])
        assert code == -1  # Timeout indicator
        assert "Timeout" in stderr
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` for full context
2. **Check dependencies** — TASK-032 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-033-base-executor.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**:
- Created `parrot/tools/security/base_executor.py` with BaseExecutorConfig and BaseExecutor
- Supports AWS, GCP, and Azure credentials via environment variables
- Docker and direct CLI execution modes with timeout handling
- Credential masking for safe logging (AWS keys, Azure secrets, GCP paths)
- Updated `__init__.py` with exports
- Created 22 unit tests covering config, env vars, commands, masking, and execution

**Deviations from spec**: Added `_build_process_env()` method for cleaner direct CLI execution; enhanced credential masking to cover Azure and GCP
