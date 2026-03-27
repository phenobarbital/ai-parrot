"""Unit tests for the Prowler parser."""

import json
from pathlib import Path

import pytest

from parrot.tools.security.models import (
    CloudProvider,
    FindingSource,
    SeverityLevel,
)
from parrot.tools.security.prowler.parser import ProwlerParser


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
        assert finding.provider == CloudProvider.AWS

    def test_normalize_pass_finding(self, parser, sample_pass_finding):
        """PASS finding gets PASS severity."""
        finding = parser.normalize_finding(sample_pass_finding)

        assert finding.severity == SeverityLevel.PASS
        assert finding.title == "Root account has MFA enabled"
        assert finding.service == "iam"

    def test_normalize_missing_optional_fields(self, parser):
        """Handles missing optional fields gracefully."""
        minimal = {
            "finding_info": {"uid": "test-123", "title": "Test"},
            "severity": "Medium",
            "status": "FAIL",
            "resources": [],
        }
        finding = parser.normalize_finding(minimal)

        assert finding.id == "test-123"
        assert finding.resource is None
        assert finding.region == "global"
        assert finding.compliance_tags == []
        assert finding.remediation is None

    def test_normalize_extracts_check_id(self, parser, sample_ocsf_finding):
        """Check ID is extracted from UID."""
        finding = parser.normalize_finding(sample_ocsf_finding)
        # prowler-aws-s3_bucket_public_access-123 -> s3_bucket_public_access
        assert finding.check_id == "s3_bucket_public_access"

    def test_normalize_string_compliance_tags(self, parser):
        """Handles compliance tags as string instead of list."""
        raw = {
            "finding_info": {"uid": "test", "title": "Test"},
            "severity": "Low",
            "status": "FAIL",
            "resources": [],
            "unmapped": {"check_type": "soc2"},
        }
        finding = parser.normalize_finding(raw)
        assert finding.compliance_tags == ["soc2"]


class TestProwlerParserSeverityMapping:
    @pytest.mark.parametrize(
        "prowler_severity,expected",
        [
            ("critical", SeverityLevel.CRITICAL),
            ("Critical", SeverityLevel.CRITICAL),
            ("high", SeverityLevel.HIGH),
            ("High", SeverityLevel.HIGH),
            ("medium", SeverityLevel.MEDIUM),
            ("Medium", SeverityLevel.MEDIUM),
            ("low", SeverityLevel.LOW),
            ("Low", SeverityLevel.LOW),
            ("informational", SeverityLevel.INFO),
            ("Informational", SeverityLevel.INFO),
            ("info", SeverityLevel.INFO),
        ],
    )
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

    def test_unknown_severity(self, parser):
        """Unknown severity maps to UNKNOWN."""
        raw = {
            "finding_info": {"uid": "test", "title": "Test"},
            "severity": "UnknownLevel",
            "status": "FAIL",
            "resources": [],
        }
        finding = parser.normalize_finding(raw)
        assert finding.severity == SeverityLevel.UNKNOWN


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

    def test_parse_empty_string(self, parser):
        """Handles empty string."""
        result = parser.parse("")
        assert len(result.findings) == 0

    def test_parse_whitespace_only(self, parser):
        """Handles whitespace-only string."""
        result = parser.parse("   \n   ")
        assert len(result.findings) == 0

    def test_summary_severity_counts(self, parser):
        """Summary has accurate severity counts."""
        findings = (
            [
                {
                    "finding_info": {"uid": f"c{i}", "title": "T"},
                    "severity": "Critical",
                    "status": "FAIL",
                    "resources": [],
                }
                for i in range(3)
            ]
            + [
                {
                    "finding_info": {"uid": f"h{i}", "title": "T"},
                    "severity": "High",
                    "status": "FAIL",
                    "resources": [],
                }
                for i in range(2)
            ]
            + [
                {
                    "finding_info": {"uid": "p1", "title": "T"},
                    "severity": "Low",
                    "status": "PASS",
                    "resources": [],
                }
            ]
        )
        raw = json.dumps(findings)
        result = parser.parse(raw)

        assert result.summary.critical_count == 3
        assert result.summary.high_count == 2
        assert result.summary.pass_count == 1
        assert result.summary.total_findings == 6

    def test_summary_services_collected(self, parser):
        """Summary collects scanned services."""
        findings = [
            {
                "finding_info": {"uid": "f1", "title": "T"},
                "severity": "High",
                "status": "FAIL",
                "resources": [],
                "unmapped": {"service_name": "s3"},
            },
            {
                "finding_info": {"uid": "f2", "title": "T"},
                "severity": "High",
                "status": "FAIL",
                "resources": [],
                "unmapped": {"service_name": "iam"},
            },
            {
                "finding_info": {"uid": "f3", "title": "T"},
                "severity": "High",
                "status": "FAIL",
                "resources": [],
                "unmapped": {"service_name": "s3"},
            },
        ]
        raw = json.dumps(findings)
        result = parser.parse(raw)

        assert "s3" in result.summary.services_scanned
        assert "iam" in result.summary.services_scanned


class TestProwlerParserProviderDetection:
    def test_detect_aws_from_arn(self, parser):
        """Detects AWS from ARN."""
        raw = {
            "finding_info": {"uid": "test", "title": "Test"},
            "severity": "High",
            "status": "FAIL",
            "resources": [{"uid": "arn:aws:s3:::bucket", "region": "us-east-1"}],
        }
        finding = parser.normalize_finding(raw)
        assert finding.provider == CloudProvider.AWS

    def test_detect_aws_from_type(self, parser):
        """Detects AWS from resource type."""
        raw = {
            "finding_info": {"uid": "test", "title": "Test"},
            "severity": "High",
            "status": "FAIL",
            "resources": [{"uid": "some-id", "type": "AwsEc2Instance"}],
        }
        finding = parser.normalize_finding(raw)
        assert finding.provider == CloudProvider.AWS


class TestProwlerParserFixture:
    def test_parse_fixture_file(self, parser):
        """Parses the sample fixture file."""
        fixture_path = Path(__file__).parent / "fixtures" / "prowler_ocsf_sample.json"
        assert fixture_path.exists(), "Fixture file should exist"

        raw = fixture_path.read_text()
        result = parser.parse(raw)

        assert result.summary.total_findings == 3
        assert result.summary.high_count == 1
        assert result.summary.medium_count == 1
        assert result.summary.pass_count == 1

        # Check services
        services = result.summary.services_scanned
        assert "s3" in services
        assert "iam" in services
        assert "ec2" in services


class TestProwlerParserPersistence:
    def test_roundtrip_persistence(self, parser, sample_ocsf_finding, tmp_path):
        """Save and load preserves data."""
        raw = json.dumps([sample_ocsf_finding])
        result = parser.parse(raw)

        # Save
        path = tmp_path / "result.json"
        parser.save_result(result, str(path))

        # Load
        loaded = parser.load_result(str(path))

        assert loaded.summary.total_findings == result.summary.total_findings
        assert len(loaded.findings) == len(result.findings)
        assert loaded.findings[0].id == result.findings[0].id


class TestImports:
    def test_import_from_prowler_package(self):
        """Parser can be imported from prowler package."""
        from parrot.tools.security.prowler import ProwlerParser

        assert ProwlerParser is not None

    def test_import_from_security_package(self):
        """Parser can be imported from security package."""
        from parrot.tools.security import ProwlerParser

        parser = ProwlerParser()
        assert parser is not None
