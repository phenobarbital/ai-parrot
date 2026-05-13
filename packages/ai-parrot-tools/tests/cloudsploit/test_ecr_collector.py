"""Unit tests for EcrScanCollector (TASK-1120)."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.cloudsploit.ecr_collector import EcrScanCollector
from parrot_tools.cloudsploit.models import (
    EcrCollectionPlan,
    EcrRepoPlan,
    EcrSeverity,
)

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_payload():
    """One ECR finding with attributes (complete, first-match scenario)."""
    return {
        "repository_name": "alpha",
        "image_tag": "staging",
        "scan_status": "COMPLETE",
        "severity_counts": {"CRITICAL": 1},
        "findings": [
            {
                "name": "CVE-2024-0001",
                "severity": "CRITICAL",
                "description": "...",
                "uri": "https://example/cve",
                "attributes": [
                    {"key": "package_name", "value": "openssl"},
                    {"key": "package_version", "value": "1.1.1"},
                    {"key": "fixed_in_versions", "value": "1.1.1w"},
                    {"key": "CVSS3_SCORE", "value": "8.0"},
                    {"key": "CVSS4_SCORE", "value": "9.8"},
                ],
            },
        ],
        "findings_count": 1,
        "total_vulnerabilities": 1,
    }


@pytest.fixture
def not_found():
    """ECR wrapper response when ScanNotFoundException is raised."""
    return {"scan_status": "NOT_FOUND", "findings": [], "findings_count": 0}


@pytest.mark.asyncio
async def test_first_match_wins(sample_payload, not_found):
    """Staging NOT_FOUND → staging tried first, then production found; prod never called."""
    call_log: list[tuple] = []

    async def fake_call(repo, tag, include_attributes=False):
        call_log.append((repo, tag))
        if tag == "dev":
            return not_found
        return sample_payload

    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        side_effect=fake_call,
    ):
        plan = EcrCollectionPlan(
            region="us-east-2",
            concurrency=2,
            repos=[EcrRepoPlan(name="alpha", tags=["dev", "staging", "prod"])],
        )
        result = await collector.collect(plan)

    # dev tried (NOT_FOUND) then staging tried (hit); prod never called
    assert len(call_log) == 2
    assert call_log[0] == ("alpha", "dev")
    assert call_log[1] == ("alpha", "staging")
    assert result.repos[0].tag == "staging"


@pytest.mark.asyncio
async def test_all_tags_fail_goes_to_skipped(not_found):
    """When every tag for a repo returns NOT_FOUND, repo appears in skipped."""
    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        AsyncMock(return_value=not_found),
    ):
        plan = EcrCollectionPlan(
            region="us-east-2",
            repos=[EcrRepoPlan(name="zeta", tags=["a", "b"])],
        )
        result = await collector.collect(plan)

    assert result.repos == []
    assert len(result.skipped) == 1
    assert result.skipped[0]["repo"] == "zeta"


@pytest.mark.asyncio
async def test_cvss_v4_preferred_over_v3(sample_payload):
    """When both CVSS4_SCORE and CVSS3_SCORE are present, prefer v4."""
    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        AsyncMock(return_value=sample_payload),
    ):
        plan = EcrCollectionPlan(
            region="us-east-2",
            repos=[EcrRepoPlan(name="alpha", tags=["staging"])],
        )
        result = await collector.collect(plan)

    f = result.repos[0].findings[0]
    assert f.cvss == "9.8"  # CVSS4_SCORE wins
    assert f.package_name == "openssl"
    assert f.fixed_in_versions == "1.1.1w"


@pytest.mark.asyncio
async def test_bounded_concurrency(sample_payload):
    """With concurrency=2, never more than 2 ECR calls in flight."""
    inflight = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_call(*args, **kwargs):
        nonlocal inflight, peak
        async with lock:
            inflight += 1
            peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        async with lock:
            inflight -= 1
        return sample_payload

    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        side_effect=fake_call,
    ):
        plan = EcrCollectionPlan(
            region="us-east-2",
            concurrency=2,
            repos=[EcrRepoPlan(name=f"r{i}", tags=["staging"]) for i in range(8)],
        )
        await collector.collect(plan)

    assert peak <= 2, f"Peak concurrency {peak} exceeded limit 2"


@pytest.mark.asyncio
async def test_unknown_severity_maps_to_untriaged(sample_payload, caplog):
    """Unknown severity string → EcrSeverity.UNTRIAGED + warning log."""
    # Mutate the payload's finding severity to something unrecognised
    bad_payload = {
        **sample_payload,
        "findings": [
            {
                **sample_payload["findings"][0],
                "severity": "WEIRD",
            }
        ],
    }
    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        AsyncMock(return_value=bad_payload),
    ), caplog.at_level(logging.WARNING, logger="EcrScanCollector"):
        plan = EcrCollectionPlan(
            region="us-east-2",
            repos=[EcrRepoPlan(name="alpha", tags=["staging"])],
        )
        result = await collector.collect(plan)

    assert result.repos[0].findings[0].severity == EcrSeverity.UNTRIAGED
    assert any("WEIRD" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_generated_at_is_utc_aware(sample_payload):
    """EcrCollectionResult.generated_at is timezone-aware UTC."""
    import pytz  # noqa: F401 — just confirming it's not needed; use standard lib
    from datetime import timezone

    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        AsyncMock(return_value=sample_payload),
    ):
        plan = EcrCollectionPlan(
            region="us-east-2",
            repos=[EcrRepoPlan(name="alpha", tags=["staging"])],
        )
        result = await collector.collect(plan)

    assert result.generated_at.tzinfo is not None
    assert result.generated_at.tzinfo == timezone.utc


@pytest.mark.asyncio
async def test_repository_not_found_skips_repo(sample_payload, caplog):
    """A RepositoryNotFoundException for one repo skips it and lets the
    rest of the gather complete."""
    async def fake_call(repo, tag, include_attributes=False):
        if repo == "ghost":
            raise RuntimeError(
                "AWS ECR error (RepositoryNotFoundException): "
                "The repository with name 'ghost' does not exist"
            )
        return sample_payload

    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        side_effect=fake_call,
    ), caplog.at_level(logging.WARNING, logger="EcrScanCollector"):
        plan = EcrCollectionPlan(
            region="us-east-2",
            repos=[
                EcrRepoPlan(name="ghost", tags=["staging", "prod"]),
                EcrRepoPlan(name="alpha", tags=["staging"]),
            ],
        )
        result = await collector.collect(plan)

    assert [r.repo for r in result.repos] == ["alpha"]
    assert len(result.skipped) == 1
    assert result.skipped[0]["repo"] == "ghost"
    assert "not found" in result.skipped[0]["reason"].lower()


@pytest.mark.asyncio
async def test_ecr_error_on_tag_falls_through_to_next_tag(
    sample_payload, not_found, caplog,
):
    """A non-fatal RuntimeError on one tag logs a warning and tries the
    next tag in priority order."""
    async def fake_call(repo, tag, include_attributes=False):
        if tag == "dev":
            raise RuntimeError("AWS ECR error (ImageNotFoundException): no image")
        return sample_payload

    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        side_effect=fake_call,
    ), caplog.at_level(logging.WARNING, logger="EcrScanCollector"):
        plan = EcrCollectionPlan(
            region="us-east-2",
            repos=[EcrRepoPlan(name="alpha", tags=["dev", "staging"])],
        )
        result = await collector.collect(plan)

    assert result.repos[0].tag == "staging"
    assert any("ImageNotFoundException" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_fixture_file_loads_and_parses(sample_payload):
    """The anonymised fixture JSON can be parsed by the collector."""
    fixture_path = _FIXTURES / "ecr_describe_findings_sample.json"
    assert fixture_path.is_file(), f"Fixture missing: {fixture_path}"
    data = json.loads(fixture_path.read_text())

    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        AsyncMock(return_value=data),
    ):
        plan = EcrCollectionPlan(
            region="us-east-2",
            repos=[EcrRepoPlan(name="navigator-api-tf", tags=["staging"])],
        )
        result = await collector.collect(plan)

    assert result.repos[0].repo == "navigator-api-tf"
    assert EcrSeverity.CRITICAL in result.repos[0].counts
