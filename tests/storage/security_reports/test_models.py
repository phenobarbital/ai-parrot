"""Unit tests for parrot.storage.security_reports.models."""
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from parrot.storage.security_reports import (
    EmbeddedFinding,
    ReportFilter,
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)


class TestReportKind:
    def test_members(self):
        assert ReportKind.SCAN.value == "scan"
        assert ReportKind.DAILY_SUMMARY.value == "daily_summary"
        assert ReportKind.WEEKLY_SUMMARY.value == "weekly_summary"
        assert ReportKind.MONTHLY_SUMMARY.value == "monthly_summary"
        assert ReportKind.DRIFT_COMPARISON.value == "drift_comparison"

    def test_is_str_enum(self):
        assert isinstance(ReportKind.SCAN, str)
        assert ReportKind.SCAN == "scan"

    def test_reportkind_advisory_member(self):
        """FEAT-226: ADVISORY enum value added for SOC2 advisory outputs."""
        assert ReportKind.ADVISORY.value == "advisory"
        assert ReportKind("advisory") is ReportKind.ADVISORY


class TestSeverityBreakdown:
    def test_defaults_zero(self):
        s = SeverityBreakdown()
        assert s.critical == 0
        assert s.high == 0
        assert s.medium == 0
        assert s.low == 0
        assert s.informational == 0
        assert s.total == 0

    def test_total_sum(self):
        s = SeverityBreakdown(critical=1, high=2, medium=3, low=4, informational=5)
        assert s.total == 15

    def test_partial_fields(self):
        s = SeverityBreakdown(critical=1, high=2)
        assert s.total == 3
        assert s.medium == 0

    def test_total_is_property_not_field(self):
        # Ensure total is not serialized as a field (it's a property)
        s = SeverityBreakdown(critical=2, high=3)
        dumped = s.model_dump()
        assert "total" not in dumped
        assert dumped["critical"] == 2


class TestEmbeddedFinding:
    def test_required_fields(self):
        f = EmbeddedFinding(
            finding_id="F-001",
            severity="CRITICAL",
            title="Open port 22",
        )
        assert f.finding_id == "F-001"
        assert f.severity == "CRITICAL"
        assert f.title == "Open port 22"
        assert f.resource_id is None
        assert f.rule_id is None
        assert f.remediation_hint is None

    def test_optional_fields(self):
        f = EmbeddedFinding(
            finding_id="F-002",
            severity="HIGH",
            title="Weak password policy",
            resource_id="arn:aws:iam::123:policy/weak",
            rule_id="CIS-1.4",
            remediation_hint="Enable MFA",
        )
        assert f.resource_id == "arn:aws:iam::123:policy/weak"
        assert f.remediation_hint == "Enable MFA"

    def test_invalid_severity_raises(self):
        with pytest.raises(ValidationError):
            EmbeddedFinding(finding_id="F-003", severity="UNKNOWN", title="x")


class TestReportRef:
    def _make_ref(self, **kwargs) -> ReportRef:
        defaults = dict(
            report_kind=ReportKind.SCAN,
            scanner="cloudsploit",
            framework="HIPAA",
            provider="aws",
            scope={"account_id": "123456789012", "region": "us-east-1"},
            severity_summary=SeverityBreakdown(critical=2, high=5),
            uri="s3://bucket/key.json",
            produced_at=datetime.now(timezone.utc),
            produced_by="agent:test",
            parser_version="1.0.0",
        )
        defaults.update(kwargs)
        return ReportRef(**defaults)

    def test_roundtrip(self):
        ref = self._make_ref()
        clone = ReportRef.model_validate(ref.model_dump(mode="json"))
        assert clone.report_id == ref.report_id
        assert clone.severity_summary.total == 7
        assert clone.report_kind == ReportKind.SCAN

    def test_default_report_id_is_uuid(self):
        ref = self._make_ref()
        assert isinstance(ref.report_id, UUID)

    def test_default_top_findings_empty(self):
        ref = self._make_ref()
        assert ref.top_findings == []

    def test_default_retention_class(self):
        ref = self._make_ref()
        assert ref.retention_class == "compliance"

    def test_default_content_type(self):
        ref = self._make_ref()
        assert ref.content_type == "application/json"

    def test_framework_nullable(self):
        ref = self._make_ref(framework=None)
        assert ref.framework is None

    def test_with_top_findings(self):
        findings = [
            EmbeddedFinding(finding_id=f"F-{i}", severity="HIGH", title=f"Issue {i}")
            for i in range(3)
        ]
        ref = self._make_ref(top_findings=findings)
        assert len(ref.top_findings) == 3
        assert ref.top_findings[0].finding_id == "F-0"

    def test_report_kind_weekly_summary(self):
        ref = self._make_ref(
            report_kind=ReportKind.WEEKLY_SUMMARY,
            scanner="aggregator",
        )
        assert ref.report_kind == ReportKind.WEEKLY_SUMMARY


class TestReportFilter:
    def test_defaults(self):
        f = ReportFilter()
        # CRITICAL: no implicit age filter
        assert f.since is None
        assert f.until is None
        assert f.limit == 50
        assert f.order_by == "produced_at_desc"
        assert f.scanner is None
        assert f.framework is None
        assert f.provider is None
        assert f.report_kind is None
        assert f.scope_match is None

    def test_with_values(self):
        f = ReportFilter(
            scanner="trivy",
            framework="HIPAA",
            provider="aws",
            limit=10,
            order_by="produced_at_asc",
        )
        assert f.scanner == "trivy"
        assert f.limit == 10
        assert f.order_by == "produced_at_asc"

    def test_no_implicit_since_default(self):
        """Spec §5 hard requirement: store must NOT apply default age filter."""
        f = ReportFilter()
        assert f.since is None, (
            "ReportFilter.since must default to None — "
            "the store must return all reports without an implicit age filter"
        )
