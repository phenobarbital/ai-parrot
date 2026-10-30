"""Tests for parrot_tools.security.cve.models."""

import pytest

from parrot_tools.security.cve.models import CVERecord, severity_from_score, validate_cve_id
from parrot_tools.security.models import SeverityLevel


def test_cve_id_validation():
    assert validate_cve_id("CVE-2026-98432") == "CVE-2026-98432"
    assert validate_cve_id("  CVE-2026-1234 ") == "CVE-2026-1234"
    for bad in ("cve-2026-1", "GHSA-xxxx-xxxx-xxxx", "CVE-26-1234", "cve-2026-98432", "CVE-2026-123"):
        with pytest.raises(ValueError):
            validate_cve_id(bad)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (10.0, SeverityLevel.CRITICAL),
        (9.0, SeverityLevel.CRITICAL),
        (8.99, SeverityLevel.HIGH),
        (7.0, SeverityLevel.HIGH),
        (6.99, SeverityLevel.MEDIUM),
        (4.0, SeverityLevel.MEDIUM),
        (3.99, SeverityLevel.LOW),
        (0.1, SeverityLevel.LOW),
        (0.0, SeverityLevel.INFO),
        (None, SeverityLevel.UNKNOWN),
    ],
)
def test_severity_boundaries(score, expected):
    assert severity_from_score(score) is expected


def test_record_defaults():
    rec = CVERecord(id="CVE-2026-98432")
    assert rec.severity is SeverityLevel.UNKNOWN
    assert rec.aliases == [] and rec.cvss == [] and rec.affected == [] and rec.sources == []
    assert rec.epss is None and rec.published is None
    assert rec.raw == {}
    other = CVERecord(id="CVE-2026-98433")
    other.aliases.append("GHSA-x")
    assert rec.aliases == []
