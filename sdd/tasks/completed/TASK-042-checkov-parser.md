# TASK-042: Checkov Parser

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-032, TASK-034
**Assigned-to**: claude-session

---

## Context

The Checkov Parser normalizes Checkov's JSON output (IaC misconfigurations) into the unified `SecurityFinding` model.

Reference: Spec Section 6.1 (Checkov Scanner Module).

---

## Scope

- Implement `parrot/tools/security/checkov/parser.py`
- Create `CheckovParser` extending `BaseParser`
- Map Checkov JSON fields to `SecurityFinding`:
  - `check_id` → `check_id`
  - `check_name` → `title`
  - `resource` → `resource`
  - `file_path:line` → `description`
  - `check_result.result` → severity (PASSED/FAILED)
  - `guideline` → `remediation`
- Handle both passed and failed checks
- Build `ScanSummary` with framework breakdown
- Create test fixture: `tests/fixtures/checkov_terraform_sample.json`
- Write comprehensive unit tests

**NOT in scope**:
- SecretsIaCToolkit (TASK-043)
- Executor logic (TASK-041)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/checkov/parser.py` | CREATE | CheckovParser class |
| `parrot/tools/security/checkov/__init__.py` | MODIFY | Add parser export |
| `tests/fixtures/checkov_terraform_sample.json` | CREATE | Sample Checkov output |
| `tests/test_checkov_parser.py` | CREATE | Unit tests |

---

## Implementation Notes

### Checkov JSON Structure

```json
{
  "check_type": "terraform",
  "results": {
    "passed_checks": [
      {
        "check_id": "CKV_AWS_18",
        "check_name": "Ensure the S3 bucket has access logging enabled",
        "check_result": {"result": "PASSED"},
        "resource": "aws_s3_bucket.example",
        "file_path": "/main.tf",
        "file_line_range": [10, 20],
        "guideline": "https://docs.bridgecrew.io/docs/s3_13-enable-logging"
      }
    ],
    "failed_checks": [
      {
        "check_id": "CKV_AWS_21",
        "check_name": "Ensure the S3 bucket has versioning enabled",
        "check_result": {"result": "FAILED"},
        "resource": "aws_s3_bucket.example",
        "file_path": "/main.tf",
        "file_line_range": [10, 20],
        "evaluations": {"default": {"reason": "versioning not enabled"}},
        "guideline": "https://docs.bridgecrew.io/docs/s3_16-enable-versioning"
      }
    ],
    "skipped_checks": []
  },
  "summary": {
    "passed": 10,
    "failed": 3,
    "skipped": 1,
    "parsing_errors": 0
  }
}
```

### Severity Mapping

Checkov doesn't provide severity in output, so we derive it:
- **FAILED** checks → `SeverityLevel.MEDIUM` (default) or based on check_id patterns
- **PASSED** checks → `SeverityLevel.PASS`
- **SKIPPED** checks → `SeverityLevel.INFO`

Some high-severity check patterns:
- `CKV_AWS_*` with IAM/root/MFA → HIGH
- `CKV_AWS_*` with encryption/KMS → HIGH
- Secrets-related → CRITICAL

### Key Constraints

- Handle both passed and failed checks arrays
- Include file path and line numbers in description
- Preserve guideline URL in remediation field
- Support multiple check_types in single output (terraform, cloudformation, etc.)
- Calculate accurate pass/fail counts in summary

---

## Acceptance Criteria

- [ ] `CheckovParser.parse()` handles Checkov JSON output correctly
- [ ] Both passed and failed checks are normalized
- [ ] Severity derived appropriately (PASS for passed, MEDIUM+ for failed)
- [ ] File path and line range included in finding
- [ ] Guideline URL preserved in remediation
- [ ] `ScanSummary` includes accurate pass/fail counts
- [ ] All tests pass: `pytest tests/test_checkov_parser.py -v`
- [ ] Test fixture created: `tests/fixtures/checkov_terraform_sample.json`

---

## Test Specification

```python
# tests/test_checkov_parser.py
import pytest
import json
from pathlib import Path
from parrot.tools.security.checkov.parser import CheckovParser
from parrot.tools.security.models import (
    SeverityLevel,
    FindingSource,
)


@pytest.fixture
def parser():
    return CheckovParser()


