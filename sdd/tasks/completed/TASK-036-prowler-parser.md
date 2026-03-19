# TASK-036: Prowler Parser

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-032, TASK-034
**Assigned-to**: claude-session

---

## Context

The Prowler Parser normalizes Prowler's JSON-OCSF output into the unified `SecurityFinding` model. This enables cross-tool aggregation with Trivy and Checkov findings.

Reference: Spec Section 4.1.3 (Parser).

---

## Scope

- Implement `parrot/tools/security/prowler/parser.py`
- Create `ProwlerParser` extending `BaseParser`
- Map Prowler JSON-OCSF fields to `SecurityFinding`:
  - `finding_info.uid` → `check_id`
  - `finding_info.title` → `title`
  - `finding_info.desc` → `description`
  - `severity_id` / `severity` → `severity` (normalized)
  - `status` → `PASS`/`FAIL`
  - `resources[0].uid` → `resource`
  - `resources[0].region` → `region`
  - `remediation.desc` → `remediation`
- Build `ScanSummary` with severity counts and service breakdown
- Write comprehensive unit tests with fixture data
- Create test fixture: `tests/fixtures/prowler_ocsf_sample.json`

**NOT in scope**:
- CloudPostureToolkit (TASK-037)
- Executor logic (TASK-035)
- Other scanner parsers

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/prowler/parser.py` | CREATE | ProwlerParser class |
| `parrot/tools/security/prowler/__init__.py` | MODIFY | Add parser export |
| `tests/fixtures/prowler_ocsf_sample.json` | CREATE | Sample Prowler output |
| `tests/test_prowler_parser.py` | CREATE | Unit tests |

---

## Implementation Notes

### Prowler JSON-OCSF Structure

```json
{
  "finding_info": {
    "uid": "prowler-aws-s3_bucket_public_access",
    "title": "S3 Bucket has Public Access",
    "desc": "Check if S3 buckets have public access..."
  },
  "severity_id": 3,
  "severity": "High",
  "status": "FAIL",
  "resources": [
    {
      "uid": "arn:aws:s3:::my-bucket",
      "region": "us-east-1",
      "type": "AwsS3Bucket"
    }
  ],
  "unmapped": {
    "check_type": ["hipaa", "soc2"]
  },
  "remediation": {
    "desc": "Enable S3 Block Public Access..."
  }
}
```

### Severity Mapping

```python
SEVERITY_MAP = {
    "critical": SeverityLevel.CRITICAL,
    "high": SeverityLevel.HIGH,
    "medium": SeverityLevel.MEDIUM,
    "low": SeverityLevel.LOW,
    "informational": SeverityLevel.INFO,
}

STATUS_MAP = {
    "PASS": SeverityLevel.PASS,
    "FAIL": None,  # use severity
    "MANUAL": SeverityLevel.INFO,
}
```

### Key Constraints

- Handle both JSON array and newline-delimited JSON (NDJSON)
- Extract compliance tags from `unmapped.check_type`
- Preserve original finding in `raw` field
- Build accurate severity counts in summary
- Handle missing optional fields gracefully

### References in Codebase

- `parrot/tools/cloudsploit/parser.py` — similar pattern

---

## Acceptance Criteria

- [x] `ProwlerParser.parse()` handles JSON array and NDJSON formats
- [x] `ProwlerParser.normalize_finding()` maps all OCSF fields correctly
- [x] Severity normalization works for all Prowler severity levels
- [x] PASS/FAIL status is handled correctly
- [x] Compliance tags extracted from `unmapped.check_type`
- [x] `ScanSummary` includes accurate counts and service breakdown
- [x] All tests pass: `pytest tests/test_prowler_parser.py -v`
- [x] Test fixture created: `tests/fixtures/prowler_ocsf_sample.json`

---

## Test Specification

```python
# tests/test_prowler_parser.py
import pytest
import json
from pathlib import Path
from parrot.tools.security.prowler.parser import ProwlerParser
from parrot.tools.security.models import (
    SeverityLevel,
    FindingSource,
    CloudProvider,
)


@pytest.fixture
def parser():
    return ProwlerParser()


