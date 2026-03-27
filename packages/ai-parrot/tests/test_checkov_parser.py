"""Unit tests for the Checkov parser."""

import json
from pathlib import Path

import pytest

from parrot.tools.security.checkov.parser import CheckovParser
from parrot.tools.security.models import (
    FindingSource,
    SeverityLevel,
)


@pytest.fixture
def parser():
    """Create a parser instance for testing."""
    return CheckovParser()


@pytest.fixture
def sample_failed_check():
    """Single Checkov failed check."""
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
    """Single Checkov passed check."""
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
def sample_skipped_check():
    """Single Checkov skipped check."""
    return {
        "check_id": "CKV_AWS_1",
        "check_name": "Ensure CloudTrail is enabled",
        "check_result": {"result": "SKIPPED", "suppress_comment": "Not applicable"},
        "resource": "aws_cloudtrail.main",
        "file_path": "/terraform/cloudtrail.tf",
        "file_line_range": [1, 5],
    }


@pytest.fixture
def full_checkov_output(sample_failed_check, sample_passed_check):
    """Complete Checkov output with mixed check types."""
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
    """Test finding normalization methods."""

    def test_normalize_failed_check(self, parser, sample_failed_check):
        """Failed check is normalized correctly."""
        finding = parser.normalize_finding(sample_failed_check, passed=False)

        assert finding.source == FindingSource.CHECKOV
        assert finding.severity in [SeverityLevel.MEDIUM, SeverityLevel.HIGH]
        assert finding.check_id == "CKV_AWS_21"
        assert finding.title == "Ensure the S3 bucket has versioning enabled"
        assert finding.resource == "aws_s3_bucket.data_bucket"
        assert "/terraform/main.tf" in finding.description
        assert "15" in finding.description  # line number
        assert finding.remediation is not None
        assert "bridgecrew" in finding.remediation

    def test_normalize_passed_check(self, parser, sample_passed_check):
        """Passed check gets PASS severity."""
        finding = parser.normalize_finding(sample_passed_check, passed=True)

        assert finding.severity == SeverityLevel.PASS
        assert finding.check_id == "CKV_AWS_18"
        assert finding.resource == "aws_s3_bucket.logs_bucket"

    def test_normalize_skipped_check(self, parser, sample_skipped_check):
        """Skipped check gets INFO severity."""
        finding = parser.normalize_finding(sample_skipped_check, passed=None)

        assert finding.severity == SeverityLevel.INFO
        assert finding.check_id == "CKV_AWS_1"
        assert "Not applicable" in finding.description

    def test_normalize_includes_raw(self, parser, sample_failed_check):
        """Raw check data is preserved."""
        finding = parser.normalize_finding(sample_failed_check, passed=False)
        assert finding.raw == sample_failed_check

    def test_normalize_includes_file_location(self, parser, sample_failed_check):
        """File path and line range are included in description."""
        finding = parser.normalize_finding(sample_failed_check, passed=False)

        assert "/terraform/main.tf" in finding.description
        assert "15" in finding.description
        assert "25" in finding.description

    def test_normalize_includes_evaluation_reason(self, parser, sample_failed_check):
        """Evaluation reason is included in description."""
        finding = parser.normalize_finding(sample_failed_check, passed=False)
        assert "versioning not enabled" in finding.description

    def test_normalize_sets_resource_type(self, parser, sample_failed_check):
        """Resource type is set from check_type."""
        finding = parser.normalize_finding(
            sample_failed_check, passed=False, check_type="terraform"
        )
        assert finding.resource_type == "terraform"


