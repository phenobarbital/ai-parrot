"""Unit tests for the Trivy parser."""

import json
from pathlib import Path

import pytest

from parrot.tools.security.models import (
    FindingSource,
    SeverityLevel,
)
from parrot.tools.security.trivy.parser import TrivyParser


@pytest.fixture
def parser():
    """Create a parser instance for testing."""
    return TrivyParser()


@pytest.fixture
def sample_vulnerability():
    """Single Trivy vulnerability finding."""
    return {
        "VulnerabilityID": "CVE-2023-44487",
        "PkgID": "golang.org/x/net@v0.7.0",
        "PkgName": "golang.org/x/net",
        "InstalledVersion": "v0.7.0",
        "FixedVersion": "v0.17.0",
        "Severity": "HIGH",
        "Title": "HTTP/2 Rapid Reset Attack",
        "Description": "The HTTP/2 protocol allows a denial of service because request cancellation can reset many streams quickly.",
        "References": [
            "https://nvd.nist.gov/vuln/detail/CVE-2023-44487",
            "https://github.com/advisories/GHSA-qppj-fm5r-hxr3",
        ],
    }


@pytest.fixture
def sample_secret():
    """Single Trivy secret finding."""
    return {
        "RuleID": "aws-access-key-id",
        "Category": "AWS",
        "Severity": "CRITICAL",
        "Title": "AWS Access Key ID",
        "Match": "AKIAIOSFODNN7EXAMPLE",
        "StartLine": 15,
        "EndLine": 15,
    }


@pytest.fixture
def sample_misconfig():
    """Single Trivy misconfiguration finding."""
    return {
        "Type": "Dockerfile",
        "ID": "DS002",
        "AVDID": "AVD-DS-0002",
        "Title": "Image user should not be 'root'",
        "Description": "Running containers as root is a security risk.",
        "Severity": "HIGH",
        "Resolution": "Add 'USER nonroot' to Dockerfile",
        "References": [
            "https://docs.docker.com/develop/develop-images/dockerfile_best-practices/"
        ],
    }


@pytest.fixture
def full_trivy_output(sample_vulnerability, sample_secret, sample_misconfig):
    """Complete Trivy output with all finding types."""
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
    """Test finding normalization methods."""

    def test_normalize_vulnerability(self, parser, sample_vulnerability):
        """Vulnerability is normalized correctly."""
        finding = parser.normalize_vulnerability(sample_vulnerability)

        assert finding.source == FindingSource.TRIVY
        assert finding.severity == SeverityLevel.HIGH
        assert finding.check_id == "CVE-2023-44487"
        assert finding.title == "HTTP/2 Rapid Reset Attack"
        assert "golang.org/x/net" in finding.resource
        assert "v0.7.0" in finding.resource
        assert finding.resource_type == "vulnerability"
        assert finding.remediation is not None
        assert "v0.17.0" in finding.remediation

    def test_normalize_vulnerability_no_fix(self, parser):
        """Vulnerability without fix version is handled."""
        vuln = {
            "VulnerabilityID": "CVE-2023-12345",
            "PkgName": "testpkg",
            "InstalledVersion": "1.0.0",
            "Severity": "MEDIUM",
            "Title": "Test vulnerability",
        }
        finding = parser.normalize_vulnerability(vuln)

        assert finding.severity == SeverityLevel.MEDIUM
        assert finding.resource == "testpkg@1.0.0"

    def test_normalize_secret(self, parser, sample_secret):
        """Secret is normalized with masked value."""
        finding = parser.normalize_secret(sample_secret)

        assert finding.source == FindingSource.TRIVY
        assert finding.severity == SeverityLevel.CRITICAL
        assert finding.check_id == "aws-access-key-id"
        assert finding.resource_type == "secret"
        # Value should be masked
        assert "AKIAIOSFODNN7EXAMPLE" not in finding.description
        # Should show partial masking
        assert "AKIA" in finding.description
        assert "***" in finding.description

    def test_normalize_secret_short_value(self, parser):
        """Short secret values are fully masked."""
        secret = {
            "RuleID": "generic-api-key",
            "Category": "Generic",
            "Severity": "HIGH",
            "Title": "API Key",
            "Match": "abc",
        }
        finding = parser.normalize_secret(secret)

        # Short values should be fully masked
        assert "abc" not in finding.description
        assert "***" in finding.description

    def test_normalize_misconfig(self, parser, sample_misconfig):
        """Misconfiguration is normalized correctly."""
        finding = parser.normalize_misconfiguration(sample_misconfig)

        assert finding.source == FindingSource.TRIVY
        assert finding.severity == SeverityLevel.HIGH
        assert finding.check_id == "DS002"
        assert finding.resource_type == "Dockerfile"
        assert "USER nonroot" in finding.remediation
        assert "root" in finding.description


class TestTrivyParserSeverityMapping:
    """Test severity mapping."""

    @pytest.mark.parametrize(
        "trivy_severity,expected",
        [
            ("CRITICAL", SeverityLevel.CRITICAL),
            ("HIGH", SeverityLevel.HIGH),
            ("MEDIUM", SeverityLevel.MEDIUM),
            ("LOW", SeverityLevel.LOW),
            ("UNKNOWN", SeverityLevel.UNKNOWN),
        ],
    )
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

    def test_unknown_severity(self, parser):
        """Unknown severity strings map to UNKNOWN."""
        raw = {
            "VulnerabilityID": "CVE-TEST",
            "PkgName": "test",
            "Severity": "INVALID",
            "Title": "Test",
        }
        finding = parser.normalize_vulnerability(raw)
        assert finding.severity == SeverityLevel.UNKNOWN

    def test_empty_severity(self, parser):
        """Empty severity maps to UNKNOWN."""
        raw = {
            "VulnerabilityID": "CVE-TEST",
            "PkgName": "test",
            "Severity": "",
            "Title": "Test",
        }
        finding = parser.normalize_vulnerability(raw)
        assert finding.severity == SeverityLevel.UNKNOWN