@pytest.fixture
def sample_failed_check():
    return {
        "check_id": "CKV_AWS_21",
        "check_name": "Ensure the S3 bucket has versioning enabled",
        "check_result": {"result": "FAILED"},
        "resource": "aws_s3_bucket.data_bucket",
        "file_path": "/terraform/main.tf",
        "file_line_range": [15, 25],
        "evaluations": {"default": {"reason": "versioning not enabled"}},
        "guideline": "https://docs.bridgecrew.io/docs/s3_16-enable-versioning",
    }


@pytest.fixture
def sample_passed_check():
    return {
        "check_id": "CKV_AWS_18",
        "check_name": "Ensure the S3 bucket has access logging enabled",
        "check_result": {"result": "PASSED"},
        "resource": "aws_s3_bucket.logs_bucket",
        "file_path": "/terraform/main.tf",
        "file_line_range": [30, 45],
        "guideline": "https://docs.bridgecrew.io/docs/s3_13-enable-logging",
    }


@pytest.fixture
def full_checkov_output(sample_failed_check, sample_passed_check):
    return {
        "check_type": "terraform",
        "results": {
            "passed_checks": [sample_passed_check],
            "failed_checks": [sample_failed_check],
            "skipped_checks": [],
        },
        "summary": {
            "passed": 1,
            "failed": 1,
            "skipped": 0,
            "parsing_errors": 0,
        },
    }


class TestCheckovParserNormalization:
    def test_normalize_failed_check(self, parser, sample_failed_check):
        """Failed check is normalized correctly."""
        finding = parser.normalize_finding(sample_failed_check)

        assert finding.source == FindingSource.CHECKOV
        assert finding.severity in [SeverityLevel.MEDIUM, SeverityLevel.HIGH]
        assert finding.check_id == "CKV_AWS_21"
        assert finding.title == "Ensure the S3 bucket has versioning enabled"
        assert finding.resource == "aws_s3_bucket.data_bucket"
        assert "/terraform/main.tf" in finding.description
        assert "15" in finding.description  # line number
        assert "versioning" in finding.remediation.lower() or "bridgecrew" in finding.remediation

    def test_normalize_passed_check(self, parser, sample_passed_check):
        """Passed check gets PASS severity."""
        finding = parser.normalize_finding(sample_passed_check, passed=True)

        assert finding.severity == SeverityLevel.PASS
        assert finding.check_id == "CKV_AWS_18"

    def test_normalize_includes_raw(self, parser, sample_failed_check):
        """Raw check data is preserved."""
        finding = parser.normalize_finding(sample_failed_check)
        assert finding.raw == sample_failed_check


class TestCheckovParserSeverityDerivation:
    def test_iam_check_is_high(self, parser):
        """IAM-related checks are HIGH severity."""
        raw = {
            "check_id": "CKV_AWS_40",
            "check_name": "Ensure IAM password policy requires minimum length",
            "check_result": {"result": "FAILED"},
            "resource": "aws_iam_account_password_policy.strict",
            "file_path": "/iam.tf",
            "file_line_range": [1, 10],
        }
        finding = parser.normalize_finding(raw)
        assert finding.severity == SeverityLevel.HIGH

    def test_encryption_check_is_high(self, parser):
        """Encryption-related checks are HIGH severity."""
        raw = {
            "check_id": "CKV_AWS_19",
            "check_name": "Ensure S3 bucket has encryption enabled",
            "check_result": {"result": "FAILED"},
            "resource": "aws_s3_bucket.unencrypted",
            "file_path": "/s3.tf",
            "file_line_range": [1, 10],
        }
        finding = parser.normalize_finding(raw)
        assert finding.severity == SeverityLevel.HIGH


