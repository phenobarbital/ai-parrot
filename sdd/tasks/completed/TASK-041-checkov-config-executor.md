# TASK-041: Checkov Config & Executor

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-032, TASK-033
**Assigned-to**: claude-session

---

## Context

Checkov is a static code analysis tool for infrastructure-as-code (IaC), scanning Terraform, CloudFormation, Kubernetes, Helm, Dockerfiles, and more for security misconfigurations and secrets.

Reference: Spec Section 6.1 (Checkov Scanner Module).

---

## Scope

- Create `parrot/tools/security/checkov/` package
- Implement `CheckovConfig` extending `BaseExecutorConfig`
- Implement `CheckovExecutor` extending `BaseExecutor`
- Support key CLI options: framework, checks, skip-checks, compact, external-checks
- Write unit tests

**NOT in scope**:
- Checkov parser (TASK-042)
- SecretsIaCToolkit (TASK-043)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/checkov/__init__.py` | CREATE | Package init |
| `parrot/tools/security/checkov/config.py` | CREATE | CheckovConfig model |
| `parrot/tools/security/checkov/executor.py` | CREATE | CheckovExecutor class |
| `parrot/tools/security/__init__.py` | MODIFY | Add checkov exports |
| `tests/test_checkov_executor.py` | CREATE | Unit tests |

---

## Implementation Notes

### CheckovConfig

```python
# parrot/tools/security/checkov/config.py
from pydantic import Field
from ..base_executor import BaseExecutorConfig


class CheckovConfig(BaseExecutorConfig):
    """Checkov-specific configuration."""
    docker_image: str = Field(default="bridgecrew/checkov:latest")

    # Scan options
    frameworks: list[str] = Field(
        default_factory=list,
        description="IaC frameworks: terraform, cloudformation, kubernetes, helm, "
                    "dockerfile, arm, bicep, serverless, github_actions"
    )
    skip_checks: list[str] = Field(default_factory=list, description="Check IDs to skip")
    run_checks: list[str] = Field(default_factory=list, description="Only run these checks")

    # Output
    output_format: str = Field(default="json", description="json, cli, sarif, junitxml")
    compact: bool = Field(default=True, description="Only show failed checks")

    # External checks
    external_checks_dir: str | None = Field(default=None, description="Custom policies dir")
    external_checks_git: str | None = Field(default=None, description="Git URL for policies")
```

### Checkov CLI Patterns

Checkov CLI: `checkov -d <dir> | -f <file> | --repo-id <repo> [options]`

Key options:
- `-d / --directory` : Directory to scan
- `-f / --file` : Specific file to scan
- `--framework` : terraform, cloudformation, kubernetes, etc.
- `--check` : Specific check IDs to run (CKV_AWS_*)
- `--skip-check` : Check IDs to skip
- `-o / --output` : json, cli, sarif, junitxml
- `--compact` : Only show failed checks
- `--external-checks-dir` : Custom policy directory
- `--soft-fail` : Always exit 0

### Key Constraints

- Always output JSON for parsing
- Support directory, file, and repo scanning modes
- Handle framework auto-detection vs explicit specification
- Include helper methods: `scan_directory()`, `scan_file()`, `scan_terraform()`, `scan_secrets()`

---

## Acceptance Criteria

- [ ] `CheckovConfig` extends `BaseExecutorConfig` with all Checkov-specific fields
- [ ] `CheckovExecutor._build_cli_args()` generates correct Checkov CLI arguments
- [ ] All scan modes supported: directory, file, framework-specific
- [ ] Helper methods implemented: `scan_directory()`, `scan_file()`, `scan_terraform()`, etc.
- [ ] All tests pass: `pytest tests/test_checkov_executor.py -v`
- [ ] Import works: `from parrot.tools.security.checkov import CheckovExecutor, CheckovConfig`

---

## Test Specification

```python
# tests/test_checkov_executor.py
import pytest
from parrot.tools.security.checkov.config import CheckovConfig
from parrot.tools.security.checkov.executor import CheckovExecutor


class TestCheckovConfig:
    def test_default_values(self):
        """Config has sensible defaults."""
        config = CheckovConfig()
        assert config.docker_image == "bridgecrew/checkov:latest"
        assert config.output_format == "json"
        assert config.compact is True

    def test_custom_frameworks(self):
        """Custom framework specification."""
        config = CheckovConfig(frameworks=["terraform", "cloudformation"])
        assert len(config.frameworks) == 2

    def test_check_filters(self):
        """Check inclusion/exclusion filters."""
        config = CheckovConfig(
            run_checks=["CKV_AWS_18", "CKV_AWS_21"],
            skip_checks=["CKV_AWS_1"],
        )
        assert "CKV_AWS_18" in config.run_checks
        assert "CKV_AWS_1" in config.skip_checks


class TestCheckovExecutor:
    @pytest.fixture
    def executor(self):
        config = CheckovConfig(
            frameworks=["terraform"],
            compact=True,
        )
        return CheckovExecutor(config)

    def test_build_directory_scan_args(self, executor):
        """Directory scan CLI args are built correctly."""
        args = executor._build_cli_args(scan_type="directory", target="/app/terraform")
        assert "-d" in args
        assert "/app/terraform" in args
        assert "-o" in args
        assert "json" in args
        assert "--compact" in args
        assert "--framework" in args
        assert "terraform" in args

    def test_build_file_scan_args(self, executor):
        """File scan CLI args are built correctly."""
        args = executor._build_cli_args(scan_type="file", target="/app/main.tf")
        assert "-f" in args
        assert "/app/main.tf" in args

    def test_build_args_with_checks(self):
        """Check filters are included."""
        config = CheckovConfig(
            run_checks=["CKV_AWS_18", "CKV_AWS_21"],
            skip_checks=["CKV_AWS_1"],
        )
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--check" in args
        assert "--skip-check" in args

    def test_build_args_without_compact(self):
        """Non-compact mode omits --compact flag."""
        config = CheckovConfig(compact=False)
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--compact" not in args

    def test_build_args_with_external_checks(self):
        """External checks directory is included."""
        config = CheckovConfig(external_checks_dir="/policies")
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--external-checks-dir" in args
        assert "/policies" in args

    def test_default_cli_name(self, executor):
        """Default CLI name is 'checkov'."""
        assert executor._default_cli_name() == "checkov"


class TestCheckovExecutorHelpers:
    @pytest.fixture
    def executor(self):
        return CheckovExecutor(CheckovConfig())

    def test_scan_directory_method_exists(self, executor):
        """scan_directory helper exists."""
        assert hasattr(executor, 'scan_directory')

    def test_scan_file_method_exists(self, executor):
        """scan_file helper exists."""
        assert hasattr(executor, 'scan_file')

    def test_scan_terraform_method_exists(self, executor):
        """scan_terraform helper exists."""
        assert hasattr(executor, 'scan_terraform')

    def test_scan_secrets_method_exists(self, executor):
        """scan_secrets helper exists."""
        assert hasattr(executor, 'scan_secrets')
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 6
2. **Check dependencies** — TASK-032, TASK-033 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-041-checkov-config-executor.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**: Implemented CheckovConfig and CheckovExecutor with full Checkov CLI support. Includes helper methods: scan_directory, scan_file, scan_terraform, scan_cloudformation, scan_kubernetes, scan_dockerfile, scan_secrets, scan_github_actions, list_checks. All 47 tests pass.

**Deviations from spec**: Added additional helper methods beyond the minimum required (scan_cloudformation, scan_kubernetes, scan_github_actions) for better coverage of common use cases.
