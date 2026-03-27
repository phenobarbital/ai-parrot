"""Tests for CloudSploit scan comparator."""
import pytest
from datetime import datetime
from parrot.tools.cloudsploit.comparator import ScanComparator
from parrot.tools.cloudsploit.models import (
    ScanFinding, ScanSummary, ScanResult, SeverityLevel,
)


def make_finding(
    plugin: str, region: str, status: SeverityLevel, resource: str = None
):
    return ScanFinding(
        plugin=plugin, category="EC2", title=plugin,
        status=status, region=region, resource=resource,
    )


def make_result(findings: list) -> ScanResult:
    summary = ScanSummary(
        total_findings=len(findings),
        ok_count=sum(1 for f in findings if f.status == SeverityLevel.OK),
        warn_count=sum(1 for f in findings if f.status == SeverityLevel.WARN),
        fail_count=sum(1 for f in findings if f.status == SeverityLevel.FAIL),
        unknown_count=0,
        scan_timestamp=datetime.now(),
    )
    return ScanResult(findings=findings, summary=summary)


@pytest.fixture
def comparator():
    return ScanComparator()


class TestComparison:
    def test_new_findings(self, comparator):
        baseline = make_result([make_finding("pluginA", "us-east-1", SeverityLevel.FAIL)])
        current = make_result([
            make_finding("pluginA", "us-east-1", SeverityLevel.FAIL),
            make_finding("pluginB", "us-west-2", SeverityLevel.WARN),
        ])
        report = comparator.compare(baseline, current)
        assert len(report.new_findings) == 1
        assert report.new_findings[0].plugin == "pluginB"

    def test_resolved_findings(self, comparator):
        baseline = make_result([
            make_finding("pluginA", "us-east-1", SeverityLevel.FAIL),
            make_finding("pluginB", "us-west-2", SeverityLevel.WARN),
        ])
        current = make_result([make_finding("pluginA", "us-east-1", SeverityLevel.FAIL)])
        report = comparator.compare(baseline, current)
        assert len(report.resolved_findings) == 1
        assert report.resolved_findings[0].plugin == "pluginB"

    def test_unchanged_findings(self, comparator):
        finding = make_finding("pluginA", "us-east-1", SeverityLevel.FAIL)
        baseline = make_result([finding])
        current = make_result([finding])
        report = comparator.compare(baseline, current)
        assert len(report.unchanged_findings) == 1

    def test_empty_scans(self, comparator):
        empty = make_result([])
        report = comparator.compare(empty, empty)
        assert len(report.new_findings) == 0
        assert len(report.resolved_findings) == 0

    def test_severity_changed(self, comparator):
        baseline = make_result([
            make_finding("pluginA", "us-east-1", SeverityLevel.WARN),
        ])
        current = make_result([
            make_finding("pluginA", "us-east-1", SeverityLevel.FAIL),
        ])
        report = comparator.compare(baseline, current)
        assert len(report.unchanged_findings) == 0
        assert len(report.severity_changed) == 1
        assert report.severity_changed[0]["old_severity"] == "WARN"
        assert report.severity_changed[0]["new_severity"] == "FAIL"

    def test_resource_none_handling(self, comparator):
        """Findings with None resource should match each other."""
        baseline = make_result([
            make_finding("pluginA", "us-east-1", SeverityLevel.FAIL, resource=None),
        ])
        current = make_result([
            make_finding("pluginA", "us-east-1", SeverityLevel.FAIL, resource=None),
        ])
        report = comparator.compare(baseline, current)
        assert len(report.unchanged_findings) == 1
        assert len(report.new_findings) == 0

    def test_timestamps_populated(self, comparator):
        baseline = make_result([])
        current = make_result([])
        report = comparator.compare(baseline, current)
        assert report.baseline_timestamp is not None
        assert report.current_timestamp is not None