@pytest.fixture
def sample_ocsf_finding():
    """Single Prowler OCSF finding."""
    return {
        "finding_info": {
            "uid": "prowler-aws-s3_bucket_public_access-123",
            "title": "S3 Bucket has Public Access Block disabled",
            "desc": "Ensure S3 buckets have public access block enabled",
        },
        "severity_id": 3,
        "severity": "High",
        "status": "FAIL",
        "resources": [
            {
                "uid": "arn:aws:s3:::test-bucket-123",
                "region": "us-east-1",
                "type": "AwsS3Bucket",
            }
        ],
        "unmapped": {
            "check_type": ["hipaa", "soc2", "cis_1.5_aws"],
            "service_name": "s3",
        },
        "remediation": {
            "desc": "Enable S3 Block Public Access settings",
        },
    }


@pytest.fixture
def sample_pass_finding():
    """Prowler finding with PASS status."""
    return {
        "finding_info": {
            "uid": "prowler-aws-iam_root_mfa-456",
            "title": "Root account has MFA enabled",
            "desc": "Check if root account has MFA",
        },
        "severity_id": 4,
        "severity": "Critical",
        "status": "PASS",
        "resources": [
            {
                "uid": "arn:aws:iam::123456789012:root",
                "region": "global",
                "type": "AwsIamUser",
            }
        ],
        "unmapped": {"service_name": "iam"},
        "remediation": {"desc": "N/A - already compliant"},
    }


class TestProwlerParserNormalization:
    def test_normalize_fail_finding(self, parser, sample_ocsf_finding):
        """FAIL finding is normalized correctly."""
        finding = parser.normalize_finding(sample_ocsf_finding)

        assert finding.source == FindingSource.PROWLER
        assert finding.severity == SeverityLevel.HIGH
        assert finding.title == "S3 Bucket has Public Access Block disabled"
        assert finding.resource == "arn:aws:s3:::test-bucket-123"
        assert finding.region == "us-east-1"
        assert finding.service == "s3"
        assert "hipaa" in finding.compliance_tags
        assert "soc2" in finding.compliance_tags
        assert finding.remediation == "Enable S3 Block Public Access settings"
        assert finding.raw == sample_ocsf_finding

    def test_normalize_pass_finding(self, parser, sample_pass_finding):
        """PASS finding gets PASS severity."""
        finding = parser.normalize_finding(sample_pass_finding)

        assert finding.severity == SeverityLevel.PASS
        assert finding.title == "Root account has MFA enabled"

    def test_normalize_missing_optional_fields(self, parser):
        """Handles missing optional fields gracefully."""
        minimal = {
            "finding_info": {"uid": "test-123", "title": "Test"},
            "severity": "Medium",
            "status": "FAIL",
            "resources": [],
        }
        finding = parser.normalize_finding(minimal)

        assert finding.id is not None
        assert finding.resource is None
        assert finding.region == "global"
        assert finding.compliance_tags == []


class TestProwlerParserSeverityMapping:
    @pytest.mark.parametrize("prowler_severity,expected", [
        ("critical", SeverityLevel.CRITICAL),
        ("Critical", SeverityLevel.CRITICAL),
        ("high", SeverityLevel.HIGH),
        ("High", SeverityLevel.HIGH),
        ("medium", SeverityLevel.MEDIUM),
        ("Medium", SeverityLevel.MEDIUM),
        ("low", SeverityLevel.LOW),
        ("informational", SeverityLevel.INFO),
    ])
    def test_severity_mapping(self, parser, prowler_severity, expected):
        """Prowler severities map to unified levels."""
        raw = {
            "finding_info": {"uid": "test", "title": "Test"},
            "severity": prowler_severity,
            "status": "FAIL",
            "resources": [],
        }
        finding = parser.normalize_finding(raw)
        assert finding.severity == expected