class TestCheckovParserSeverityDerivation:
    """Test severity derivation logic."""

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
        finding = parser.normalize_finding(raw, passed=False)
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
        finding = parser.normalize_finding(raw, passed=False)
        assert finding.severity == SeverityLevel.HIGH

    def test_mfa_check_is_high(self, parser):
        """MFA-related checks are HIGH severity."""
        raw = {
            "check_id": "CKV_AWS_50",
            "check_name": "Ensure MFA is enabled for root account",
            "check_result": {"result": "FAILED"},
            "resource": "aws_account.main",
            "file_path": "/account.tf",
            "file_line_range": [1, 5],
        }
        finding = parser.normalize_finding(raw, passed=False)
        assert finding.severity == SeverityLevel.HIGH

    def test_public_access_is_high(self, parser):
        """Public access checks are HIGH severity."""
        raw = {
            "check_id": "CKV_AWS_55",
            "check_name": "Ensure S3 bucket is not publicly accessible",
            "check_result": {"result": "FAILED"},
            "resource": "aws_s3_bucket.public",
            "file_path": "/s3.tf",
            "file_line_range": [1, 10],
        }
        finding = parser.normalize_finding(raw, passed=False)
        assert finding.severity == SeverityLevel.HIGH

    def test_secret_check_is_critical(self, parser):
        """Secret-related checks are CRITICAL severity."""
        raw = {
            "check_id": "CKV_SECRET_1",
            "check_name": "Ensure no hardcoded secrets in code",
            "check_result": {"result": "FAILED"},
            "resource": "secrets_found",
            "file_path": "/main.tf",
            "file_line_range": [1, 5],
        }
        finding = parser.normalize_finding(raw, passed=False)
        assert finding.severity == SeverityLevel.CRITICAL

    def test_credential_check_is_critical(self, parser):
        """Credential-related checks are CRITICAL severity."""
        raw = {
            "check_id": "CKV_AWS_99",
            "check_name": "Ensure no hardcoded credentials in Lambda",
            "check_result": {"result": "FAILED"},
            "resource": "aws_lambda_function.main",
            "file_path": "/lambda.tf",
            "file_line_range": [1, 10],
        }
        finding = parser.normalize_finding(raw, passed=False)
        assert finding.severity == SeverityLevel.CRITICAL

    def test_generic_check_is_medium(self, parser):
        """Generic checks default to MEDIUM severity."""
        raw = {
            "check_id": "CKV_AWS_999",
            "check_name": "Ensure something is configured",
            "check_result": {"result": "FAILED"},
            "resource": "aws_something.main",
            "file_path": "/main.tf",
            "file_line_range": [1, 5],
        }
        finding = parser.normalize_finding(raw, passed=False)
        assert finding.severity == SeverityLevel.MEDIUM


class TestCheckovParserParse:
    """Test the main parse method."""

    def test_parse_full_output(self, parser, full_checkov_output):
        """Parses complete Checkov output with all check types."""
        raw = json.dumps(full_checkov_output)
        result = parser.parse(raw)

        assert len(result.findings) == 2  # 1 passed + 1 failed
        assert result.summary.total_findings == 2
        assert result.summary.pass_count == 1  # Uses Checkov's count

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
        assert result.summary.total_findings == 0

    def test_parse_empty_string(self, parser):
        """Handles empty string input."""
        result = parser.parse("")

        assert len(result.findings) == 0
        assert result.summary.total_findings == 0

    def test_parse_whitespace_only(self, parser):
        """Handles whitespace-only input."""
        result = parser.parse("   \n   ")

        assert len(result.findings) == 0

    def test_parse_invalid_json(self, parser):
        """Handles invalid JSON gracefully."""
        result = parser.parse("not valid json")

        assert len(result.findings) == 0
        assert result.summary.total_findings == 0

    def test_parse_with_skipped_checks(self, parser, sample_skipped_check):
        """Parses output with skipped checks."""
        output = {
            "check_type": "terraform",
            "results": {
                "passed_checks": [],
                "failed_checks": [],
                "skipped_checks": [sample_skipped_check],
            },
            "summary": {"passed": 0, "failed": 0, "skipped": 1},
        }
        result = parser.parse(json.dumps(output))

        assert len(result.findings) == 1
        assert result.findings[0].severity == SeverityLevel.INFO

    def test_parse_preserves_check_type(self, parser, sample_failed_check):
        """check_type is preserved in findings."""
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

    def test_parse_multiple_frameworks(self, parser, sample_failed_check):
        """Framework type is captured in resource_type."""
        for framework in ["terraform", "cloudformation", "kubernetes", "dockerfile"]:
            output = {
                "check_type": framework,
                "results": {
                    "passed_checks": [],
                    "failed_checks": [sample_failed_check],
                    "skipped_checks": [],
                },
                "summary": {"passed": 0, "failed": 1, "skipped": 0},
            }
            result = parser.parse(json.dumps(output))
            assert result.findings[0].resource_type == framework


