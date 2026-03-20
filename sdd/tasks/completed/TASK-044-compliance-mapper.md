# TASK-044: Compliance Mapper

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-032
**Assigned-to**: claude-session

---

## Context

The Compliance Mapper is responsible for mapping normalized `SecurityFinding` objects to compliance framework controls (SOC2, HIPAA, PCI-DSS, etc.). This is the critical piece that enables cross-tool compliance reporting.

Reference: Spec Section 8.1 (Compliance Mapper).

---

## Scope

- Implement `parrot/tools/security/reports/compliance_mapper.py`
- Create `ComplianceMapper` class with:
  - `map_finding_to_controls()` — Map finding to framework controls
  - `get_framework_coverage()` — Calculate compliance coverage
  - `get_control_details()` — Get details for a specific control
- Create compliance mapping data files:
  - `parrot/tools/security/reports/mappings/soc2_controls.yaml`
  - `parrot/tools/security/reports/mappings/hipaa_controls.yaml`
  - `parrot/tools/security/reports/mappings/pci_dss_controls.yaml`
- Map scanner check IDs to framework controls
- Write comprehensive unit tests

**NOT in scope**:
- Report generation (TASK-045)
- ComplianceReportToolkit (TASK-046)
- Full mapping coverage (start with key controls, expand later)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/reports/__init__.py` | CREATE | Package init |
| `parrot/tools/security/reports/compliance_mapper.py` | CREATE | ComplianceMapper class |
| `parrot/tools/security/reports/mappings/soc2_controls.yaml` | CREATE | SOC2 control mappings |
| `parrot/tools/security/reports/mappings/hipaa_controls.yaml` | CREATE | HIPAA control mappings |
| `parrot/tools/security/reports/mappings/pci_dss_controls.yaml` | CREATE | PCI-DSS control mappings |
| `tests/test_compliance_mapper.py` | CREATE | Unit tests |

---

## Implementation Notes

### ComplianceMapper Class

```python
# parrot/tools/security/reports/compliance_mapper.py
from pathlib import Path
from typing import Optional
import yaml
from ..models import SecurityFinding, ComplianceFramework


class ComplianceMapper:
    """Maps security findings to compliance framework controls.

    Maintains a mapping database from:
    - Prowler check IDs → compliance controls
    - Trivy vulnerability types → compliance controls
    - Checkov policy IDs → compliance controls
    """

    def __init__(self, mappings_dir: str | None = None):
        self.mappings_dir = Path(mappings_dir or Path(__file__).parent / "mappings")
        self._mappings: dict[str, dict] = {}
        self._controls: dict[str, dict] = {}
        self._load_mappings()

    def _load_mappings(self) -> None:
        """Load all YAML mapping files."""
        for framework in ComplianceFramework:
            mapping_file = self.mappings_dir / f"{framework.value}_controls.yaml"
            if mapping_file.exists():
                with open(mapping_file) as f:
                    data = yaml.safe_load(f)
                    self._mappings[framework.value] = data.get("check_mappings", {})
                    self._controls[framework.value] = data.get("controls", {})

    def map_finding_to_controls(
        self, finding: SecurityFinding, framework: ComplianceFramework
    ) -> list[str]:
        """Map a finding to relevant compliance controls."""
        ...

    def get_framework_coverage(
        self, findings: list[SecurityFinding], framework: ComplianceFramework
    ) -> dict:
        """Calculate compliance coverage for a framework."""
        ...

    def get_control_details(
        self, control_id: str, framework: ComplianceFramework
    ) -> dict | None:
        """Get details for a specific control."""
        ...
```

### YAML Mapping Format

```yaml
# soc2_controls.yaml
framework: soc2
version: "2017"

controls:
  CC6.1:
    name: "Logical and Physical Access Controls"
    description: "The entity implements logical access security software..."
    category: "access_control"

  CC6.6:
    name: "System Boundaries Protection"
    description: "The entity implements controls to protect..."
    category: "network_security"

check_mappings:
  # Prowler check mappings
  prowler:
    s3_bucket_public_access: ["CC6.1", "CC6.6"]
    iam_root_mfa_enabled: ["CC6.1"]
    ec2_security_groups_default: ["CC6.6"]

  # Trivy mappings (by finding type)
  trivy:
    vulnerability_critical: ["CC7.1"]
    vulnerability_high: ["CC7.1"]
    secret_exposed: ["CC6.1"]

  # Checkov mappings
  checkov:
    CKV_AWS_18: ["CC6.1"]  # S3 logging
    CKV_AWS_19: ["CC6.1"]  # S3 encryption
    CKV_AWS_21: ["CC7.2"]  # S3 versioning
```

### Key SOC2 Trust Service Criteria

- **CC1**: Control Environment
- **CC2**: Communication and Information
- **CC3**: Risk Assessment
- **CC4**: Monitoring Activities
- **CC5**: Control Activities
- **CC6**: Logical and Physical Access Controls
- **CC7**: System Operations
- **CC8**: Change Management
- **CC9**: Risk Mitigation

### Key HIPAA Safeguards

- **§164.308**: Administrative Safeguards
- **§164.310**: Physical Safeguards
- **§164.312**: Technical Safeguards
- **§164.314**: Organizational Requirements

### Key Constraints

- Use YAML for human-readable mapping files
- Lazy-load mappings (load on first use)
- Support custom mapping overrides
- Handle unmapped checks gracefully (return empty list)
- Calculate coverage as: (passed_controls / total_controls) * 100

---

## Acceptance Criteria

- [ ] `ComplianceMapper` loads YAML mapping files
- [ ] `map_finding_to_controls()` returns correct control IDs
- [ ] `get_framework_coverage()` calculates pass/fail/coverage percentages
- [ ] SOC2, HIPAA, PCI-DSS mappings created with key controls
- [ ] Handles unmapped check IDs gracefully
- [ ] All tests pass: `pytest tests/test_compliance_mapper.py -v`
- [ ] Import works: `from parrot.tools.security.reports import ComplianceMapper`

---

## Test Specification

```python
# tests/test_compliance_mapper.py
import pytest
from pathlib import Path
from parrot.tools.security.reports.compliance_mapper import ComplianceMapper
from parrot.tools.security.models import (
    SecurityFinding,
    FindingSource,
    SeverityLevel,
    ComplianceFramework,
)


