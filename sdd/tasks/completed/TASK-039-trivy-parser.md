# TASK-039: Trivy Parser

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-032, TASK-034
**Assigned-to**: unassigned

---

## Context

The Trivy Parser normalizes Trivy's JSON output (vulnerabilities, secrets, misconfigs) into the unified `SecurityFinding` model.

Reference: Spec Section 5.1 (Trivy Scanner Module).

---

## Scope

- Implement `parrot/tools/security/trivy/parser.py`
- Create `TrivyParser` extending `BaseParser`
- Handle multiple result types:
  - Vulnerabilities (CVEs with package info)
  - Secrets (exposed credentials)
  - Misconfigurations (IaC issues)
- Map Trivy JSON fields to `SecurityFinding`
- Build `ScanSummary` with severity counts
- Create test fixture: `tests/fixtures/trivy_image_sample.json`
- Write comprehensive unit tests

**NOT in scope**:
- ContainerSecurityToolkit (TASK-040)
- Executor logic (TASK-038)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/trivy/parser.py` | CREATE | TrivyParser class |
| `parrot/tools/security/trivy/__init__.py` | MODIFY | Add parser export |
| `tests/fixtures/trivy_image_sample.json` | CREATE | Sample Trivy output |
| `tests/test_trivy_parser.py` | CREATE | Unit tests |

---

## Implementation Notes

### Trivy JSON Structure (Image Scan)

```json
{
  "SchemaVersion": 2,
  "ArtifactName": "nginx:latest",
  "ArtifactType": "container_image",
  "Results": [
    {
      "Target": "nginx:latest (debian 11.6)",
      "Class": "os-pkgs",
      "Type": "debian",
      "Vulnerabilities": [
        {
          "VulnerabilityID": "CVE-2023-1234",
          "PkgID": "libssl1.1@1.1.1n-0+deb11u3",
          "PkgName": "libssl1.1",
          "InstalledVersion": "1.1.1n-0+deb11u3",
          "FixedVersion": "1.1.1n-0+deb11u4",
          "Severity": "HIGH",
          "Title": "OpenSSL vulnerability",
          "Description": "A vulnerability in OpenSSL...",
          "References": ["https://nvd.nist.gov/..."]
        }
      ],
      "Secrets": [
        {
          "RuleID": "aws-access-key-id",
          "Category": "AWS",
          "Severity": "CRITICAL",
          "Title": "AWS Access Key ID",
          "Match": "AKIA..."
        }
      ],
      "Misconfigurations": [
        {
          "Type": "Dockerfile",
          "ID": "DS002",
          "Title": "Root user",
          "Description": "Running as root...",
          "Severity": "HIGH",
          "Resolution": "Use USER directive"
        }
      ]
    }
  ]
}
```

### Mapping Strategy

**Vulnerabilities:**
- `VulnerabilityID` → `check_id`
- `Title` → `title`
- `Description` → `description`
- `Severity` → `severity` (direct mapping)
- `PkgName@InstalledVersion` → `resource`
- `"vulnerability"` → `resource_type`
- `References` → part of `remediation`

**Secrets:**
- `RuleID` → `check_id`
- `Title` → `title`
- `Match` (masked) → `description`
- `Severity` → `severity`
- `"secret"` → `resource_type`

**Misconfigurations:**
- `ID` → `check_id`
- `Title` → `title`
- `Description` → `description`
- `Severity` → `severity`
- `Resolution` → `remediation`
- `Type` → `resource_type`

### Key Constraints

- Handle empty Results array gracefully
- Mask secret values in findings (show only first/last chars)
- Support all three finding types in single parse
- Calculate accurate severity counts across all result types

---

## Acceptance Criteria

- [ ] `TrivyParser.parse()` handles all Trivy JSON result types
- [ ] Vulnerabilities, Secrets, and Misconfigurations all normalized correctly
- [ ] Secret values are masked in findings
- [ ] `ScanSummary` includes accurate counts across all finding types
- [ ] All tests pass: `pytest tests/test_trivy_parser.py -v`
- [ ] Test fixture created: `tests/fixtures/trivy_image_sample.json`

---

## Test Specification

```python
# tests/test_trivy_parser.py
import pytest
import json
from pathlib import Path
from parrot.tools.security.trivy.parser import TrivyParser
from parrot.tools.security.models import (
    SeverityLevel,
    FindingSource,
)


@pytest.fixture
def parser():
    return TrivyParser()