class TestTrivyParserParse:
    """Test the main parse method."""

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
        assert result.findings[0].resource_type == "vulnerability"

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

    def test_parse_misconfigs_only(self, parser, sample_misconfig):
        """Parses output with only misconfigurations."""
        output = {
            "SchemaVersion": 2,
            "ArtifactName": "test",
            "Results": [
                {
                    "Target": "test",
                    "Misconfigurations": [sample_misconfig],
                }
            ],
        }
        result = parser.parse(json.dumps(output))

        assert len(result.findings) == 1
        assert result.findings[0].resource_type == "Dockerfile"

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

    def test_parse_preserves_target(self, parser, sample_vulnerability):
        """Target is preserved in findings."""
        output = {
            "SchemaVersion": 2,
            "ArtifactName": "test",
            "Results": [
                {
                    "Target": "nginx:1.21 (debian 11)",
                    "Vulnerabilities": [sample_vulnerability],
                }
            ],
        }
        result = parser.parse(json.dumps(output))

        assert result.findings[0].service == "nginx:1.21 (debian 11)"


class TestTrivyParserSummary:
    """Test summary building."""

    def test_summary_severity_counts(self, parser):
        """Summary has accurate severity counts."""
        output = {
            "SchemaVersion": 2,
            "ArtifactName": "test",
            "Results": [
                {
                    "Target": "test",
                    "Vulnerabilities": [
                        {"VulnerabilityID": "CVE-1", "PkgName": "a", "Severity": "CRITICAL", "Title": "T"},
                        {"VulnerabilityID": "CVE-2", "PkgName": "b", "Severity": "CRITICAL", "Title": "T"},
                        {"VulnerabilityID": "CVE-3", "PkgName": "c", "Severity": "HIGH", "Title": "T"},
                        {"VulnerabilityID": "CVE-4", "PkgName": "d", "Severity": "MEDIUM", "Title": "T"},
                        {"VulnerabilityID": "CVE-5", "PkgName": "e", "Severity": "LOW", "Title": "T"},
                    ],
                }
            ],
        }
        result = parser.parse(json.dumps(output))

        assert result.summary.total_findings == 5
        assert result.summary.critical_count == 2
        assert result.summary.high_count == 1
        assert result.summary.medium_count == 1
        assert result.summary.low_count == 1

    def test_summary_source_is_trivy(self, parser, full_trivy_output):
        """Summary has correct source."""
        result = parser.parse(json.dumps(full_trivy_output))

        assert result.summary.source == FindingSource.TRIVY

    def test_summary_collects_resource_types(self, parser, full_trivy_output):
        """Summary collects scanned resource types."""
        result = parser.parse(json.dumps(full_trivy_output))

        # Should include vulnerability, secret, and Dockerfile
        assert "vulnerability" in result.summary.services_scanned
        assert "secret" in result.summary.services_scanned
        assert "Dockerfile" in result.summary.services_scanned


class TestTrivyParserSecretMasking:
    """Test secret value masking."""

    def test_mask_long_secret(self, parser):
        """Long secrets show first and last 4 chars."""
        masked = parser._mask_secret("AKIAIOSFODNN7EXAMPLE")

        assert masked.startswith("AKIA")
        assert masked.endswith("MPLE")
        assert "***" in masked
        assert "IOSFODNN7EXA" not in masked

    def test_mask_medium_secret(self, parser):
        """Medium secrets show partial masking."""
        masked = parser._mask_secret("abcdefgh")

        assert masked.startswith("ab")
        assert "***" in masked

    def test_mask_short_secret(self, parser):
        """Short secrets are fully masked."""
        masked = parser._mask_secret("abc")

        assert masked == "***"

    def test_mask_empty_secret(self, parser):
        """Empty secrets return placeholder."""
        masked = parser._mask_secret("")

        assert masked == "***"


class TestTrivyParserFixture:
    """Test with fixture file."""

    def test_parse_fixture_file(self, parser):
        """Parses the sample fixture file."""
        fixture_path = Path(__file__).parent / "fixtures" / "trivy_image_sample.json"
        assert fixture_path.exists(), "Fixture file should exist"

        raw = fixture_path.read_text()
        result = parser.parse(raw)

        # Based on the fixture content
        assert result.summary.total_findings == 6  # 3 vulns + 2 misconfigs + 1 secret
        assert result.summary.critical_count == 2  # libcurl vuln + AWS secret
        assert result.summary.high_count == 2  # HTTP/2 vuln + root user misconfig
        assert result.summary.medium_count == 1  # zlib vuln
        assert result.summary.low_count == 1  # HEALTHCHECK misconfig


class TestTrivyParserPersistence:
    """Test save and load functionality."""

    def test_roundtrip_persistence(self, parser, full_trivy_output, tmp_path):
        """Save and load preserves data."""
        raw = json.dumps(full_trivy_output)
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

    def test_import_from_trivy_package(self):
        """Parser can be imported from trivy package."""
        from parrot.tools.security.trivy import TrivyParser

        assert TrivyParser is not None

    def test_import_from_security_package(self):
        """Parser can be imported from security package."""
        from parrot.tools.security import TrivyParser

        parser = TrivyParser()
        assert parser is not None
