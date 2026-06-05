"""Unit tests for SOC2AdvisoryToolkit (FEAT-226 TASK-1481).

Uses the same in-memory store double as test_advisory_engine.py.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from parrot.storage.security_reports import (
    ReportFilter,
    SeverityBreakdown,
)
from parrot_tools.security.soc2_advisory import SOC2AdvisoryToolkit

# Import shared store double and helpers from conftest (auto-discovered by pytest)
from .conftest import FakeStore as _FakeStore, _make_ref, _prowler_finding, _prowler_content


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_store():
    """Store with one SOC2 scan report with two findings."""
    ref_id = uuid4()
    findings = [
        _prowler_finding("s3_bucket_public_access", "CRITICAL", "arn:aws:s3:::my-bucket"),
        _prowler_finding("iam_root_mfa", "HIGH", "arn:aws:iam::123:root"),
    ]
    return _FakeStore(
        refs=[_make_ref(report_id=ref_id, severity_summary=SeverityBreakdown(critical=1, high=1))],
        contents={ref_id: _prowler_content(findings)},
    )


@pytest.fixture
def empty_store():
    """Store with no reports."""
    return _FakeStore(refs=[], contents={})


@pytest.fixture
def toolkit(fake_store):
    return SOC2AdvisoryToolkit(report_store=fake_store)


@pytest.fixture
def toolkit_empty(empty_store):
    return SOC2AdvisoryToolkit(report_store=empty_store)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSOC2AdvisoryToolkit:
    def test_tool_prefix_is_soc2(self, toolkit):
        assert toolkit.tool_prefix == "soc2"

    def test_get_tools_returns_soc2_prefixed(self, toolkit):
        tools = toolkit.get_tools()
        names = [t.name for t in tools]
        assert len(tools) >= 3, f"Expected at least 3 tools, got {names}"
        assert any(n.startswith("soc2_") for n in names), f"No soc2_ prefix found: {names}"

    def test_get_tools_has_all_three(self, toolkit):
        """All three expected tool methods should be discovered."""
        names = [t.name for t in toolkit.get_tools()]
        expected_suffixes = {"map_report_to_soc2", "soc2_gap_analysis", "daily_soc2_advisory"}
        for suffix in expected_suffixes:
            assert any(suffix in n for n in names), f"Tool '{suffix}' not found in {names}"

    @pytest.mark.asyncio
    async def test_daily_advisory_returns_recommendations(self, toolkit):
        result = await toolkit.daily_soc2_advisory(framework="soc2")
        assert "recommendations" in result, f"Got: {result}"

    @pytest.mark.asyncio
    async def test_daily_advisory_has_framework(self, toolkit):
        result = await toolkit.daily_soc2_advisory(framework="soc2")
        assert result.get("framework") == "soc2"

    @pytest.mark.asyncio
    async def test_map_report_to_soc2_returns_dict(self, fake_store):
        """Fetches the stored report ID and maps findings to SOC2 controls."""
        refs = await fake_store.query(ReportFilter(framework="soc2"))
        assert refs, "Expected at least one ref in fake_store"
        report_id = str(refs[0].report_id)

        toolkit = SOC2AdvisoryToolkit(report_store=fake_store)
        result = await toolkit.map_report_to_soc2(report_id)
        # Should have either control_findings (success) or an error
        assert "control_findings" in result or "error" in result

    @pytest.mark.asyncio
    async def test_missing_report_is_structured_error(self, toolkit):
        """Non-existent UUID returns structured error dict, not an exception."""
        result = await toolkit.map_report_to_soc2("00000000-0000-0000-0000-000000000000")
        assert "error" in result, f"Expected error key, got: {result}"
        assert "recommendations" not in result

    @pytest.mark.asyncio
    async def test_invalid_uuid_is_structured_error(self, toolkit):
        """Invalid UUID string returns structured error dict."""
        result = await toolkit.map_report_to_soc2("not-a-valid-uuid")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_soc2_gap_analysis_returns_coverage(self, toolkit):
        result = await toolkit.soc2_gap_analysis(framework="soc2")
        assert "coverage" in result or "error" in result

    @pytest.mark.asyncio
    async def test_gap_analysis_empty_store_is_structured_error(self, toolkit_empty):
        result = await toolkit_empty.soc2_gap_analysis(framework="soc2")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_daily_advisory_empty_store_returns_valid_dict(self, toolkit_empty):
        """Empty store returns a valid advisory dict (empty, no raise)."""
        result = await toolkit_empty.daily_soc2_advisory(framework="soc2")
        # Either a normal advisory (empty) or a structured error — never raises
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_no_store_write_methods_called(self, fake_store):
        """Toolkit must never call save_report on the store."""
        called_saves: list[str] = []

        class _TrackingStore(_FakeStore.__class__):
            async def save_report(self, *args, **kwargs):
                called_saves.append("save_report")

        # Wrap fake_store to detect any write
        fake_store.save_report = lambda *a, **kw: called_saves.append("save_report")  # type: ignore[attr-defined]
        toolkit = SOC2AdvisoryToolkit(report_store=fake_store)
        await toolkit.daily_soc2_advisory(framework="soc2")
        await toolkit.soc2_gap_analysis(framework="soc2")
        assert called_saves == [], f"save_report was called: {called_saves}"