class TestProwlerParserParse:
    def test_parse_json_array(self, parser, sample_ocsf_finding, sample_pass_finding):
        """Parses JSON array format."""
        raw = json.dumps([sample_ocsf_finding, sample_pass_finding])
        result = parser.parse(raw)

        assert len(result.findings) == 2
        assert result.summary.total_findings == 2
        assert result.summary.high_count == 1
        assert result.summary.pass_count == 1

    def test_parse_ndjson(self, parser, sample_ocsf_finding, sample_pass_finding):
        """Parses newline-delimited JSON format."""
        raw = json.dumps(sample_ocsf_finding) + "\n" + json.dumps(sample_pass_finding)
        result = parser.parse(raw)

        assert len(result.findings) == 2

    def test_parse_empty_output(self, parser):
        """Handles empty scanner output."""
        result = parser.parse("[]")
        assert len(result.findings) == 0
        assert result.summary.total_findings == 0

    def test_summary_severity_counts(self, parser):
        """Summary has accurate severity counts."""
        findings = [
            {"finding_info": {"uid": f"c{i}", "title": "T"}, "severity": "Critical", "status": "FAIL", "resources": []}
            for i in range(3)
        ] + [
            {"finding_info": {"uid": f"h{i}", "title": "T"}, "severity": "High", "status": "FAIL", "resources": []}
            for i in range(2)
        ] + [
            {"finding_info": {"uid": "p1", "title": "T"}, "severity": "Low", "status": "PASS", "resources": []}
        ]
        raw = json.dumps(findings)
        result = parser.parse(raw)

        assert result.summary.critical_count == 3
        assert result.summary.high_count == 2
        assert result.summary.pass_count == 1


class TestProwlerParserFixture:
    def test_parse_fixture_file(self, parser):
        """Parses the sample fixture file."""
        fixture_path = Path(__file__).parent / "fixtures" / "prowler_ocsf_sample.json"
        if fixture_path.exists():
            raw = fixture_path.read_text()
            result = parser.parse(raw)
            assert result.summary.total_findings > 0
```

### Fixture File

Create `tests/fixtures/prowler_ocsf_sample.json`:

```json
[
  {
    "finding_info": {
      "uid": "prowler-aws-s3_bucket_public_access-bucket1",
      "title": "S3 Bucket has Public Access Block disabled",
      "desc": "Ensure S3 buckets have public access block enabled to prevent unauthorized access."
    },
    "severity_id": 3,
    "severity": "High",
    "status": "FAIL",
    "resources": [
      {
        "uid": "arn:aws:s3:::example-bucket-1",
        "region": "us-east-1",
        "type": "AwsS3Bucket"
      }
    ],
    "unmapped": {
      "check_type": ["hipaa", "soc2", "cis_1.5_aws"],
      "service_name": "s3"
    },
    "remediation": {
      "desc": "Enable S3 Block Public Access settings for the bucket."
    }
  },
  {
    "finding_info": {
      "uid": "prowler-aws-iam_root_mfa-root",
      "title": "Root account has MFA enabled",
      "desc": "Check if root account has MFA enabled."
    },
    "severity_id": 4,
    "severity": "Critical",
    "status": "PASS",
    "resources": [
      {
        "uid": "arn:aws:iam::123456789012:root",
        "region": "global",
        "type": "AwsIamUser"
      }
    ],
    "unmapped": {
      "service_name": "iam"
    },
    "remediation": {
      "desc": "N/A - already compliant"
    }
  },
  {
    "finding_info": {
      "uid": "prowler-aws-ec2_instance_public_ip-i123",
      "title": "EC2 instance has public IP",
      "desc": "EC2 instances should not have public IP addresses unless necessary."
    },
    "severity_id": 2,
    "severity": "Medium",
    "status": "FAIL",
    "resources": [
      {
        "uid": "arn:aws:ec2:us-west-2:123456789012:instance/i-1234567890abcdef0",
        "region": "us-west-2",
        "type": "AwsEc2Instance"
      }
    ],
    "unmapped": {
      "check_type": ["pci_dss"],
      "service_name": "ec2"
    },
    "remediation": {
      "desc": "Remove public IP or use a NAT gateway."
    }
  }
]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 4.1.3
2. **Check dependencies** — TASK-032, TASK-034 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Create fixture file first** — needed for tests
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-036-prowler-parser.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**:
- Created `parrot/tools/security/prowler/parser.py` with ProwlerParser class
- Supports JSON array and NDJSON formats
- Maps all OCSF fields: finding_info, severity, status, resources, unmapped, remediation
- Severity mapping: critical, high, medium, low, informational, info
- PASS status overrides severity to SeverityLevel.PASS
- Extracts compliance tags from unmapped.check_type (handles string or list)
- Detects cloud provider from resource ARN or type
- Extracts check_id from finding UID
- Created test fixture with 3 sample findings (s3, iam, ec2)
- Created 30 unit tests covering all functionality

**Deviations from spec**: Added provider detection from resource ARN/type; enhanced check_id extraction
