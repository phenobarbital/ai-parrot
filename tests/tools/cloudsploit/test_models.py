"""Unit tests for CloudSploit data models."""
import pytest
from datetime import datetime
from parrot.tools.cloudsploit.models import (
    SeverityLevel,
    ComplianceFramework,
    ScanFinding,
    ScanSummary,
    ScanResult,
    CloudSploitConfig,
    ComparisonReport,
)


class TestSeverityLevel:
    def test_valid_values(self):
        assert SeverityLevel.OK == "OK"
        assert SeverityLevel.WARN == "WARN"
        assert SeverityLevel.FAIL == "FAIL"
        assert SeverityLevel.UNKNOWN == "UNKNOWN"

    def test_from_string(self):
        assert SeverityLevel("WARN") == SeverityLevel.WARN
        assert SeverityLevel("FAIL") == SeverityLevel.FAIL

    def test_invalid_value(self):
        with pytest.raises(ValueError):
            SeverityLevel("CRITICAL")


class TestComplianceFramework:
    def test_valid_values(self):
        assert ComplianceFramework.HIPAA == "hipaa"
        assert ComplianceFramework.CIS1 == "cis1"
        assert ComplianceFramework.CIS2 == "cis2"
        assert ComplianceFramework.PCI == "pci"

    def test_from_string(self):
        assert ComplianceFramework("pci") == ComplianceFramework.PCI


class TestScanFinding:
    def test_from_dict(self):
        finding = ScanFinding(
            plugin="ec2-open-ssh",
            category="EC2",
            title="Open SSH",
            status=SeverityLevel.FAIL,
            region="us-east-1",
            resource="arn:aws:ec2:us-east-1:123456:sg/sg-123",
            message="Security group allows unrestricted SSH access",
        )
        assert finding.status == SeverityLevel.FAIL
        assert finding.category == "EC2"
        assert finding.plugin == "ec2-open-ssh"
        assert finding.resource == "arn:aws:ec2:us-east-1:123456:sg/sg-123"

    def test_optional_fields(self):
        finding = ScanFinding(
            plugin="test",
            category="IAM",
            title="Test",
            status=SeverityLevel.OK,
        )
        assert finding.resource is None
        assert finding.region == "global"
        assert finding.description == ""
        assert finding.message == ""

    def test_all_severity_levels(self):
        for level in SeverityLevel:
            finding = ScanFinding(
                plugin="test",
                category="EC2",
                title="Test",
                status=level,
            )
            assert finding.status == level

    def test_json_serialization(self):
        finding = ScanFinding(
            plugin="test",
            category="EC2",
            title="Test Finding",
            status=SeverityLevel.WARN,
            region="us-west-2",
            resource="sg-abc",
            message="Warning message",
        )
        json_str = finding.model_dump_json()
        restored = ScanFinding.model_validate_json(json_str)
        assert restored.plugin == finding.plugin
        assert restored.status == finding.status
        assert restored.resource == finding.resource


class TestScanSummary:
    def test_basic_summary(self):
        summary = ScanSummary(
            total_findings=10,
            ok_count=5,
            warn_count=3,
            fail_count=2,
            unknown_count=0,
            scan_timestamp=datetime(2026, 2, 20, 12, 0, 0),
        )
        assert summary.total_findings == 10
        assert summary.ok_count == 5
        assert summary.categories == {}
        assert summary.compliance_framework is None
        assert summary.duration_seconds is None

    def test_with_categories(self):
        summary = ScanSummary(
            total_findings=3,
            ok_count=1,
            warn_count=1,
            fail_count=1,
            unknown_count=0,
            scan_timestamp=datetime.now(),
            categories={"EC2": 2, "S3": 1},
        )
        assert summary.categories["EC2"] == 2

    def test_with_compliance(self):
        summary = ScanSummary(
            total_findings=5,
            ok_count=3,
            warn_count=1,
            fail_count=1,
            unknown_count=0,
            scan_timestamp=datetime.now(),
            compliance_framework="pci",
            duration_seconds=123.45,
        )
        assert summary.compliance_framework == "pci"
        assert summary.duration_seconds == 123.45