class TestCheckovParserSummary:
    """Test summary building."""

    def test_summary_severity_counts(self, parser):
        """Summary has accurate severity counts."""
        output = {
            "check_type": "terraform",
            "results": {
                "passed_checks": [
                    {"check_id": "CKV_1", "check_name": "Pass", "check_result": {"result": "PASSED"},
                     "resource": "r1", "file_path": "/a.tf", "file_line_range": [1, 2]},
                ],
                "failed_checks": [
                    {"check_id": "CKV_SECRET_1", "check_name": "Secret exposed", "check_result": {"result": "FAILED"},
                     "resource": "r2", "file_path": "/b.tf", "file_line_range": [1, 2]},  # CRITICAL
                    {"check_id": "CKV_IAM_1", "check_name": "IAM issue", "check_result": {"result": "FAILED"},
                     "resource": "r3", "file_path": "/c.tf", "file_line_range": [1, 2]},  # HIGH
                    {"check_id": "CKV_AWS_999", "check_name": "Generic", "check_result": {"result": "FAILED"},
                     "resource": "r4", "file_path": "/d.tf", "file_line_range": [1, 2]},  # MEDIUM
                ],
                "skipped_checks": [
                    {"check_id": "CKV_5", "check_name": "Skip", "check_result": {"result": "SKIPPED"},
                     "resource": "r5", "file_path": "/e.tf", "file_line_range": [1, 2]},
                ],
            },
            "summary": {"passed": 1, "failed": 3, "skipped": 1},
        }
        result = parser.parse(json.dumps(output))

        assert result.summary.total_findings == 5
        assert result.summary.critical_count == 1
        assert result.summary.high_count == 1
        assert result.summary.medium_count == 1
        assert result.summary.info_count == 1  # skipped
        assert result.summary.pass_count == 1

    def test_summary_source_is_checkov(self, parser, full_checkov_output):
        """Summary has correct source."""
        result = parser.parse(json.dumps(full_checkov_output))

        assert result.summary.source == FindingSource.CHECKOV

    def test_summary_includes_check_type(self, parser, full_checkov_output):
        """Summary includes scanned framework."""
        result = parser.parse(json.dumps(full_checkov_output))

        assert "terraform" in result.summary.services_scanned


class TestCheckovParserFixture:
    """Test with fixture file."""

    def test_parse_fixture_file(self, parser):
        """Parses the sample fixture file."""
        fixture_path = Path(__file__).parent / "fixtures" / "checkov_terraform_sample.json"
        assert fixture_path.exists(), "Fixture file should exist"

        raw = fixture_path.read_text()
        result = parser.parse(raw)

        # Based on fixture: 1 passed, 3 failed, 1 skipped
        assert result.summary.total_findings == 5
        assert result.summary.pass_count == 1
        # 3 failed checks: CKV_AWS_21 (medium), CKV_AWS_19 (high), CKV_AWS_40 (high)
        assert result.summary.high_count >= 2
        assert result.summary.info_count == 1  # skipped


class TestCheckovParserPersistence:
    """Test save and load functionality."""

    def test_roundtrip_persistence(self, parser, full_checkov_output, tmp_path):
        """Save and load preserves data."""
        raw = json.dumps(full_checkov_output)
        result = parser.parse(raw)

        # Save
        path = tmp_path / "result.json"
        parser.save_result(result, str(path))

        # Load
        loaded = parser.load_result(str(path))

        assert loaded.summary.total_findings == result.summary.total_findings
        assert len(loaded.findings) == len(result.findings)
        assert loaded.findings[0].check_id == result.findings[0].check_id


class TestImports:
    """Test module imports."""

    def test_import_from_checkov_package(self):
        """Parser can be imported from checkov package."""
        from parrot.tools.security.checkov import CheckovParser

        assert CheckovParser is not None

    def test_import_from_security_package(self):
        """Parser can be imported from security package."""
        from parrot.tools.security import CheckovParser

        parser = CheckovParser()
        assert parser is not None
