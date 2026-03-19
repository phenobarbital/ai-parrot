# TASK-038: Trivy Config & Executor

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-032, TASK-033
**Assigned-to**: unassigned

---

## Context

Trivy is a comprehensive security scanner for containers, filesystems, git repositories, Kubernetes, and IaC configurations. This task implements the Trivy-specific configuration and executor.

Reference: Spec Section 5.1 (Trivy Scanner Module).

---

## Scope

- Create `parrot/tools/security/trivy/` package
- Implement `TrivyConfig` extending `BaseExecutorConfig`
- Implement `TrivyExecutor` extending `BaseExecutor`
- Support all Trivy scan types: image, fs, repo, config, k8s, sbom
- Support key CLI options: format, severity, scanners, compliance
- Write unit tests

**NOT in scope**:
- Trivy parser (TASK-039)
- ContainerSecurityToolkit (TASK-040)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/trivy/__init__.py` | CREATE | Package init |
| `parrot/tools/security/trivy/config.py` | CREATE | TrivyConfig model |
| `parrot/tools/security/trivy/executor.py` | CREATE | TrivyExecutor class |
| `parrot/tools/security/__init__.py` | MODIFY | Add trivy exports |
| `tests/test_trivy_executor.py` | CREATE | Unit tests |

---

## Implementation Notes

### TrivyConfig

```python
# parrot/tools/security/trivy/config.py
from pydantic import Field
from ..base_executor import BaseExecutorConfig


class TrivyConfig(BaseExecutorConfig):
    """Trivy-specific configuration."""
    docker_image: str = Field(default="aquasec/trivy:latest")
    cache_dir: str | None = Field(default=None, description="Trivy cache directory")
    db_skip_update: bool = Field(default=False, description="Skip vulnerability DB update")

    # Scan options
    severity_filter: list[str] = Field(
        default=["CRITICAL", "HIGH"],
        description="Severity levels to include"
    )
    ignore_unfixed: bool = Field(default=False, description="Ignore unfixed vulnerabilities")
    scanners: list[str] = Field(
        default=["vuln", "secret"],
        description="Scanner types: vuln, misconfig, secret, license"
    )

    # Output
    output_format: str = Field(default="json", description="json, table, sarif, cyclonedx")
```

### Trivy CLI Patterns

Trivy CLI: `trivy <scan_type> [options] <target>`

Scan types:
- `image` — Container image vulnerabilities
- `fs` — Filesystem scanning
- `repo` — Git repository scanning
- `config` — IaC misconfiguration
- `k8s` — Kubernetes cluster
- `sbom` — SBOM generation

Key options:
- `--format` : json, table, sarif, cyclonedx, spdx
- `--severity` : CRITICAL,HIGH,MEDIUM,LOW,UNKNOWN
- `--ignore-unfixed` : skip unfixed vulns
- `--scanners` : vuln, misconfig, secret, license
- `--output` : output file path
- `--compliance` : compliance spec (e.g. docker-cis-1.6.0)

### Key Constraints

- Always output JSON for parsing
- Support multiple scan types via different methods
- Handle K8s context/namespace for cluster scans
- Include helper methods: `scan_image()`, `scan_filesystem()`, `scan_k8s()`, `generate_sbom()`

---

## Acceptance Criteria

- [ ] `TrivyConfig` extends `BaseExecutorConfig` with all Trivy-specific fields
- [ ] `TrivyExecutor._build_cli_args()` generates correct Trivy CLI arguments
- [ ] All scan types supported: image, fs, repo, config, k8s, sbom
- [ ] Helper methods implemented: `scan_image()`, `scan_filesystem()`, `scan_k8s()`, `generate_sbom()`
- [ ] All tests pass: `pytest tests/test_trivy_executor.py -v`
- [ ] Import works: `from parrot.tools.security.trivy import TrivyExecutor, TrivyConfig`

---

## Test Specification

```python
# tests/test_trivy_executor.py
import pytest
from parrot.tools.security.trivy.config import TrivyConfig
from parrot.tools.security.trivy.executor import TrivyExecutor


