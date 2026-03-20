# TASK-032: Shared Security Models

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

This is the foundational task for the Security Toolkits Suite (FEAT-011). All scanner integrations (Prowler, Trivy, Checkov) must normalize their findings into a unified data model. This task creates the shared models that enable cross-tool aggregation and unified compliance reporting.

Reference: Spec Section 2 (Architectural Design → Data Models) and Section 3 (Module 1).

---

## Scope

- Implement `parrot/tools/security/models.py` with all unified data models
- Create enums: `SeverityLevel`, `FindingSource`, `ComplianceFramework`, `CloudProvider`
- Create models: `SecurityFinding`, `ScanSummary`, `ScanResult`, `ComparisonDelta`, `ConsolidatedReport`
- Write unit tests for model serialization and validation

**NOT in scope**:
- Scanner-specific models (those go in each scanner's module)
- Base executor/parser (separate tasks)
- Any CLI/Docker execution logic

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/__init__.py` | CREATE | Package init with re-exports |
| `parrot/tools/security/models.py` | CREATE | All shared data models |
| `tests/test_security_models.py` | CREATE | Unit tests for models |

---

## Implementation Notes

### Pattern to Follow

Follow the existing `CloudSploitToolkit` models pattern:

```python
# Reference: parrot/tools/cloudsploit/models.py
from datetime import datetime
from enum import Enum
from typing import Optional, Union
from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    """Normalized severity levels across all scanners."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"
    PASS = "PASS"
    UNKNOWN = "UNKNOWN"
```

### Key Constraints

- All models must inherit from `pydantic.BaseModel`
- Use `Field(...)` with descriptions for all fields
- Enums inherit from `(str, Enum)` for JSON serialization
- Use `default_factory=list` for mutable defaults
- Include `raw: Optional[dict]` field in SecurityFinding for original scanner output

### References in Codebase

- `parrot/tools/cloudsploit/models.py` — pattern to follow exactly
- `parrot/tools/toolkit.py` — will be used by toolkits that consume these models

---

## Acceptance Criteria

- [x] All enums defined: `SeverityLevel`, `FindingSource`, `ComplianceFramework`, `CloudProvider`
- [x] All models defined: `SecurityFinding`, `ScanSummary`, `ScanResult`, `ComparisonDelta`, `ConsolidatedReport`
- [x] Models serialize to/from JSON correctly
- [x] All tests pass: `pytest tests/test_security_models.py -v`
- [x] No linting errors: `ruff check parrot/tools/security/`
- [x] Import works: `from parrot.tools.security.models import SecurityFinding, ScanResult`

---

## Test Specification

```python
# tests/test_security_models.py
import pytest
from datetime import datetime
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


class TestEnums:
    def test_severity_level_values(self):
        """All expected severity levels exist."""
        assert SeverityLevel.CRITICAL == "CRITICAL"
        assert SeverityLevel.PASS == "PASS"

    def test_finding_source_values(self):
        """All scanner sources defined."""
        assert FindingSource.PROWLER == "prowler"
        assert FindingSource.TRIVY == "trivy"
        assert FindingSource.CHECKOV == "checkov"

    def test_compliance_framework_values(self):
        """Key compliance frameworks defined."""
        assert ComplianceFramework.SOC2 == "soc2"
        assert ComplianceFramework.HIPAA == "hipaa"
        assert ComplianceFramework.PCI_DSS == "pci_dss"


class TestSecurityFinding:
    def test_minimal_finding(self):
        """Finding with required fields only."""
        finding = SecurityFinding(
            id="test-001",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.HIGH,
            title="Test Finding",
        )
        assert finding.id == "test-001"
        assert finding.region == "global"  # default

    def test_full_finding(self):
        """Finding with all fields populated."""
        finding = SecurityFinding(
            id="test-002",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.CRITICAL,
            title="Critical CVE Found",
            description="CVE-2024-1234 in package X",
            resource="arn:aws:s3:::my-bucket",
            resource_type="S3 Bucket",
            region="us-east-1",
            provider=CloudProvider.AWS,
            service="s3",
            check_id="s3_bucket_public_access",
            compliance_tags=["SOC2-CC6.1", "HIPAA-164.312"],
            remediation="Enable bucket encryption",
            raw={"original": "data"},
        )
        assert finding.compliance_tags == ["SOC2-CC6.1", "HIPAA-164.312"]

    def test_finding_json_roundtrip(self):
        """Finding serializes and deserializes correctly."""
        finding = SecurityFinding(
            id="test-003",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.MEDIUM,
            title="IaC Misconfiguration",
        )
        json_data = finding.model_dump_json()
        restored = SecurityFinding.model_validate_json(json_data)
        assert restored.id == finding.id


class TestScanResult:
    def test_empty_scan_result(self):
        """Scan result with no findings."""
        summary = ScanSummary(
            source=FindingSource.PROWLER,
            provider=CloudProvider.AWS,
            total_findings=0,
            scan_timestamp=datetime.now(),
        )
        result = ScanResult(findings=[], summary=summary)
        assert len(result.findings) == 0

    def test_scan_result_with_findings(self):
        """Scan result with multiple findings."""
        findings = [
            SecurityFinding(
                id=f"f-{i}",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.HIGH,
                title=f"Finding {i}",
            )
            for i in range(3)
        ]
        summary = ScanSummary(
            source=FindingSource.PROWLER,
            provider=CloudProvider.AWS,
            total_findings=3,
            high_count=3,
            scan_timestamp=datetime.now(),
        )
        result = ScanResult(findings=findings, summary=summary)
        assert result.summary.total_findings == 3


class TestConsolidatedReport:
    def test_empty_consolidated_report(self):
        """Consolidated report with no scan results."""
        report = ConsolidatedReport(generated_at=datetime.now())
        assert report.total_findings == 0
        assert report.scan_results == {}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-032-shared-security-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**:
- Created `parrot/tools/security/models.py` with all unified data models
- Created `parrot/tools/security/__init__.py` with package re-exports
- Created `tests/test_security_models.py` with 20 unit tests (all passing)
- Followed CloudSploitToolkit pattern with `(str, Enum)` for JSON serialization
- Added extra enums: `CLOUDSPLOIT`, `MANUAL` in FindingSource; `GDPR`, `ISO_27001`, `AWS_WELL_ARCHITECTED` in ComplianceFramework; `MULTI` in CloudProvider

**Deviations from spec**: Minor additions to enums for broader coverage; no breaking changes