@pytest.fixture
def mapper():
    return ComplianceMapper()


@pytest.fixture
def prowler_finding():
    return SecurityFinding(
        id="test-1",
        source=FindingSource.PROWLER,
        severity=SeverityLevel.HIGH,
        title="S3 Bucket Public Access",
        check_id="s3_bucket_public_access",
    )


@pytest.fixture
def trivy_finding():
    return SecurityFinding(
        id="CVE-2023-1234",
        source=FindingSource.TRIVY,
        severity=SeverityLevel.CRITICAL,
        title="Critical CVE",
        resource_type="vulnerability",
    )


@pytest.fixture
def checkov_finding():
    return SecurityFinding(
        id="CKV_AWS_18",
        source=FindingSource.CHECKOV,
        severity=SeverityLevel.MEDIUM,
        title="S3 Logging Disabled",
        check_id="CKV_AWS_18",
    )


class TestComplianceMapperInit:
    def test_loads_mappings(self, mapper):
        """Mapper loads YAML mapping files."""
        assert mapper._mappings is not None
        # Should have at least one framework loaded
        assert len(mapper._mappings) > 0 or True  # Graceful if no files yet

    def test_custom_mappings_dir(self, tmp_path):
        """Accepts custom mappings directory."""
        mapper = ComplianceMapper(mappings_dir=str(tmp_path))
        assert mapper.mappings_dir == tmp_path


class TestMapFindingToControls:
    def test_map_prowler_finding_soc2(self, mapper, prowler_finding):
        """Maps Prowler finding to SOC2 controls."""
        controls = mapper.map_finding_to_controls(
            prowler_finding, ComplianceFramework.SOC2
        )
        # Should return list of control IDs (e.g., ["CC6.1", "CC6.6"])
        assert isinstance(controls, list)
        # If mapping exists, should have controls
        if controls:
            assert all(c.startswith("CC") for c in controls)

    def test_map_checkov_finding_soc2(self, mapper, checkov_finding):
        """Maps Checkov finding to SOC2 controls."""
        controls = mapper.map_finding_to_controls(
            checkov_finding, ComplianceFramework.SOC2
        )
        assert isinstance(controls, list)

    def test_map_trivy_finding_hipaa(self, mapper, trivy_finding):
        """Maps Trivy finding to HIPAA controls."""
        controls = mapper.map_finding_to_controls(
            trivy_finding, ComplianceFramework.HIPAA
        )
        assert isinstance(controls, list)

    def test_unmapped_check_returns_empty(self, mapper):
        """Unmapped check IDs return empty list."""
        finding = SecurityFinding(
            id="unknown",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.LOW,
            title="Unknown Check",
            check_id="nonexistent_check_12345",
        )
        controls = mapper.map_finding_to_controls(finding, ComplianceFramework.SOC2)
        assert controls == []


class TestGetFrameworkCoverage:
    def test_coverage_with_findings(self, mapper):
        """Calculates coverage from findings."""
        findings = [
            SecurityFinding(
                id=f"f{i}",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.PASS if i % 2 == 0 else SeverityLevel.HIGH,
                title=f"Finding {i}",
                check_id=f"check_{i}",
            )
            for i in range(4)
        ]
        coverage = mapper.get_framework_coverage(findings, ComplianceFramework.SOC2)

        assert "total_controls" in coverage
        assert "checked_controls" in coverage
        assert "passed_controls" in coverage
        assert "failed_controls" in coverage
        assert "coverage_pct" in coverage
        assert 0 <= coverage["coverage_pct"] <= 100

    def test_coverage_empty_findings(self, mapper):
        """Handles empty findings list."""
        coverage = mapper.get_framework_coverage([], ComplianceFramework.SOC2)
        assert coverage["checked_controls"] == 0


class TestGetControlDetails:
    def test_get_existing_control(self, mapper):
        """Gets details for existing control."""
        details = mapper.get_control_details("CC6.1", ComplianceFramework.SOC2)
        if details:  # If mapping file exists
            assert "name" in details
            assert "description" in details

    def test_get_nonexistent_control(self, mapper):
        """Returns None for nonexistent control."""
        details = mapper.get_control_details("INVALID_999", ComplianceFramework.SOC2)
        assert details is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 8.1
2. **Check dependencies** — TASK-032 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Create directory structure first**: `parrot/tools/security/reports/mappings/`
5. **Create YAML mapping files** with key controls (expand later)
6. **Implement** following the scope and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-044-compliance-mapper.md`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**:
- Created `ComplianceMapper` class with full mapping functionality
- Created YAML mapping files for SOC2, HIPAA, and PCI-DSS frameworks
- SOC2: 25+ controls mapped including CC1-CC9 trust service criteria
- HIPAA: 30+ controls covering 164.308, 164.310, 164.312, 164.314
- PCI-DSS v4.0: 40+ controls covering Requirements 1-12
- Added helper methods: `get_all_controls()`, `get_findings_by_control()`, `get_unmapped_findings()`
- 36 tests passing covering all functionality

**Deviations from spec**:
- Added extra helper methods for practical use cases
- Implemented lazy-loading of YAML files (loads on first use per framework)
