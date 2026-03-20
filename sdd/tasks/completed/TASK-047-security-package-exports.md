# TASK-047: Security Package Exports

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-037, TASK-040, TASK-043, TASK-046
**Assigned-to**: claude-session

---

## Context

This task ensures all security toolkits and components are properly exported from the package `__init__.py` files, making them easily importable by users.

Reference: Spec Section 2.1 (Module Structure).

---

## Scope

- Update `parrot/tools/security/__init__.py` with all exports
- Update `parrot/tools/__init__.py` to include security toolkits
- Ensure clean import paths for users
- Write import verification tests

**NOT in scope**:
- Implementation of any components (all done in prior tasks)
- Documentation (separate task if needed)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/__init__.py` | MODIFY | Export all public components |
| `parrot/tools/__init__.py` | MODIFY | Add security toolkit exports |
| `tests/test_security_imports.py` | CREATE | Import verification tests |

---

## Implementation Notes

### Security Package Exports

```python
# parrot/tools/security/__init__.py
"""AI-Parrot Security Toolkits Suite.

Provides agent-callable tools for cloud security scanning, compliance reporting,
and vulnerability management. Wraps Prowler, Trivy, and Checkov.

Usage:
    from parrot.tools.security import (
        CloudPostureToolkit,
        ContainerSecurityToolkit,
        SecretsIaCToolkit,
        ComplianceReportToolkit,
    )

    # Or import specific components
    from parrot.tools.security.models import SecurityFinding, ScanResult
    from parrot.tools.security.prowler import ProwlerExecutor, ProwlerConfig
"""

# Models
from .models import (
    SeverityLevel,
    FindingSource,
    ComplianceFramework,
    CloudProvider,
    SecurityFinding,
    ScanSummary,
    ScanResult,
    ComparisonDelta,
    ConsolidatedReport,
)

# Base classes
from .base_executor import BaseExecutor, BaseExecutorConfig
from .base_parser import BaseParser

# Toolkits
from .cloud_posture_toolkit import CloudPostureToolkit
from .container_security_toolkit import ContainerSecurityToolkit
from .secrets_iac_toolkit import SecretsIaCToolkit
from .compliance_report_toolkit import ComplianceReportToolkit

# Scanner modules (for advanced usage)
from .prowler import ProwlerExecutor, ProwlerConfig, ProwlerParser
from .trivy import TrivyExecutor, TrivyConfig, TrivyParser
from .checkov import CheckovExecutor, CheckovConfig, CheckovParser

# Reports
from .reports import ComplianceMapper, ReportGenerator

__all__ = [
    # Models
    "SeverityLevel",
    "FindingSource",
    "ComplianceFramework",
    "CloudProvider",
    "SecurityFinding",
    "ScanSummary",
    "ScanResult",
    "ComparisonDelta",
    "ConsolidatedReport",
    # Base classes
    "BaseExecutor",
    "BaseExecutorConfig",
    "BaseParser",
    # Toolkits
    "CloudPostureToolkit",
    "ContainerSecurityToolkit",
    "SecretsIaCToolkit",
    "ComplianceReportToolkit",
    # Scanner components
    "ProwlerExecutor",
    "ProwlerConfig",
    "ProwlerParser",
    "TrivyExecutor",
    "TrivyConfig",
    "TrivyParser",
    "CheckovExecutor",
    "CheckovConfig",
    "CheckovParser",
    # Reports
    "ComplianceMapper",
    "ReportGenerator",
]
```

### Tools Package Update

```python
# parrot/tools/__init__.py (add to existing exports)
from .security import (
    CloudPostureToolkit,
    ContainerSecurityToolkit,
    SecretsIaCToolkit,
    ComplianceReportToolkit,
)
```

### Key Constraints

- All imports should be lazy-safe (no heavy imports at module level)
- `__all__` must be defined for explicit public API
- Docstring should include usage examples
- Avoid circular imports

---

## Acceptance Criteria

- [ ] All 4 toolkits importable from `parrot.tools.security`
- [ ] All 4 toolkits importable from `parrot.tools`
- [ ] Models importable: `from parrot.tools.security.models import SecurityFinding`
- [ ] Scanner components importable: `from parrot.tools.security.prowler import ProwlerExecutor`
- [ ] `__all__` defined with all public exports
- [ ] All tests pass: `pytest tests/test_security_imports.py -v`
- [ ] No circular import errors

---

## Test Specification

```python
# tests/test_security_imports.py
import pytest


