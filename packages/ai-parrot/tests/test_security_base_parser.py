"""Unit tests for the security base parser."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from parrot.tools.security.base_parser import BaseParser
from parrot.tools.security.models import (
    CloudProvider,
    FindingSource,
    ScanResult,
    ScanSummary,
    SecurityFinding,
    SeverityLevel,
)


class ConcreteParser(BaseParser):
    """Test implementation of BaseParser."""

    def parse(self, raw_output: str) -> ScanResult:
        """Simple test implementation that looks for FAIL in output."""
        findings = []
        if "FAIL" in raw_output:
            findings.append(
                self.normalize_finding({"status": "FAIL", "id": "test-1"})
            )
        summary = ScanSummary(
            source=FindingSource.PROWLER,
            provider=CloudProvider.AWS,
            total_findings=len(findings),
            high_count=len(findings),
            scan_timestamp=datetime.now(),
        )
        return ScanResult(findings=findings, summary=summary)

    def normalize_finding(self, raw_finding: dict) -> SecurityFinding:
        """Convert raw finding dict to SecurityFinding."""
        return SecurityFinding(
            id=raw_finding.get("id", "unknown"),
            source=FindingSource.PROWLER,
            severity=(
                SeverityLevel.HIGH
                if raw_finding.get("status") == "FAIL"
                else SeverityLevel.PASS
            ),
            title=f"Finding {raw_finding.get('id', 'unknown')}",
            raw=raw_finding,
        )


class TestBaseParserAbstract:
    def test_cannot_instantiate_base(self):
        """BaseParser cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseParser()  # type: ignore

    def test_concrete_implementation(self):
        """Concrete implementation can be instantiated."""
        parser = ConcreteParser()
        assert parser is not None
        assert parser.logger is not None


class TestBaseParserPersistence:
    @pytest.fixture
    def parser(self):
        return ConcreteParser()

    @pytest.fixture
    def sample_result(self):
        finding = SecurityFinding(
            id="test-001",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.CRITICAL,
            title="Test Finding",
            description="A test finding for persistence",
        )
        summary = ScanSummary(
            source=FindingSource.TRIVY,
            provider=CloudProvider.AWS,
            total_findings=1,
            critical_count=1,
            scan_timestamp=datetime.now(),
        )
        return ScanResult(findings=[finding], summary=summary)

    def test_save_result_creates_file(self, parser, sample_result):
        """save_result writes JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "result.json"
            saved_path = parser.save_result(sample_result, str(path))
            assert Path(saved_path).exists()

    def test_save_result_creates_parent_dirs(self, parser, sample_result):
        """save_result creates parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subdir" / "nested" / "result.json"
            saved_path = parser.save_result(sample_result, str(path))
            assert Path(saved_path).exists()

    def test_save_result_content(self, parser, sample_result):
        """save_result writes correct JSON content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "result.json"
            parser.save_result(sample_result, str(path))
            content = path.read_text()
            assert "test-001" in content
            assert "CRITICAL" in content
            assert "Test Finding" in content

    def test_load_result(self, parser, sample_result):
        """load_result reads JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "result.json"
            parser.save_result(sample_result, str(path))
            loaded = parser.load_result(str(path))
            assert len(loaded.findings) == 1
            assert loaded.findings[0].id == "test-001"

    def test_load_result_preserves_severity(self, parser, sample_result):
        """load_result preserves severity enum."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "result.json"
            parser.save_result(sample_result, str(path))
            loaded = parser.load_result(str(path))
            assert loaded.findings[0].severity == SeverityLevel.CRITICAL

    def test_roundtrip(self, parser, sample_result):
        """Save then load returns equivalent data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "result.json"
            parser.save_result(sample_result, str(path))
            loaded = parser.load_result(str(path))
            assert loaded.summary.total_findings == sample_result.summary.total_findings
            assert loaded.findings[0].severity == sample_result.findings[0].severity
            assert loaded.findings[0].title == sample_result.findings[0].title

    def test_roundtrip_multiple_findings(self, parser):
        """Roundtrip works with multiple findings."""
        findings = [
            SecurityFinding(
                id=f"finding-{i}",
                source=FindingSource.CHECKOV,
                severity=SeverityLevel.MEDIUM,
                title=f"Finding {i}",
            )
            for i in range(5)
        ]
        summary = ScanSummary(
            source=FindingSource.CHECKOV,
            provider=CloudProvider.LOCAL,
            total_findings=5,
            medium_count=5,
            scan_timestamp=datetime.now(),
        )
        result = ScanResult(findings=findings, summary=summary)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "result.json"
            parser.save_result(result, str(path))
            loaded = parser.load_result(str(path))
            assert len(loaded.findings) == 5
            assert loaded.findings[2].id == "finding-2"

    def test_load_missing_file(self, parser):
        """load_result raises error for missing file."""
        with pytest.raises(FileNotFoundError):
            parser.load_result("/nonexistent/path/to/file.json")


class TestConcreteParser:
    @pytest.fixture
    def parser(self):
        return ConcreteParser()

    def test_parse_with_failure(self, parser):
        """Parser extracts findings from raw output with FAIL."""
        result = parser.parse("FAIL: Something went wrong")
        assert len(result.findings) == 1
        assert result.findings[0].severity == SeverityLevel.HIGH
        assert result.summary.total_findings == 1

    def test_parse_without_failure(self, parser):
        """Parser handles output with no failures."""
        result = parser.parse("OK: Everything is fine")
        assert len(result.findings) == 0
        assert result.summary.total_findings == 0

    def test_parse_empty_string(self, parser):
        """Parser handles empty string."""
        result = parser.parse("")
        assert len(result.findings) == 0

    def test_normalize_finding_fail(self, parser):
        """normalize_finding handles FAIL status."""
        raw = {"id": "check-123", "status": "FAIL"}
        finding = parser.normalize_finding(raw)
        assert finding.id == "check-123"
        assert finding.severity == SeverityLevel.HIGH
        assert finding.raw == raw

    def test_normalize_finding_pass(self, parser):
        """normalize_finding handles PASS status."""
        raw = {"id": "check-456", "status": "PASS"}
        finding = parser.normalize_finding(raw)
        assert finding.id == "check-456"
        assert finding.severity == SeverityLevel.PASS

    def test_normalize_finding_preserves_raw(self, parser):
        """normalize_finding preserves original data in raw field."""
        raw = {
            "id": "check-789",
            "status": "FAIL",
            "extra_field": "extra_value",
            "nested": {"key": "value"},
        }
        finding = parser.normalize_finding(raw)
        assert finding.raw == raw
        assert finding.raw["extra_field"] == "extra_value"


class TestImports:
    def test_import_from_security_package(self):
        """BaseParser can be imported from parrot.tools.security."""
        from parrot.tools.security import BaseParser

        assert BaseParser is not None

    def test_import_from_base_parser_module(self):
        """BaseParser can be imported from base_parser module."""
        from parrot.tools.security.base_parser import BaseParser

        assert BaseParser is not None