class TestTrivyConfig:
    def test_default_values(self):
        """Config has sensible defaults."""
        config = TrivyConfig()
        assert config.docker_image == "aquasec/trivy:latest"
        assert "CRITICAL" in config.severity_filter
        assert "vuln" in config.scanners

    def test_custom_severity(self):
        """Custom severity filter."""
        config = TrivyConfig(severity_filter=["CRITICAL", "HIGH", "MEDIUM"])
        assert len(config.severity_filter) == 3

    def test_custom_scanners(self):
        """Custom scanner types."""
        config = TrivyConfig(scanners=["vuln", "misconfig", "secret", "license"])
        assert len(config.scanners) == 4


class TestTrivyExecutor:
    @pytest.fixture
    def executor(self):
        config = TrivyConfig(
            severity_filter=["CRITICAL", "HIGH"],
            scanners=["vuln", "secret"],
        )
        return TrivyExecutor(config)

    def test_build_image_scan_args(self, executor):
        """Image scan CLI args are built correctly."""
        args = executor._build_cli_args(scan_type="image", target="nginx:latest")
        assert args[0] == "image"
        assert "--format" in args
        assert "json" in args
        assert "--severity" in args
        assert "CRITICAL,HIGH" in args
        assert "--scanners" in args
        assert "nginx:latest" in args

    def test_build_fs_scan_args(self, executor):
        """Filesystem scan CLI args are built correctly."""
        args = executor._build_cli_args(scan_type="fs", target="/app")
        assert args[0] == "fs"
        assert "/app" in args

    def test_build_k8s_scan_args(self, executor):
        """Kubernetes scan CLI args are built correctly."""
        args = executor._build_cli_args(
            scan_type="k8s",
            target="cluster",
            k8s_context="my-context",
            k8s_namespace="default",
        )
        assert args[0] == "k8s"
        assert "--context" in args or "my-context" in args

    def test_build_sbom_args(self, executor):
        """SBOM generation CLI args are built correctly."""
        args = executor._build_cli_args(
            scan_type="image",
            target="myapp:v1",
            sbom_format="cyclonedx",
        )
        assert "--format" in args
        # SBOM format should be set

    def test_ignore_unfixed_flag(self):
        """ignore_unfixed flag is included."""
        config = TrivyConfig(ignore_unfixed=True)
        executor = TrivyExecutor(config)
        args = executor._build_cli_args(scan_type="image", target="test:latest")
        assert "--ignore-unfixed" in args

    def test_compliance_flag(self, executor):
        """Compliance flag is included when specified."""
        args = executor._build_cli_args(
            scan_type="k8s",
            target="cluster",
            compliance="k8s-cis-1.23",
        )
        assert "--compliance" in args
        assert "k8s-cis-1.23" in args

    def test_default_cli_name(self, executor):
        """Default CLI name is 'trivy'."""
        assert executor._default_cli_name() == "trivy"


class TestTrivyExecutorHelpers:
    @pytest.fixture
    def executor(self):
        return TrivyExecutor(TrivyConfig())

    def test_scan_image_builds_correct_args(self, executor):
        """scan_image helper builds image scan args."""
        # Verify method exists and has correct signature
        assert hasattr(executor, 'scan_image')

    def test_scan_filesystem_builds_correct_args(self, executor):
        """scan_filesystem helper builds fs scan args."""
        assert hasattr(executor, 'scan_filesystem')

    def test_scan_k8s_builds_correct_args(self, executor):
        """scan_k8s helper builds k8s scan args."""
        assert hasattr(executor, 'scan_k8s')

    def test_generate_sbom_builds_correct_args(self, executor):
        """generate_sbom helper builds sbom args."""
        assert hasattr(executor, 'generate_sbom')
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 5
2. **Check dependencies** — TASK-032, TASK-033 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-038-trivy-config-executor.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**:
- Created `parrot/tools/security/trivy/` package with config.py, executor.py, __init__.py
- TrivyConfig supports all Trivy scan options: severity, scanners, cache, k8s, compliance, skip patterns
- TrivyExecutor implements all scan types: image, fs, repo, config, k8s, sbom
- Added helper methods: scan_image(), scan_filesystem(), scan_repository(), scan_config(), scan_k8s(), generate_sbom()
- 38 tests passing
- Exports added to parrot/tools/security/__init__.py

**Deviations from spec**: Added additional helper method scan_repository() beyond spec requirements
