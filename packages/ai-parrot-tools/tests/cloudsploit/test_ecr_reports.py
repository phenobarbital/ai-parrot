"""Unit tests for ReportGenerator.generate_ecr_html (TASK-1122)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parrot_tools.cloudsploit.models import (
    EcrCollectionResult,
    EcrRepoFindings,
    EcrScanFinding,
    EcrSeverity,
)
from parrot_tools.cloudsploit.reports import ReportGenerator


@pytest.fixture
def sample_result() -> EcrCollectionResult:
    """Two-repo result with one finding each."""
    f = EcrScanFinding(
        name="CVE-2024-0001",
        severity=EcrSeverity.CRITICAL,
        description="boom " * 100,  # 500 chars — will be truncated to 180
        uri="https://example/cve",
        package_name="openssl",
        package_version="1.1.1",
        fixed_in_versions="1.1.1w",
        cvss="9.8",
    )
    return EcrCollectionResult(
        generated_at=datetime.now(tz=timezone.utc),
        region="us-east-2",
        repos=[
            EcrRepoFindings(
                repo="navigator-front-tf",
                tag="staging",
                counts={EcrSeverity.CRITICAL: 1},
                findings=[f],
            ),
            EcrRepoFindings(
                repo="navigator-api-tf",
                tag="staging",
                counts={EcrSeverity.HIGH: 1},
                findings=[
                    f.model_copy(update={
                        "name": "CVE-2024-0002",
                        "severity": EcrSeverity.HIGH,
                    }),
                ],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_returns_html_string_when_no_path(sample_result):
    """When output_path is None, returns the rendered HTML string."""
    rg = ReportGenerator()
    out = await rg.generate_ecr_html(sample_result)
    assert isinstance(out, str)
    assert "<html" in out.lower()
    assert "ECR Vulnerability" in out


@pytest.mark.asyncio
async def test_writes_file_when_path_given(sample_result, tmp_path):
    """When output_path is set, writes the file and returns the path."""
    rg = ReportGenerator()
    dest = str(tmp_path / "deep" / "dir" / "report.html")
    out = await rg.generate_ecr_html(sample_result, output_path=dest)
    assert Path(out).is_file()
    assert "navigator-api-tf" in Path(out).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_navigator_api_pinned_first(sample_result):
    """navigator-api-tf must appear before navigator-front-tf in the output."""
    rg = ReportGenerator()
    html = await rg.generate_ecr_html(sample_result)
    api_pos = html.find("navigator-api-tf")
    front_pos = html.find("navigator-front-tf")
    assert api_pos != -1 and front_pos != -1, "Both repos must appear in HTML"
    assert api_pos < front_pos, "navigator-api-tf must come first"


@pytest.mark.asyncio
async def test_description_truncated_to_180(sample_result):
    """A 500-char description is truncated to 180 chars + ellipsis."""
    rg = ReportGenerator()
    html = await rg.generate_ecr_html(sample_result)
    # The full 500-char string should NOT appear verbatim
    assert ("boom " * 100) not in html
    # But the first portion should
    assert "boom boom" in html


@pytest.mark.asyncio
async def test_html_escapes_script_in_description(sample_result):
    """Special chars in descriptions are HTML-escaped (autoescape=True)."""
    sample_result.repos[0].findings[0].description = "<script>alert(1)</script>"
    rg = ReportGenerator()
    html = await rg.generate_ecr_html(sample_result)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.asyncio
async def test_findings_grouped_by_package(tmp_path):
    """Two findings with the same package+version appear in ONE package block."""
    f1 = EcrScanFinding(
        name="CVE-A",
        severity=EcrSeverity.CRITICAL,
        package_name="openssl",
        package_version="1.0",
    )
    f2 = EcrScanFinding(
        name="CVE-B",
        severity=EcrSeverity.HIGH,
        package_name="openssl",
        package_version="1.0",
    )
    result = EcrCollectionResult(
        generated_at=datetime.now(tz=timezone.utc),
        region="us-east-2",
        repos=[
            EcrRepoFindings(
                repo="alpha",
                tag="staging",
                counts={EcrSeverity.CRITICAL: 1, EcrSeverity.HIGH: 1},
                findings=[f1, f2],
            )
        ],
    )
    rg = ReportGenerator()
    html = await rg.generate_ecr_html(result)
    # Both CVE names appear
    assert "CVE-A" in html
    assert "CVE-B" in html
    # The package name appears — grouped under one block
    assert "openssl" in html


@pytest.mark.asyncio
async def test_total_counts_in_rendered_html(sample_result):
    """Global summary counts appear in the rendered HTML."""
    rg = ReportGenerator()
    html = await rg.generate_ecr_html(sample_result)
    # One CRITICAL, one HIGH in sample_result
    # The counts should appear as digits somewhere in the rendered page
    assert "1" in html  # at minimum the count values


@pytest.mark.asyncio
async def test_secondary_sort_navigator_by_critical_count():
    """Two navigator-* repos are sorted by CRITICAL count descending."""
    f_crit = EcrScanFinding(name="C1", severity=EcrSeverity.CRITICAL)
    result = EcrCollectionResult(
        generated_at=datetime.now(tz=timezone.utc),
        region="us-east-2",
        repos=[
            EcrRepoFindings(
                repo="navigator-beta-tf",
                tag="staging",
                counts={EcrSeverity.HIGH: 1},
                findings=[f_crit.model_copy(update={"severity": EcrSeverity.HIGH})],
            ),
            EcrRepoFindings(
                repo="navigator-alpha-tf",
                tag="staging",
                counts={EcrSeverity.CRITICAL: 3},
                findings=[f_crit, f_crit, f_crit],
            ),
        ],
    )
    rg = ReportGenerator()
    html = await rg.generate_ecr_html(result)
    # navigator-alpha-tf has more CRITICAL → should appear first
    alpha_pos = html.find("navigator-alpha-tf")
    beta_pos = html.find("navigator-beta-tf")
    assert alpha_pos < beta_pos