class TestCloudSploitConfig:
    def test_default_values(self):
        config = CloudSploitConfig()
        assert config.docker_image == "cloudsploit:0.0.1"
        assert config.timeout_seconds == 600
        assert config.aws_region == "us-east-1"
        assert config.govcloud is False
        assert config.use_docker is True
        assert config.aws_access_key_id is None
        assert config.aws_profile is None
        assert config.results_dir is None

    def test_explicit_credentials(self):
        config = CloudSploitConfig(
            aws_access_key_id="AKIA...",
            aws_secret_access_key="secret",
            aws_session_token="token123",
        )
        assert config.aws_access_key_id == "AKIA..."
        assert config.aws_secret_access_key == "secret"
        assert config.aws_session_token == "token123"

    def test_profile_credentials(self):
        config = CloudSploitConfig(aws_profile="production")
        assert config.aws_profile == "production"

    def test_results_dir(self):
        config = CloudSploitConfig(results_dir="/tmp/cloudsploit_results")
        assert config.results_dir == "/tmp/cloudsploit_results"

    def test_docker_disabled(self):
        config = CloudSploitConfig(
            use_docker=False,
            cli_path="/usr/local/bin/cloudsploit",
        )
        assert config.use_docker is False
        assert config.cli_path == "/usr/local/bin/cloudsploit"

    def test_govcloud_mode(self):
        config = CloudSploitConfig(govcloud=True)
        assert config.govcloud is True

    def test_custom_timeout(self):
        config = CloudSploitConfig(timeout_seconds=1200)
        assert config.timeout_seconds == 1200


class TestScanResult:
    def test_basic_result(self):
        result = ScanResult(
            findings=[
                ScanFinding(
                    plugin="test",
                    category="EC2",
                    title="Test",
                    status=SeverityLevel.OK,
                )
            ],
            summary=ScanSummary(
                total_findings=1,
                ok_count=1,
                warn_count=0,
                fail_count=0,
                unknown_count=0,
                scan_timestamp=datetime.now(),
            ),
        )
        assert len(result.findings) == 1
        assert result.raw_json is None
        assert result.collection_data is None

    def test_with_raw_data(self):
        result = ScanResult(
            findings=[],
            summary=ScanSummary(
                total_findings=0,
                ok_count=0,
                warn_count=0,
                fail_count=0,
                unknown_count=0,
                scan_timestamp=datetime.now(),
            ),
            raw_json={"pluginId": {"results": []}},
            collection_data={"ec2": {"instances": []}},
        )
        assert result.raw_json is not None
        assert result.collection_data is not None

    def test_json_round_trip(self):
        result = ScanResult(
            findings=[
                ScanFinding(
                    plugin="test",
                    category="EC2",
                    title="Test",
                    status=SeverityLevel.OK,
                ),
                ScanFinding(
                    plugin="test2",
                    category="S3",
                    title="Test2",
                    status=SeverityLevel.FAIL,
                    region="us-west-2",
                    resource="arn:aws:s3:::bucket",
                    message="Issue found",
                ),
            ],
            summary=ScanSummary(
                total_findings=2,
                ok_count=1,
                warn_count=0,
                fail_count=1,
                unknown_count=0,
                scan_timestamp=datetime(2026, 2, 20, 12, 0, 0),
                categories={"EC2": 1, "S3": 1},
            ),
        )
        json_str = result.model_dump_json()
        restored = ScanResult.model_validate_json(json_str)
        assert restored.summary.total_findings == 2
        assert restored.summary.fail_count == 1
        assert len(restored.findings) == 2
        assert restored.findings[1].resource == "arn:aws:s3:::bucket"

    def test_empty_result(self):
        result = ScanResult(
            findings=[],
            summary=ScanSummary(
                total_findings=0,
                ok_count=0,
                warn_count=0,
                fail_count=0,
                unknown_count=0,
                scan_timestamp=datetime.now(),
            ),
        )
        assert result.summary.total_findings == 0
        assert len(result.findings) == 0


class TestComparisonReport:
    def test_empty_comparison(self):
        report = ComparisonReport()
        assert len(report.new_findings) == 0
        assert len(report.resolved_findings) == 0
        assert len(report.unchanged_findings) == 0
        assert len(report.severity_changed) == 0

    def test_with_findings(self):
        finding = ScanFinding(
            plugin="test",
            category="EC2",
            title="Test",
            status=SeverityLevel.FAIL,
        )
        report = ComparisonReport(
            new_findings=[finding],
            resolved_findings=[],
            unchanged_findings=[],
            baseline_timestamp=datetime(2026, 2, 19),
            current_timestamp=datetime(2026, 2, 20),
        )
        assert len(report.new_findings) == 1
        assert report.baseline_timestamp is not None

    def test_json_round_trip(self):
        report = ComparisonReport(
            new_findings=[
                ScanFinding(
                    plugin="new-issue",
                    category="IAM",
                    title="New Issue",
                    status=SeverityLevel.FAIL,
                )
            ],
            resolved_findings=[
                ScanFinding(
                    plugin="old-issue",
                    category="S3",
                    title="Old Issue",
                    status=SeverityLevel.WARN,
                )
            ],
            unchanged_findings=[],
            baseline_timestamp=datetime(2026, 2, 19, 10, 0, 0),
            current_timestamp=datetime(2026, 2, 20, 10, 0, 0),
        )
        json_str = report.model_dump_json()
        restored = ComparisonReport.model_validate_json(json_str)
        assert len(restored.new_findings) == 1
        assert len(restored.resolved_findings) == 1
        assert restored.new_findings[0].plugin == "new-issue"
