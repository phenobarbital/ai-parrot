# TASK-035: Prowler Config & Executor

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-032, TASK-033
**Assigned-to**: claude-session

---

## Context

Prowler is a cloud security posture assessment tool supporting AWS, Azure, GCP, and Kubernetes. This task implements the Prowler-specific configuration and executor that builds on the base executor.

Reference: Spec Section 4.1.1 (Config) and 4.1.2 (Executor).

---

## Scope

- Create `parrot/tools/security/prowler/` package
- Implement `ProwlerConfig` extending `BaseExecutorConfig`
- Implement `ProwlerExecutor` extending `BaseExecutor`
- Support all Prowler CLI options: provider, output modes, region filtering, compliance framework
- Write unit tests

**NOT in scope**:
- Prowler parser (TASK-036)
- CloudPostureToolkit (TASK-037)
- Actual Docker/CLI execution tests (use mocks)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/prowler/__init__.py` | CREATE | Package init |
| `parrot/tools/security/prowler/config.py` | CREATE | ProwlerConfig model |
| `parrot/tools/security/prowler/executor.py` | CREATE | ProwlerExecutor class |
| `parrot/tools/security/__init__.py` | MODIFY | Add prowler exports |
| `tests/test_prowler_executor.py` | CREATE | Unit tests |

---

## Implementation Notes

### ProwlerConfig

```python
# parrot/tools/security/prowler/config.py
from pydantic import Field
from ..base_executor import BaseExecutorConfig


class ProwlerConfig(BaseExecutorConfig):
    """Prowler-specific configuration."""
    docker_image: str = Field(default="toniblyx/prowler:latest")
    provider: str = Field(default="aws", description="aws, azure, gcp, kubernetes")
    output_modes: list[str] = Field(default=["json-ocsf"])

    # AWS-specific
    filter_regions: list[str] = Field(default_factory=list)

    # Azure-specific
    azure_auth_method: str | None = Field(default=None)
    subscription_ids: list[str] = Field(default_factory=list)

    # GCP-specific
    gcp_project_ids: list[str] = Field(default_factory=list)

    # Scan filtering
    services: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    excluded_checks: list[str] = Field(default_factory=list)
    excluded_services: list[str] = Field(default_factory=list)
    severity: list[str] = Field(default_factory=list)
    compliance_framework: str | None = Field(default=None)
```

### ProwlerExecutor CLI Building

Prowler CLI pattern: `prowler <provider> [options]`

Key options to support:
- `-M / --output-modes` : csv, json, json-ocsf, json-asff, html
- `-c / --checks` : specific check IDs
- `-s / --services` : specific services
- `-e / --excluded-checks` : exclude checks
- `-f / --filter-region` : specific regions (AWS)
- `--compliance` : compliance framework filter
- `--severity` : severity filter
- `-p / --profile` : AWS profile
- `--sp-env-auth` : Azure service principal
- `--project-ids` : GCP project IDs

### Key Constraints

- Always output JSON-OCSF for parsing
- Support all three major cloud providers
- Build CLI args dynamically based on config
- Include `run_scan()`, `list_checks()`, `list_services()` helper methods

### References in Codebase

- `parrot/tools/cloudsploit/executor.py` — similar pattern

---

## Acceptance Criteria

- [x] `ProwlerConfig` extends `BaseExecutorConfig` with all Prowler-specific fields
- [x] `ProwlerExecutor._build_cli_args()` generates correct Prowler CLI arguments
- [x] AWS, Azure, GCP provider-specific options are handled correctly
- [x] `run_scan()`, `list_checks()`, `list_services()` methods implemented
- [x] All tests pass: `pytest tests/test_prowler_executor.py -v`
- [x] Import works: `from parrot.tools.security.prowler import ProwlerExecutor, ProwlerConfig`

---

## Test Specification

```python
# tests/test_prowler_executor.py
import pytest
from parrot.tools.security.prowler.config import ProwlerConfig
from parrot.tools.security.prowler.executor import ProwlerExecutor