class TestCheckovParserParse:
    def test_parse_full_output(self, parser, full_checkov_output):
        """Parses complete Checkov output."""
        raw = json.dumps(full_checkov_output)
        result = parser.parse(raw)

        assert len(result.findings) == 2
        assert result.summary.total_findings == 2
        assert result.summary.pass_count == 1

    def test_parse_failed_only_compact(self, parser, sample_failed_check):
        """Parses compact output (failed only)."""
        output = {
            "check_type": "terraform",
            "results": {
                "passed_checks": [],
                "failed_checks": [sample_failed_check],
                "skipped_checks": [],
            },
            "summary": {"passed": 0, "failed": 1, "skipped": 0},
        }
        result = parser.parse(json.dumps(output))
        assert len(result.findings) == 1
        assert result.findings[0].severity != SeverityLevel.PASS

    def test_parse_empty_results(self, parser):
        """Handles empty scan results."""
        output = {
            "check_type": "terraform",
            "results": {
                "passed_checks": [],
                "failed_checks": [],
                "skipped_checks": [],
            },
            "summary": {"passed": 0, "failed": 0, "skipped": 0},
        }
        result = parser.parse(json.dumps(output))
        assert len(result.findings) == 0

    def test_parse_multiple_frameworks(self, parser, sample_failed_check):
        """Handles output with multiple check_types."""
        # Checkov can scan multiple frameworks at once
        output = {
            "check_type": "terraform",
            "results": {
                "passed_checks": [],
                "failed_checks": [sample_failed_check],
                "skipped_checks": [],
            },
            "summary": {"passed": 0, "failed": 1, "skipped": 0},
        }
        result = parser.parse(json.dumps(output))
        assert result.findings[0].resource_type == "terraform"


class TestCheckovParserFixture:
    def test_parse_fixture_file(self, parser):
        """Parses the sample fixture file."""
        fixture_path = Path(__file__).parent / "fixtures" / "checkov_terraform_sample.json"
        if fixture_path.exists():
            raw = fixture_path.read_text()
            result = parser.parse(raw)
            assert result.summary.total_findings >= 0
```

### Fixture File

Create `tests/fixtures/checkov_terraform_sample.json`:

```json
{
  "check_type": "terraform",
  "results": {
    "passed_checks": [
      {
        "check_id": "CKV_AWS_18",
        "check_name": "Ensure the S3 bucket has access logging enabled",
        "check_result": {"result": "PASSED"},
        "resource": "aws_s3_bucket.logs",
        "file_path": "/terraform/main.tf",
        "file_line_range": [1, 15],
        "guideline": "https://docs.bridgecrew.io/docs/s3_13-enable-logging"
      }
    ],
    "failed_checks": [
      {
        "check_id": "CKV_AWS_21",
        "check_name": "Ensure the S3 bucket has versioning enabled",
        "check_result": {"result": "FAILED"},
        "resource": "aws_s3_bucket.data",
        "file_path": "/terraform/main.tf",
        "file_line_range": [20, 35],
        "evaluations": {"default": {"reason": "versioning not enabled"}},
        "guideline": "https://docs.bridgecrew.io/docs/s3_16-enable-versioning"
      },
      {
        "check_id": "CKV_AWS_19",
        "check_name": "Ensure the S3 bucket has encryption enabled",
        "check_result": {"result": "FAILED"},
        "resource": "aws_s3_bucket.data",
        "file_path": "/terraform/main.tf",
        "file_line_range": [20, 35],
        "guideline": "https://docs.bridgecrew.io/docs/s3_14-enable-encryption"
      },
      {
        "check_id": "CKV_AWS_40",
        "check_name": "Ensure IAM password policy requires minimum length of 14",
        "check_result": {"result": "FAILED"},
        "resource": "aws_iam_account_password_policy.strict",
        "file_path": "/terraform/iam.tf",
        "file_line_range": [1, 12],
        "guideline": "https://docs.bridgecrew.io/docs/iam_7-password-length"
      }
    ],
    "skipped_checks": [
      {
        "check_id": "CKV_AWS_1",
        "check_name": "Ensure CloudTrail is enabled",
        "check_result": {"result": "SKIPPED", "suppress_comment": "Not applicable"},
        "resource": "aws_cloudtrail.main",
        "file_path": "/terraform/cloudtrail.tf",
        "file_line_range": [1, 5]
      }
    ]
  },
  "summary": {
    "passed": 1,
    "failed": 3,
    "skipped": 1,
    "parsing_errors": 0
  }
}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 6
2. **Check dependencies** — TASK-032, TASK-034 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Create fixture file first**
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-042-checkov-parser.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**: Implemented CheckovParser with pattern-based severity derivation. Handles passed, failed, and skipped checks. Created fixture file. All 30 tests pass.

**Deviations from spec**: none
