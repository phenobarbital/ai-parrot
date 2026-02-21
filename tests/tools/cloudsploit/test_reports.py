"""Unit tests for CloudSploit report generator."""
import pytest
from datetime import datetime

from parrot.tools.cloudsploit.reports import ReportGenerator
from parrot.tools.cloudsploit.models import (
    ScanFinding,
    ScanSummary,
    ScanResult,
    SeverityLevel,
    ComparisonReport,
)


@pytest.fixture
def generator():
    return ReportGenerator()


@pytest.fixture
def scan_result():
    findings = [
        ScanFinding(
            plugin="ec2OpenSSH",
            category="EC2",
            title="Open SSH",
            status=SeverityLevel.FAIL,
            region="us-east-1",
            resource="arn:aws:ec2:us-east-1:123:sg/sg-abc",
            message="Unrestricted SSH access",
        ),
        ScanFinding(
            plugin="s3Encryption",
            category="S3",
            title="S3 Encryption",
            status=SeverityLevel.OK,
            region="global",
            resource="arn:aws:s3:::my-bucket",
            message="Encryption enabled",
        ),
        ScanFinding(
            plugin="iamRootAccess",
            category="IAM",
            title="Root Account Access",
            status=SeverityLevel.WARN,
            region="global",
            resource="root",
            message="Root account used recently",
        ),
    ]
    return ScanResult(
        findings=findings,
        summary=ScanSummary(
            total_findings=3,
            ok_count=1,
            warn_count=1,
            fail_count=1,
            unknown_count=0,
            categories={"EC2": 1, "S3": 1, "IAM": 1},
            scan_timestamp=datetime(2026, 2, 21, 10, 30, 0),
            duration_seconds=45.2,
        ),
    )


@pytest.fixture
def empty_result():
    return ScanResult(
        findings=[],
        summary=ScanSummary(
            total_findings=0,
            ok_count=0,
            warn_count=0,
            fail_count=0,
            unknown_count=0,
            scan_timestamp=datetime(2026, 2, 21, 10, 0, 0),
        ),
    )


@pytest.fixture
def comparison():
    return ComparisonReport(
        new_findings=[
            ScanFinding(
                plugin="newPlugin",
                category="IAM",
                title="New Issue",
                status=SeverityLevel.FAIL,
                region="global",
                message="Newly detected problem",
            ),
        ],
        resolved_findings=[
            ScanFinding(
                plugin="oldPlugin",
                category="S3",
                title="Old Issue",
                status=SeverityLevel.WARN,
                region="us-east-1",
                resource="arn:aws:s3:::old-bucket",
                message="Previously detected problem",
            ),
        ],
        unchanged_findings=[
            ScanFinding(
                plugin="stablePlugin",
                category="EC2",
                title="Stable Issue",
                status=SeverityLevel.FAIL,
                region="us-west-2",
                message="Still present",
            ),
        ],
        baseline_timestamp=datetime(2026, 2, 19, 10, 0, 0),
        current_timestamp=datetime(2026, 2, 21, 10, 0, 0),
    )


