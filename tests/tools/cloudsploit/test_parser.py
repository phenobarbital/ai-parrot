"""Unit tests for CloudSploit result parser."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from parrot.tools.cloudsploit.models import ScanResult, SeverityLevel
from parrot.tools.cloudsploit.parser import ScanResultParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def parser():
    return ScanResultParser()


@pytest.fixture
def sample_json():
    return json.dumps({
        "ec2OpenSSH": {
            "title": "Open SSH",
            "category": "EC2",
            "description": "Checks for open SSH ports",
            "recommended_action": "Restrict SSH access",
            "results": [
                {
                    "status": "FAIL",
                    "region": "us-east-1",
                    "resource": "arn:aws:ec2:us-east-1:123456:sg/sg-abc",
                    "message": "Security group sg-abc allows unrestricted SSH",
                },
                {
                    "status": "OK",
                    "region": "us-west-2",
                    "resource": "arn:aws:ec2:us-west-2:123456:sg/sg-def",
                    "message": "Security group sg-def restricts SSH",
                },
            ],
        },
        "s3BucketEncryption": {
            "title": "S3 Bucket Encryption",
            "category": "S3",
            "description": "Checks for S3 bucket encryption",
            "recommended_action": "Enable encryption",
            "results": [
                {
                    "status": "WARN",
                    "region": "global",
                    "resource": "arn:aws:s3:::my-bucket",
                    "message": "Bucket uses AES-256 but not KMS",
                }
            ],
        },
    })


@pytest.fixture
def fixture_json():
    """Load the realistic fixture file."""
    return (FIXTURES_DIR / "sample_scan_output.json").read_text(encoding="utf-8")


class TestParsing:
    def test_parse_returns_scan_result(self, parser, sample_json):
        result = parser.parse(sample_json)
        assert isinstance(result, ScanResult)
        assert len(result.findings) == 3

    def test_summary_counts(self, parser, sample_json):
        result = parser.parse(sample_json)
        assert result.summary.total_findings == 3
        assert result.summary.ok_count == 1
        assert result.summary.fail_count == 1
        assert result.summary.warn_count == 1

    def test_category_breakdown(self, parser, sample_json):
        result = parser.parse(sample_json)
        assert result.summary.categories["EC2"] == 2
        assert result.summary.categories["S3"] == 1

    def test_finding_fields(self, parser, sample_json):
        result = parser.parse(sample_json)
        fail = [f for f in result.findings if f.status == SeverityLevel.FAIL][0]
        assert fail.plugin == "ec2OpenSSH"
        assert fail.category == "EC2"
        assert fail.region == "us-east-1"
        assert fail.resource is not None
        assert fail.message != ""

    def test_raw_json_preserved(self, parser, sample_json):
        result = parser.parse(sample_json)
        assert result.raw_json is not None
        assert "ec2OpenSSH" in result.raw_json

    def test_custom_timestamp(self, parser, sample_json):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        result = parser.parse(sample_json, timestamp=ts)
        assert result.summary.scan_timestamp == ts

    def test_description_carried(self, parser, sample_json):
        result = parser.parse(sample_json)
        finding = result.findings[0]
        assert finding.description == "Checks for open SSH ports"


class TestFixtureFile:
    """Tests against the realistic fixture JSON."""

    def test_parse_fixture(self, parser, fixture_json):
        result = parser.parse(fixture_json)
        assert result.summary.total_findings == 7
        assert result.summary.fail_count == 3
        assert result.summary.ok_count == 2
        assert result.summary.warn_count == 1
        assert result.summary.unknown_count == 1

    def test_fixture_categories(self, parser, fixture_json):
        result = parser.parse(fixture_json)
        assert result.summary.categories["EC2"] == 3
        assert result.summary.categories["S3"] == 2
        assert result.summary.categories["IAM"] == 1
        assert result.summary.categories["RDS"] == 1


class TestFiltering:
    def test_filter_by_severity(self, parser, sample_json):
        result = parser.parse(sample_json)
        filtered = parser.filter_by_severity(result, [SeverityLevel.FAIL])
        assert len(filtered.findings) == 1
        assert filtered.findings[0].status == SeverityLevel.FAIL
        assert filtered.summary.fail_count == 1
        assert filtered.summary.ok_count == 0

    def test_filter_by_multiple_severities(self, parser, sample_json):
        result = parser.parse(sample_json)
        filtered = parser.filter_by_severity(
            result, [SeverityLevel.FAIL, SeverityLevel.WARN]
        )
        assert len(filtered.findings) == 2

    def test_filter_by_category(self, parser, sample_json):
        result = parser.parse(sample_json)
        filtered = parser.filter_by_category(result, ["S3"])
        assert len(filtered.findings) == 1
        assert filtered.findings[0].category == "S3"
        assert filtered.summary.categories == {"S3": 1}

    def test_filter_by_region(self, parser, sample_json):
        result = parser.parse(sample_json)
        filtered = parser.filter_by_region(result, ["us-east-1"])
        assert len(filtered.findings) == 1
        assert filtered.findings[0].region == "us-east-1"

    def test_filter_returns_empty(self, parser, sample_json):
        result = parser.parse(sample_json)
        filtered = parser.filter_by_category(result, ["Lambda"])
        assert len(filtered.findings) == 0
        assert filtered.summary.total_findings == 0


class TestEdgeCases:
    def test_empty_results(self, parser):
        result = parser.parse("{}")
        assert result.summary.total_findings == 0
        assert result.findings == []

    def test_malformed_json(self, parser):
        result = parser.parse("not json at all")
        assert result.summary.total_findings == 0
        assert result.findings == []

    def test_none_input(self, parser):
        result = parser.parse(None)
        assert result.summary.total_findings == 0

    def test_plugin_with_no_results_key(self, parser):
        raw = json.dumps({
            "somePlugin": {
                "title": "No results",
                "category": "EC2",
            }
        })
        result = parser.parse(raw)
        assert result.summary.total_findings == 0

    def test_plugin_with_empty_results(self, parser):
        raw = json.dumps({
            "somePlugin": {
                "title": "Empty results",
                "category": "EC2",
                "results": [],
            }
        })
        result = parser.parse(raw)
        assert result.summary.total_findings == 0

    def test_missing_status_defaults_to_unknown(self, parser):
        raw = json.dumps({
            "testPlugin": {
                "title": "Test",
                "category": "IAM",
                "results": [
                    {"region": "us-east-1", "message": "no status field"}
                ],
            }
        })
        result = parser.parse(raw)
        assert len(result.findings) == 1
        assert result.findings[0].status == SeverityLevel.UNKNOWN

    def test_non_dict_plugin_entry_skipped(self, parser):
        raw = json.dumps({"badPlugin": "not a dict", "goodPlugin": {
            "title": "Good",
            "category": "S3",
            "results": [{"status": "OK", "region": "global"}],
        }})
        result = parser.parse(raw)
        assert len(result.findings) == 1

    def test_json_array_input(self, parser):
        result = parser.parse("[]")
        assert result.summary.total_findings == 0


class TestPersistence:
    def test_save_and_load(self, parser, sample_json, tmp_path):
        result = parser.parse(sample_json)
        path = str(tmp_path / "scan_result.json")
        saved = parser.save_result(result, path)
        assert Path(saved).exists()

        loaded = parser.load_result(path)
        assert loaded.summary.total_findings == result.summary.total_findings
        assert len(loaded.findings) == len(result.findings)

    def test_round_trip_fidelity(self, parser, sample_json, tmp_path):
        result = parser.parse(sample_json)
        path = str(tmp_path / "round_trip.json")
        parser.save_result(result, path)
        loaded = parser.load_result(path)

        for orig, restored in zip(result.findings, loaded.findings):
            assert orig.plugin == restored.plugin
            assert orig.category == restored.category
            assert orig.status == restored.status
            assert orig.region == restored.region
            assert orig.resource == restored.resource
            assert orig.message == restored.message

    def test_save_creates_directories(self, parser, sample_json, tmp_path):
        result = parser.parse(sample_json)
        path = str(tmp_path / "nested" / "dir" / "result.json")
        parser.save_result(result, path)
        assert Path(path).exists()

    def test_summary_preserved(self, parser, sample_json, tmp_path):
        result = parser.parse(sample_json)
        path = str(tmp_path / "summary_test.json")
        parser.save_result(result, path)
        loaded = parser.load_result(path)

        assert loaded.summary.ok_count == result.summary.ok_count
        assert loaded.summary.warn_count == result.summary.warn_count
        assert loaded.summary.fail_count == result.summary.fail_count
        assert loaded.summary.categories == result.summary.categories


class TestFlatArrayFormat:
    """Tests for the flat-array CloudSploit JSON format (--json /dev/stdout)."""

    @pytest.fixture
    def flat_json(self):
        return json.dumps([
            {
                "plugin": "ec2OpenSSH",
                "category": "EC2",
                "title": "Open SSH",
                "description": "Check SSH ports",
                "resource": "sg-abc",
                "region": "us-east-1",
                "status": "FAIL",
                "message": "Unrestricted SSH",
            },
            {
                "plugin": "s3Encryption",
                "category": "S3",
                "title": "S3 Encryption",
                "description": "Check encryption",
                "resource": "my-bucket",
                "region": "global",
                "status": "OK",
                "message": "Encrypted",
            },
            {
                "plugin": "iamRootAccess",
                "category": "IAM",
                "title": "Root Access",
                "description": "Check root",
                "resource": "root",
                "region": "global",
                "status": "WARN",
                "message": "Root accessed",
                "compliance": {"pci": "PCI 2.1"},
            },
        ])

    def test_parse_flat_array(self, parser, flat_json):
        result = parser.parse(flat_json)
        assert result.summary.total_findings == 3
        assert result.summary.fail_count == 1
        assert result.summary.ok_count == 1
        assert result.summary.warn_count == 1

    def test_flat_array_finding_fields(self, parser, flat_json):
        result = parser.parse(flat_json)
        fail = [f for f in result.findings if f.status == SeverityLevel.FAIL][0]
        assert fail.plugin == "ec2OpenSSH"
        assert fail.category == "EC2"
        assert fail.region == "us-east-1"
        assert fail.message == "Unrestricted SSH"

    def test_flat_array_categories(self, parser, flat_json):
        result = parser.parse(flat_json)
        assert result.summary.categories == {"EC2": 1, "S3": 1, "IAM": 1}

    def test_single_flat_dict(self, parser):
        single = json.dumps({
            "plugin": "ec2OpenSSH",
            "category": "EC2",
            "title": "Open SSH",
            "description": "Check SSH",
            "resource": "sg-1",
            "region": "us-east-1",
            "status": "FAIL",
            "message": "Open",
        })
        result = parser.parse(single)
        assert result.summary.total_findings == 1
        assert result.summary.fail_count == 1

    def test_flat_array_in_noisy_output(self, parser):
        noisy = 'Some log noise\n[{"plugin": "test", "category": "EC2", "title": "T", "description": "", "resource": "r", "region": "us-east-1", "status": "OK", "message": "ok"}]\nMore noise'
        result = parser.parse(noisy)
        assert result.summary.total_findings == 1
        assert result.summary.ok_count == 1