@pytest.fixture
def sample_vulnerability():
    return {
        "VulnerabilityID": "CVE-2023-44487",
        "PkgID": "golang.org/x/net@v0.7.0",
        "PkgName": "golang.org/x/net",
        "InstalledVersion": "v0.7.0",
        "FixedVersion": "v0.17.0",
        "Severity": "HIGH",
        "Title": "HTTP/2 Rapid Reset Attack",
        "Description": "The HTTP/2 protocol allows a denial of service...",
        "References": [
            "https://nvd.nist.gov/vuln/detail/CVE-2023-44487",
        ],
    }


@pytest.fixture
def sample_secret():
    return {
        "RuleID": "aws-access-key-id",
        "Category": "AWS",
        "Severity": "CRITICAL",
        "Title": "AWS Access Key ID",
        "Match": "AKIAIOSFODNN7EXAMPLE",
    }


@pytest.fixture
def sample_misconfig():
    return {
        "Type": "Dockerfile",
        "ID": "DS002",
        "Title": "Image user should not be 'root'",
        "Description": "Running containers as root is a security risk.",
        "Severity": "HIGH",
        "Resolution": "Add 'USER nonroot' to Dockerfile",
    }


@pytest.fixture
def full_trivy_output(sample_vulnerability, sample_secret, sample_misconfig):
    return {
        "SchemaVersion": 2,
        "ArtifactName": "myapp:v1.0",
        "ArtifactType": "container_image",
        "Results": [
            {
                "Target": "myapp:v1.0",
                "Class": "os-pkgs",
                "Type": "debian",
                "Vulnerabilities": [sample_vulnerability],
                "Secrets": [sample_secret],
                "Misconfigurations": [sample_misconfig],
            }
        ],
    }


class TestTrivyParserNormalization:
    def test_normalize_vulnerability(self, parser, sample_vulnerability):
        """Vulnerability is normalized correctly."""
        finding = parser.normalize_vulnerability(sample_vulnerability)

        assert finding.source == FindingSource.TRIVY
        assert finding.severity == SeverityLevel.HIGH
        assert finding.check_id == "CVE-2023-44487"
        assert finding.title == "HTTP/2 Rapid Reset Attack"
        assert "golang.org/x/net" in finding.resource
        assert finding.resource_type == "vulnerability"

    def test_normalize_secret(self, parser, sample_secret):
        """Secret is normalized with masked value."""
        finding = parser.normalize_secret(sample_secret)

        assert finding.source == FindingSource.TRIVY
        assert finding.severity == SeverityLevel.CRITICAL
        assert finding.check_id == "aws-access-key-id"
        assert finding.resource_type == "secret"
        # Value should be masked
        assert "AKIAIOSFODNN7EXAMPLE" not in finding.description
        assert "***" in finding.description or "AKIA" in finding.description

    def test_normalize_misconfig(self, parser, sample_misconfig):
        """Misconfiguration is normalized correctly."""
        finding = parser.normalize_misconfiguration(sample_misconfig)

        assert finding.source == FindingSource.TRIVY
        assert finding.severity == SeverityLevel.HIGH
        assert finding.check_id == "DS002"
        assert finding.resource_type == "Dockerfile"
        assert "USER nonroot" in finding.remediation


class TestTrivyParserSeverityMapping:
    @pytest.mark.parametrize("trivy_severity,expected", [
        ("CRITICAL", SeverityLevel.CRITICAL),
        ("HIGH", SeverityLevel.HIGH),
        ("MEDIUM", SeverityLevel.MEDIUM),
        ("LOW", SeverityLevel.LOW),
        ("UNKNOWN", SeverityLevel.UNKNOWN),
    ])
    def test_severity_mapping(self, parser, trivy_severity, expected):
        """Trivy severities map correctly."""
        raw = {
            "VulnerabilityID": "CVE-TEST",
            "PkgName": "test",
            "Severity": trivy_severity,
            "Title": "Test",
        }
        finding = parser.normalize_vulnerability(raw)
        assert finding.severity == expected