class TestProwlerConfig:
    def test_default_values(self):
        """Config has sensible defaults."""
        config = ProwlerConfig()
        assert config.provider == "aws"
        assert config.docker_image == "toniblyx/prowler:latest"
        assert "json-ocsf" in config.output_modes

    def test_aws_config(self):
        """AWS-specific configuration."""
        config = ProwlerConfig(
            provider="aws",
            filter_regions=["us-east-1", "eu-west-1"],
            services=["s3", "iam"],
            compliance_framework="soc2",
        )
        assert config.filter_regions == ["us-east-1", "eu-west-1"]

    def test_azure_config(self):
        """Azure-specific configuration."""
        config = ProwlerConfig(
            provider="azure",
            azure_auth_method="sp-env-auth",
            subscription_ids=["sub-123", "sub-456"],
        )
        assert config.azure_auth_method == "sp-env-auth"

    def test_gcp_config(self):
        """GCP-specific configuration."""
        config = ProwlerConfig(
            provider="gcp",
            gcp_project_ids=["project-1", "project-2"],
        )
        assert len(config.gcp_project_ids) == 2


class TestProwlerExecutor:
    @pytest.fixture
    def aws_executor(self):
        config = ProwlerConfig(
            provider="aws",
            filter_regions=["us-east-1"],
            services=["s3", "iam"],
            severity=["critical", "high"],
        )
        return ProwlerExecutor(config)

    @pytest.fixture
    def azure_executor(self):
        config = ProwlerConfig(
            provider="azure",
            azure_auth_method="sp-env-auth",
            subscription_ids=["sub-123"],
        )
        return ProwlerExecutor(config)

    def test_build_aws_args(self, aws_executor):
        """AWS CLI args are built correctly."""
        args = aws_executor._build_cli_args()
        assert args[0] == "aws"
        assert "-M" in args
        assert "json-ocsf" in args
        assert "-f" in args
        assert "us-east-1" in args
        assert "-s" in args
        assert "s3" in args
        assert "--severity" in args

    def test_build_azure_args(self, azure_executor):
        """Azure CLI args are built correctly."""
        args = azure_executor._build_cli_args()
        assert args[0] == "azure"
        assert "--sp-env-auth" in args
        assert "--subscription-ids" in args

    def test_build_args_with_compliance(self):
        """Compliance framework flag is included."""
        config = ProwlerConfig(
            provider="aws",
            compliance_framework="hipaa",
        )
        executor = ProwlerExecutor(config)
        args = executor._build_cli_args()
        assert "--compliance" in args
        assert "hipaa" in args

    def test_build_args_with_exclusions(self):
        """Exclusion flags are included."""
        config = ProwlerConfig(
            provider="aws",
            excluded_checks=["check1", "check2"],
            excluded_services=["cloudtrail"],
        )
        executor = ProwlerExecutor(config)
        args = executor._build_cli_args()
        assert "-e" in args
        assert "--excluded-services" in args

    def test_override_provider_in_kwargs(self, aws_executor):
        """Provider can be overridden via kwargs."""
        args = aws_executor._build_cli_args(provider="gcp")
        assert args[0] == "gcp"

    def test_list_checks_args(self, aws_executor):
        """list_checks builds correct args."""
        # Test that list_checks would call with --list-checks
        # (actual execution would be mocked in integration tests)
        pass

    def test_default_cli_name(self, aws_executor):
        """Default CLI name is 'prowler'."""
        assert aws_executor._default_cli_name() == "prowler"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 4
2. **Check dependencies** — TASK-032, TASK-033 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-035-prowler-config-executor.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**:
- Created `parrot/tools/security/prowler/` package with config.py, executor.py, __init__.py
- ProwlerConfig supports: AWS (regions, profile), Azure (auth method, subscriptions), GCP (projects), Kubernetes (context, namespace)
- ProwlerExecutor implements: `run_scan()`, `list_checks()`, `list_services()`, `list_compliance_frameworks()`
- Updated security __init__.py with prowler exports
- Created 25 unit tests covering all providers and CLI argument building

**Deviations from spec**: Added Kubernetes provider support and `list_compliance_frameworks()` helper method
