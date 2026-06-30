"""Smoke tests for FEAT-226 public package exports (TASK-1483).

Verifies that advisory components are importable from the
``parrot_tools.security`` public surface without requiring any
external services (no AWS, no Postgres).
"""
from __future__ import annotations


def test_advisor_public_exports():
    """All FEAT-226 advisory symbols must be importable from parrot_tools.security."""
    from parrot_tools.security import (  # noqa: F401
        AdvisoryRecommendation,
        AdvisoryReport,
        FindingDelta,
        SecurityAdvisoryEngine,
        SOC2AdvisoryToolkit,
    )


def test_advisor_symbols_in_all():
    """New symbols must appear in parrot_tools.security.__all__."""
    import parrot_tools.security as sec

    expected = {
        "SecurityAdvisoryEngine",
        "AdvisoryReport",
        "FindingDelta",
        "AdvisoryRecommendation",
        "SOC2AdvisoryToolkit",
    }
    missing = expected - set(sec.__all__)
    assert not missing, f"Missing from __all__: {missing}"


def test_existing_exports_unchanged():
    """Pre-FEAT-226 exports must still be importable."""
    from parrot_tools.security import (  # noqa: F401
        CloudPostureToolkit,
        ComplianceMapper,
        ComplianceReportToolkit,
        ContainerSecurityToolkit,
        ProwlerConfig,
        ProwlerExecutor,
        ProwlerParser,
        ReportGenerator,
        SecurityFinding,
        SecretsIaCToolkit,
        SeverityLevel,
    )


def test_security_advisory_engine_is_class():
    from parrot_tools.security import SecurityAdvisoryEngine
    assert isinstance(SecurityAdvisoryEngine, type)


def test_advisory_report_is_pydantic_model():
    from parrot_tools.security import AdvisoryReport
    # Pydantic v2 models have model_fields
    assert hasattr(AdvisoryReport, "model_fields")


def test_soc2_advisory_toolkit_is_class():
    from parrot_tools.security import SOC2AdvisoryToolkit
    assert isinstance(SOC2AdvisoryToolkit, type)