class TestTrivyParserParse:
    def test_parse_full_output(self, parser, full_trivy_output):
        """Parses complete Trivy output with all finding types."""
        raw = json.dumps(full_trivy_output)
        result = parser.parse(raw)

        assert len(result.findings) == 3  # 1 vuln + 1 secret + 1 misconfig
        assert result.summary.total_findings == 3
        assert result.summary.critical_count == 1  # secret
        assert result.summary.high_count == 2  # vuln + misconfig

    def test_parse_empty_results(self, parser):
        """Handles empty Results array."""
        empty = {
            "SchemaVersion": 2,
            "ArtifactName": "clean-image:latest",
            "Results": [],
        }
        result = parser.parse(json.dumps(empty))
        assert len(result.findings) == 0
        assert result.summary.total_findings == 0

    def test_parse_vulnerabilities_only(self, parser, sample_vulnerability):
        """Parses output with only vulnerabilities."""
        output = {
            "SchemaVersion": 2,
            "ArtifactName": "test",
            "Results": [
                {
                    "Target": "test",
                    "Vulnerabilities": [sample_vulnerability],
                }
            ],
        }
        result = parser.parse(json.dumps(output))
        assert len(result.findings) == 1
        assert result.findings[0].check_id == "CVE-2023-44487"

    def test_parse_secrets_only(self, parser, sample_secret):
        """Parses output with only secrets."""
        output = {
            "SchemaVersion": 2,
            "ArtifactName": "test",
            "Results": [
                {
                    "Target": "test",
                    "Secrets": [sample_secret],
                }
            ],
        }
        result = parser.parse(json.dumps(output))
        assert len(result.findings) == 1
        assert result.findings[0].resource_type == "secret"

    def test_parse_multiple_results(self, parser, sample_vulnerability):
        """Handles multiple Results entries."""
        output = {
            "SchemaVersion": 2,
            "ArtifactName": "test",
            "Results": [
                {"Target": "layer1", "Vulnerabilities": [sample_vulnerability]},
                {"Target": "layer2", "Vulnerabilities": [sample_vulnerability]},
            ],
        }
        result = parser.parse(json.dumps(output))
        assert len(result.findings) == 2


class TestTrivyParserFixture:
    def test_parse_fixture_file(self, parser):
        """Parses the sample fixture file."""
        fixture_path = Path(__file__).parent / "fixtures" / "trivy_image_sample.json"
        if fixture_path.exists():
            raw = fixture_path.read_text()
            result = parser.parse(raw)
            assert result.summary.total_findings >= 0
```

### Fixture File

Create `tests/fixtures/trivy_image_sample.json`:

```json
{
  "SchemaVersion": 2,
  "ArtifactName": "nginx:1.21",
  "ArtifactType": "container_image",
  "Metadata": {
    "OS": {"Family": "debian", "Name": "11.6"},
    "ImageID": "sha256:abc123"
  },
  "Results": [
    {
      "Target": "nginx:1.21 (debian 11.6)",
      "Class": "os-pkgs",
      "Type": "debian",
      "Vulnerabilities": [
        {
          "VulnerabilityID": "CVE-2023-44487",
          "PkgID": "libnghttp2-14@1.43.0-1",
          "PkgName": "libnghttp2-14",
          "InstalledVersion": "1.43.0-1",
          "FixedVersion": "1.43.0-1+deb11u1",
          "Severity": "HIGH",
          "Title": "HTTP/2 Rapid Reset Attack",
          "Description": "The HTTP/2 protocol allows denial of service.",
          "References": ["https://nvd.nist.gov/vuln/detail/CVE-2023-44487"]
        },
        {
          "VulnerabilityID": "CVE-2023-38545",
          "PkgID": "libcurl4@7.74.0-1.3+deb11u7",
          "PkgName": "libcurl4",
          "InstalledVersion": "7.74.0-1.3+deb11u7",
          "FixedVersion": "7.74.0-1.3+deb11u10",
          "Severity": "CRITICAL",
          "Title": "curl SOCKS5 heap buffer overflow",
          "Description": "A heap buffer overflow in curl's SOCKS5 proxy handshake.",
          "References": ["https://curl.se/docs/CVE-2023-38545.html"]
        }
      ]
    },
    {
      "Target": "Dockerfile",
      "Class": "config",
      "Type": "dockerfile",
      "Misconfigurations": [
        {
          "Type": "Dockerfile",
          "ID": "DS002",
          "AVDID": "AVD-DS-0002",
          "Title": "Image user should not be 'root'",
          "Description": "Running containers with root privileges is insecure.",
          "Severity": "HIGH",
          "Resolution": "Add USER directive to run as non-root"
        }
      ]
    }
  ]
}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 5
2. **Check dependencies** — TASK-032, TASK-034 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Create fixture file first**
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-039-trivy-parser.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**:
- Created `parrot/tools/security/trivy/parser.py` with TrivyParser class
- Handles all three finding types: Vulnerabilities, Secrets, Misconfigurations
- Secrets are properly masked (shows first 4 and last 4 chars for long values)
- Severity mapping: CRITICAL, HIGH, MEDIUM, LOW, UNKNOWN
- ScanSummary uses `CloudProvider.LOCAL` for Trivy scans
- Created test fixture: `tests/fixtures/trivy_image_sample.json`
- 33 tests passing
- Exports added to `parrot/tools/security/trivy/__init__.py` and `parrot/tools/security/__init__.py`

**Deviations from spec**: Used `CloudProvider.LOCAL` instead of `None` for provider field since ScanSummary.provider is required