class TestHTMLReport:
    @pytest.mark.asyncio
    async def test_generates_html(self, generator, scan_result):
        html = await generator.generate_html(scan_result)
        assert "<html" in html
        assert "CloudSploit" in html

    @pytest.mark.asyncio
    async def test_contains_findings(self, generator, scan_result):
        html = await generator.generate_html(scan_result)
        assert "Open SSH" in html
        assert "FAIL" in html
        assert "S3 Encryption" in html
        assert "Root Account Access" in html

    @pytest.mark.asyncio
    async def test_contains_summary_cards(self, generator, scan_result):
        html = await generator.generate_html(scan_result)
        # Total findings count
        assert ">3<" in html
        # Individual severity counts
        assert ">1<" in html

    @pytest.mark.asyncio
    async def test_contains_categories(self, generator, scan_result):
        html = await generator.generate_html(scan_result)
        assert "EC2" in html
        assert "S3" in html
        assert "IAM" in html

    @pytest.mark.asyncio
    async def test_contains_severity_chart(self, generator, scan_result):
        html = await generator.generate_html(scan_result)
        assert "bar-chart" in html
        assert "bar-segment" in html

    @pytest.mark.asyncio
    async def test_contains_pass_rate(self, generator, scan_result):
        html = await generator.generate_html(scan_result)
        # 1 of 3 passed = 33.3%
        assert "33.3%" in html

    @pytest.mark.asyncio
    async def test_contains_scan_date(self, generator, scan_result):
        html = await generator.generate_html(scan_result)
        assert "2026-02-21" in html

    @pytest.mark.asyncio
    async def test_contains_duration(self, generator, scan_result):
        html = await generator.generate_html(scan_result)
        assert "45.2" in html

    @pytest.mark.asyncio
    async def test_findings_table_columns(self, generator, scan_result):
        html = await generator.generate_html(scan_result)
        # Table headers
        assert "Status" in html
        assert "Plugin" in html
        assert "Category" in html
        assert "Region" in html
        assert "Resource" in html
        assert "Message" in html

    @pytest.mark.asyncio
    async def test_saves_to_file(self, generator, scan_result, tmp_path):
        path = str(tmp_path / "report.html")
        result = await generator.generate_html(scan_result, output_path=path)
        assert result == path
        with open(path) as f:
            content = f.read()
            assert "<html" in content
            assert "Open SSH" in content

    @pytest.mark.asyncio
    async def test_empty_findings(self, generator, empty_result):
        html = await generator.generate_html(empty_result)
        assert "0" in html
        assert "No findings to display" in html

    @pytest.mark.asyncio
    async def test_severity_badges(self, generator, scan_result):
        html = await generator.generate_html(scan_result)
        assert "badge-fail" in html
        assert "badge-ok" in html
        assert "badge-warn" in html

    @pytest.mark.asyncio
    async def test_resource_none_shows_dash(self, generator):
        result = ScanResult(
            findings=[
                ScanFinding(
                    plugin="test",
                    category="EC2",
                    title="Test",
                    status=SeverityLevel.OK,
                    resource=None,
                ),
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
        html = await generator.generate_html(result)
        # The template uses '—' (em dash) for None resources
        assert "\u2014" in html


class TestHTMLPagination:
    @pytest.mark.asyncio
    async def test_large_result_set_paginated(self, generator):
        """Findings beyond max_findings should be truncated with a message."""
        findings = [
            ScanFinding(
                plugin=f"plugin-{i}",
                category="EC2",
                title=f"Finding {i}",
                status=SeverityLevel.WARN,
                region="us-east-1",
            )
            for i in range(1500)
        ]
        result = ScanResult(
            findings=findings,
            summary=ScanSummary(
                total_findings=1500,
                ok_count=0,
                warn_count=1500,
                fail_count=0,
                unknown_count=0,
                scan_timestamp=datetime.now(),
            ),
        )
        html = await generator.generate_html(result, max_findings=500)
        # Should contain the truncation notice
        assert "Showing 500 of 1500 findings" in html
        # Should NOT contain finding 999 (beyond limit)
        assert "Finding 999" not in html


class TestPDFReport:
    @pytest.mark.asyncio
    async def test_generates_pdf(self, generator, scan_result, tmp_path):
        path = str(tmp_path / "report.pdf")
        result = await generator.generate_pdf(scan_result, output_path=path)
        assert result == path
        with open(path, "rb") as f:
            header = f.read(4)
            assert header == b"%PDF"

    @pytest.mark.asyncio
    async def test_pdf_nonzero_size(self, generator, scan_result, tmp_path):
        path = str(tmp_path / "report.pdf")
        await generator.generate_pdf(scan_result, output_path=path)
        import os
        assert os.path.getsize(path) > 100

    @pytest.mark.asyncio
    async def test_pdf_empty_result(self, generator, empty_result, tmp_path):
        path = str(tmp_path / "report.pdf")
        result = await generator.generate_pdf(empty_result, output_path=path)
        assert result == path
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"


class TestComparisonReport:
    @pytest.mark.asyncio
    async def test_comparison_html(self, generator, comparison):
        html = await generator.generate_comparison_html(comparison)
        assert "New Issue" in html
        assert "Old Issue" in html
        assert "Stable Issue" in html

    @pytest.mark.asyncio
    async def test_comparison_contains_sections(self, generator, comparison):
        html = await generator.generate_comparison_html(comparison)
        assert "New Findings" in html
        assert "Resolved Findings" in html
        assert "Unchanged Findings" in html

    @pytest.mark.asyncio
    async def test_comparison_summary_cards(self, generator, comparison):
        html = await generator.generate_comparison_html(comparison)
        assert "New Issues" in html
        assert "Resolved" in html
        assert "Unchanged" in html

    @pytest.mark.asyncio
    async def test_comparison_timestamps(self, generator, comparison):
        html = await generator.generate_comparison_html(comparison)
        assert "2026-02-19" in html
        assert "2026-02-21" in html

    @pytest.mark.asyncio
    async def test_comparison_saves_to_file(self, generator, comparison, tmp_path):
        path = str(tmp_path / "comparison.html")
        result = await generator.generate_comparison_html(
            comparison, output_path=path
        )
        assert result == path
        with open(path) as f:
            assert "New Issue" in f.read()

    @pytest.mark.asyncio
    async def test_empty_comparison(self, generator):
        empty = ComparisonReport()
        html = await generator.generate_comparison_html(empty)
        assert "No findings to compare" in html

    @pytest.mark.asyncio
    async def test_comparison_pdf(self, generator, comparison, tmp_path):
        path = str(tmp_path / "comparison.pdf")
        result = await generator.generate_comparison_pdf(
            comparison, output_path=path
        )
        assert result == path
        with open(path, "rb") as f:
            assert f.read(4) == b"%PDF"
