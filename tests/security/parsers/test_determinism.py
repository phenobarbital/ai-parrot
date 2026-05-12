"""Determinism and registry tests for the catalog-level scanner parsers."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot_tools.security.parsers import get_report_parser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "scanner,fixture",
    [
        ("trivy", "trivy_filesystem.json"),
        ("cloudsploit", "cloudsploit_hipaa.json"),
        ("prowler", "prowler_aws.json"),
        ("checkov", "checkov_terraform.json"),
        ("aggregator", "weekly_summary.json"),
    ],
)
def test_parse_is_deterministic(scanner: str, fixture: str) -> None:
    """Same bytes must produce identical ParsedReport on consecutive calls."""
    content = (FIXTURES / fixture).read_bytes()
    parser = get_report_parser(scanner)
    a = parser.parse(content)
    b = parser.parse(content)
    assert a.severity_summary == b.severity_summary, (
        f"{scanner}: severity_summary differed between runs"
    )
    assert [f.finding_id for f in a.top_findings] == [f.finding_id for f in b.top_findings], (
        f"{scanner}: top_findings order differed between runs"
    )


def test_unknown_scanner_raises() -> None:
    """get_report_parser with an unknown scanner must raise ValueError."""
    with pytest.raises(ValueError, match="No parser registered"):
        get_report_parser("nope")


def test_all_parsers_have_version() -> None:
    """Every registered parser must expose parser_version = '1.0.0'."""
    for scanner in ("trivy", "cloudsploit", "prowler", "checkov", "aggregator"):
        parser = get_report_parser(scanner)
        assert parser.parser_version == "1.0.0", (
            f"{scanner}: expected parser_version '1.0.0', got {parser.parser_version!r}"
        )


@pytest.mark.parametrize("scanner,fixture", [
    ("trivy", "trivy_filesystem.json"),
    ("cloudsploit", "cloudsploit_hipaa.json"),
    ("prowler", "prowler_aws.json"),
    ("checkov", "checkov_terraform.json"),
    ("aggregator", "weekly_summary.json"),
])
def test_top_findings_capped_at_10(scanner: str, fixture: str) -> None:
    """top_findings must never exceed 10 entries."""
    content = (FIXTURES / fixture).read_bytes()
    parsed = get_report_parser(scanner).parse(content)
    assert len(parsed.top_findings) <= 10, (
        f"{scanner}: expected <= 10 top_findings, got {len(parsed.top_findings)}"
    )


@pytest.mark.parametrize("scanner,fixture", [
    ("trivy", "trivy_filesystem.json"),
    ("cloudsploit", "cloudsploit_hipaa.json"),
    ("prowler", "prowler_aws.json"),
    ("checkov", "checkov_terraform.json"),
    ("aggregator", "weekly_summary.json"),
])
def test_extract_section_summary_matches_parse(scanner: str, fixture: str) -> None:
    """extract_section('summary') must match parse().severity_summary.model_dump()."""
    content = (FIXTURES / fixture).read_bytes()
    parser = get_report_parser(scanner)
    parsed = parser.parse(content)
    section = parser.extract_section(content, "summary")
    expected = parsed.severity_summary.model_dump()
    # Remove computed fields not stored as fields (e.g. total is a property)
    assert section["critical"] == expected["critical"]
    assert section["high"] == expected["high"]


def test_extract_section_critical_filters() -> None:
    """extract_section('critical') returns only CRITICAL findings."""
    content = (FIXTURES / "cloudsploit_hipaa.json").read_bytes()
    parser = get_report_parser("cloudsploit")
    section = parser.extract_section(content, "critical")
    findings = section.get("findings", [])
    for f in findings:
        assert f["severity"] == "CRITICAL", (
            f"Expected only CRITICAL findings, got {f['severity']!r}"
        )


def test_extract_section_invalid_raises() -> None:
    """extract_section with an unknown section name must raise ValueError."""
    content = (FIXTURES / "trivy_filesystem.json").read_bytes()
    parser = get_report_parser("trivy")
    with pytest.raises(ValueError, match="Unknown section"):
        parser.extract_section(content, "not-a-section")


def test_aggregator_executive_paragraph() -> None:
    """AggregatorParser.extract_section('executive') returns the paragraph."""
    content = (FIXTURES / "weekly_summary.json").read_bytes()
    parser = get_report_parser("aggregator")
    section = parser.extract_section(content, "executive")
    assert "paragraph" in section
    assert "critical" in section["paragraph"].lower()


def test_parse_from_path(tmp_path: Path) -> None:
    """Parsers must accept a Path as content argument."""
    import shutil
    fixture_path = FIXTURES / "trivy_filesystem.json"
    dest = tmp_path / "trivy_filesystem.json"
    shutil.copy(fixture_path, dest)

    parser = get_report_parser("trivy")
    parsed = parser.parse(dest)
    assert parsed.severity_summary.critical >= 0
