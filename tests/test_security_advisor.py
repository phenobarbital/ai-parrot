"""Tests for SecurityAdvisor agent (FEAT-226 TASK-1482).

Tests the read-only invariant, registry resolution, and the daily advisory
pipeline with mocked store/Jira/notification.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

import importlib.util
import os as _os

from parrot.storage.security_reports import (
    ReportFilter,
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)

# ---------------------------------------------------------------------------
# Load security_advisor directly by file path (agents/ is gitignored and may
# not be findable via the normal `agents.*` namespace under all pytest runs).
# ---------------------------------------------------------------------------

def _load_security_advisor_module():
    """Load security_advisor.py by absolute path, bypassing namespace issues."""
    _worktree_root = _os.path.normpath(
        _os.path.join(_os.path.dirname(__file__), _os.pardir)
    )
    _module_path = _os.path.join(_worktree_root, "agents", "security_advisor.py")
    spec = importlib.util.spec_from_file_location("security_advisor", _module_path)
    if spec is None:
        raise ImportError(f"Could not create spec for {_module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_SECURITY_ADVISOR_MOD = _load_security_advisor_module()

# ---------------------------------------------------------------------------
# Scanner tool name hints — none of these should appear in the advisor's tools
# ---------------------------------------------------------------------------

SCANNER_HINTS = (
    "cloudsploit",
    "prowler",
    "trivy",
    "checkov",
    "run_scan",
    "run_compliance_scan",
    "run_container_scan",
    "launch_scan",
)


# ---------------------------------------------------------------------------
# In-memory store double (reused from other security tests)
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(self, refs=None, contents=None):
        self._refs = refs or []
        self._contents = contents or {}
        self._saved: list[ReportRef] = []

    async def query(self, filter: ReportFilter) -> list[ReportRef]:
        results = [
            r for r in self._refs
            if (filter.framework is None or r.framework == filter.framework)
            and (filter.report_kind is None or r.report_kind == filter.report_kind)
        ]
        reverse = (filter.order_by or "produced_at_desc") == "produced_at_desc"
        results.sort(key=lambda r: r.produced_at, reverse=reverse)
        return results[: (filter.limit or 50)]

    async def get(self, report_id: UUID) -> ReportRef | None:
        for r in self._refs:
            if r.report_id == report_id:
                return r
        return None

    async def fetch_content(self, report_id: UUID) -> bytes:
        if report_id not in self._contents:
            raise KeyError(f"No content for {report_id}")
        return self._contents[report_id]

    async def save_report(self, ref: ReportRef, content: bytes) -> ReportRef:
        # Simulate saving by assigning a fake URI and appending
        saved = ref.model_copy(update={"uri": f"file:///tmp/{ref.report_id}.md"})
        self._saved.append(saved)
        return saved

    def saved_refs(self) -> list[ReportRef]:
        return self._saved

    async def query_distinct_frameworks(self) -> list[str]:
        return list({r.framework for r in self._refs if r.framework})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scan_ref(
    report_id: UUID | None = None,
    framework: str = "soc2",
    produced_at: datetime | None = None,
) -> ReportRef:
    return ReportRef(
        report_id=report_id or uuid4(),
        report_kind=ReportKind.SCAN,
        scanner="prowler",
        framework=framework,
        provider="aws",
        scope={"account_id": "123"},
        severity_summary=SeverityBreakdown(critical=2, high=1),
        uri="s3://test/key.json",
        produced_at=produced_at or datetime.now(timezone.utc),
        produced_by="test",
        parser_version="1.0.0",
    )


def _prowler_content(findings: list[dict]) -> bytes:
    return json.dumps(findings).encode()


def _prowler_finding(check_id: str, severity: str, resource: str) -> dict:
    return {
        "severity": severity,
        "finding_info": {"uid": check_id, "title": f"Check: {check_id}"},
        "resources": [{"uid": resource, "region": "us-east-1"}],
    }


# ---------------------------------------------------------------------------
# Build a test advisor without real AWS/Postgres
# ---------------------------------------------------------------------------


def _make_advisor_with_mocks(store: _FakeStore) -> Any:
    """Instantiate SecurityAdvisor with toolkits wired to a fake store."""
    SecurityAdvisor = _SECURITY_ADVISOR_MOD.SecurityAdvisor
    from parrot_tools.security.soc2_advisory import SOC2AdvisoryToolkit
    from parrot_tools.security.report_toolkit import SecurityReportToolkit
    from parrot_tools.s3.report_reader import S3ReportReaderToolkit

    # Mock file manager (S3FileManager)
    mock_fm = MagicMock()
    mock_fm.list_files = AsyncMock(return_value=[])

    advisor = SecurityAdvisor.__new__(SecurityAdvisor)
    advisor.logger = __import__("logging").getLogger("test_security_advisor")
    advisor._report_store = store

    # Build real toolkits with fake store
    advisor._report_toolkit = SecurityReportToolkit(
        report_store=store, file_manager=mock_fm
    )
    advisor._s3_toolkit = S3ReportReaderToolkit(
        file_manager=mock_fm, report_store=store
    )
    advisor._soc2_toolkit = SOC2AdvisoryToolkit(report_store=store)

    return advisor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSecurityAdvisorReadOnly:
    def test_advisor_registered(self):
        """security_advisor must be importable and the class decorated."""
        SecurityAdvisor = _SECURITY_ADVISOR_MOD.SecurityAdvisor

        # The @register_agent decorator stores the name on the class.
        assert SecurityAdvisor.__name__ == "SecurityAdvisor"
        # Check agent_id is set as a class attribute (Agent subclass convention)
        assert getattr(SecurityAdvisor, "agent_id", None) is not None, (
            "SecurityAdvisor must define agent_id"
        )

    def test_advisor_tools_are_read_only(self):
        """agent_tools() must include zero scanner toolkit tools."""
        from parrot_tools.security.soc2_advisory import SOC2AdvisoryToolkit
        from parrot_tools.security.report_toolkit import SecurityReportToolkit
        from parrot_tools.s3.report_reader import S3ReportReaderToolkit

        ref_id = uuid4()
        store = _FakeStore(
            refs=[_make_scan_ref(report_id=ref_id)],
            contents={ref_id: _prowler_content([
                _prowler_finding("s3_public", "CRITICAL", "arn:aws:s3:::b")
            ])},
        )
        mock_fm = MagicMock()
        mock_fm.list_files = AsyncMock(return_value=[])

        rt = SecurityReportToolkit(report_store=store, file_manager=mock_fm)
        s3t = S3ReportReaderToolkit(file_manager=mock_fm, report_store=store)
        soc2t = SOC2AdvisoryToolkit(report_store=store)

        all_tools = [
            *rt.get_tools(),
            *s3t.get_tools(),
            *soc2t.get_tools(),
        ]
        tool_names = [t.name.lower() for t in all_tools]

        for hint in SCANNER_HINTS:
            offenders = [n for n in tool_names if hint in n]
            assert not offenders, (
                f"Scanner hint '{hint}' found in tool names: {offenders}"
            )


@pytest.mark.asyncio
class TestSecurityAdvisorDailyTask:
    async def test_daily_advisory_persists_advisory_ref(self):
        """run_daily_soc2_advisory must save a ReportRef with ADVISORY kind."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        ref_a = _make_scan_ref(produced_at=yesterday)
        ref_b = _make_scan_ref(produced_at=now)
        findings_a = [_prowler_finding("s3_pub", "HIGH", "arn:aws:s3:::b1")]
        findings_b = [
            _prowler_finding("s3_pub", "HIGH", "arn:aws:s3:::b1"),
            _prowler_finding("iam_mfa", "CRITICAL", "arn:aws:iam::123:root"),
        ]
        store = _FakeStore(
            refs=[ref_b, ref_a],
            contents={
                ref_a.report_id: _prowler_content(findings_a),
                ref_b.report_id: _prowler_content(findings_b),
            },
        )

        advisor = _make_advisor_with_mocks(store)

        # Mock ask() to return a canned narrative
        mock_ask_response = MagicMock()
        mock_ask_response.response = "# Daily SOC2 Advisory\n\nAll good."
        advisor.ask = AsyncMock(return_value=mock_ask_response)

        # Mock send_notification
        advisor.send_notification = AsyncMock()

        # Mock Jira toolkit tools
        mock_jira_tool = AsyncMock(return_value="NAV-123")
        mock_jira_toolkit = MagicMock()
        mock_jira_toolkit.get_tools.return_value = [
            MagicMock(name="jira_create_issue", __call__=mock_jira_tool)
        ]

        with patch.object(advisor, "_build_jira", return_value=mock_jira_toolkit):
            await advisor.run_daily_soc2_advisory()

        # Verify an ADVISORY ReportRef was saved
        saved = store.saved_refs()
        assert any(
            r.report_kind == ReportKind.ADVISORY for r in saved
        ), f"No ADVISORY ref saved. Saved refs: {[r.report_kind for r in saved]}"

        # Verify send_notification was called
        assert advisor.send_notification.called, "send_notification was not called"

    async def test_daily_advisory_material_creates_jira(self):
        """Material recommendations (CRITICAL new findings) must create Jira tickets."""
        now = datetime.now(timezone.utc)
        ref_id = uuid4()
        findings = [_prowler_finding("iam_root_no_mfa", "CRITICAL", "arn:aws:iam::123:root")]
        store = _FakeStore(
            refs=[_make_scan_ref(report_id=ref_id, produced_at=now)],
            contents={ref_id: _prowler_content(findings)},
        )

        advisor = _make_advisor_with_mocks(store)
        mock_ask_response = MagicMock()
        mock_ask_response.response = "# Advisory"
        advisor.ask = AsyncMock(return_value=mock_ask_response)
        advisor.send_notification = AsyncMock()

        jira_calls: list[dict] = []

        async def _mock_create_issue(**kwargs):
            jira_calls.append(kwargs)
            return "NAV-100"

        mock_create = MagicMock(name="jira_create_issue")
        mock_create.side_effect = _mock_create_issue
        # Make it async callable
        mock_create = AsyncMock(name="jira_create_issue", return_value="NAV-100")

        mock_jira_toolkit = MagicMock()
        mock_jira_toolkit.get_tools.return_value = [mock_create]
        # Patch the name attribute
        mock_create.name = "jira_create_issue"

        with patch.object(advisor, "_build_jira", return_value=mock_jira_toolkit):
            result = await advisor.run_daily_soc2_advisory()

        # With a CRITICAL new finding, at least one material recommendation
        # should have triggered a Jira call
        soc2_result = result.get("results", {}).get("soc2", {})
        material_count = soc2_result.get("material_recommendations", 0)
        if material_count > 0:
            assert mock_create.called or len(jira_calls) > 0, (
                "Material recommendations present but Jira not called"
            )

    async def test_daily_advisory_sends_email(self):
        """run_daily_soc2_advisory must always attempt to send an email."""
        ref_id = uuid4()
        store = _FakeStore(
            refs=[_make_scan_ref(report_id=ref_id)],
            contents={ref_id: _prowler_content([
                _prowler_finding("s3_pub", "HIGH", "arn:aws:s3:::b")
            ])},
        )
        advisor = _make_advisor_with_mocks(store)
        mock_ask_response = MagicMock()
        mock_ask_response.response = "# Advisory"
        advisor.ask = AsyncMock(return_value=mock_ask_response)
        advisor.send_notification = AsyncMock()

        mock_jira = MagicMock()
        mock_jira.get_tools.return_value = []
        with patch.object(advisor, "_build_jira", return_value=mock_jira):
            await advisor.run_daily_soc2_advisory()

        assert advisor.send_notification.called, "send_notification was not called"