class TestSecurityPackageImports:
    def test_import_toolkits_from_security(self):
        """Toolkits importable from parrot.tools.security."""
        from parrot.tools.security import (
            CloudPostureToolkit,
            ContainerSecurityToolkit,
            SecretsIaCToolkit,
            ComplianceReportToolkit,
        )
        assert CloudPostureToolkit is not None
        assert ContainerSecurityToolkit is not None
        assert SecretsIaCToolkit is not None
        assert ComplianceReportToolkit is not None

    def test_import_toolkits_from_tools(self):
        """Toolkits importable from parrot.tools."""
        from parrot.tools import (
            CloudPostureToolkit,
            ContainerSecurityToolkit,
            SecretsIaCToolkit,
            ComplianceReportToolkit,
        )
        assert CloudPostureToolkit is not None

    def test_import_models(self):
        """Models importable from security.models."""
        from parrot.tools.security.models import (
            SeverityLevel,
            FindingSource,
            ComplianceFramework,
            CloudProvider,
            SecurityFinding,
            ScanSummary,
            ScanResult,
            ComparisonDelta,
            ConsolidatedReport,
        )
        assert SeverityLevel.CRITICAL == "CRITICAL"

    def test_import_base_classes(self):
        """Base classes importable."""
        from parrot.tools.security import (
            BaseExecutor,
            BaseExecutorConfig,
            BaseParser,
        )
        assert BaseExecutor is not None

    def test_import_prowler_components(self):
        """Prowler components importable."""
        from parrot.tools.security.prowler import (
            ProwlerExecutor,
            ProwlerConfig,
            ProwlerParser,
        )
        assert ProwlerExecutor is not None

    def test_import_trivy_components(self):
        """Trivy components importable."""
        from parrot.tools.security.trivy import (
            TrivyExecutor,
            TrivyConfig,
            TrivyParser,
        )
        assert TrivyExecutor is not None

    def test_import_checkov_components(self):
        """Checkov components importable."""
        from parrot.tools.security.checkov import (
            CheckovExecutor,
            CheckovConfig,
            CheckovParser,
        )
        assert CheckovExecutor is not None

    def test_import_reports(self):
        """Report components importable."""
        from parrot.tools.security.reports import (
            ComplianceMapper,
            ReportGenerator,
        )
        assert ComplianceMapper is not None
        assert ReportGenerator is not None

    def test_all_defined(self):
        """__all__ is defined in security package."""
        from parrot.tools import security
        assert hasattr(security, '__all__')
        assert len(security.__all__) > 0

    def test_no_circular_imports(self):
        """No circular import errors."""
        # If we got here without ImportError, circular imports are avoided
        import parrot.tools.security
        import parrot.tools.security.cloud_posture_toolkit
        import parrot.tools.security.compliance_report_toolkit
        assert True


class TestToolkitInstantiation:
    def test_instantiate_cloud_posture(self):
        """CloudPostureToolkit can be instantiated."""
        from parrot.tools.security import CloudPostureToolkit
        toolkit = CloudPostureToolkit()
        assert toolkit is not None
        assert len(toolkit.get_tools()) > 0

    def test_instantiate_container_security(self):
        """ContainerSecurityToolkit can be instantiated."""
        from parrot.tools.security import ContainerSecurityToolkit
        toolkit = ContainerSecurityToolkit()
        assert toolkit is not None

    def test_instantiate_secrets_iac(self):
        """SecretsIaCToolkit can be instantiated."""
        from parrot.tools.security import SecretsIaCToolkit
        toolkit = SecretsIaCToolkit()
        assert toolkit is not None

    def test_instantiate_compliance_report(self):
        """ComplianceReportToolkit can be instantiated."""
        from parrot.tools.security import ComplianceReportToolkit
        toolkit = ComplianceReportToolkit()
        assert toolkit is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — All toolkit tasks must be complete
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Update __init__.py files** as specified
4. **Run import tests** to verify no circular imports
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-047-security-package-exports.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**: Updated security __init__.py with reports exports and enhanced docstring. Added security toolkits to parrot.tools __init__.py via lazy import pattern. All 26 import verification tests passing.

**Deviations from spec**: none - all exports work as specified.
