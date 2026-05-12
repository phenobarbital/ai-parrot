"""Catalog-level scanner parser registry.

Usage::

    from parrot_tools.security.parsers import get_report_parser, ParsedReport, ReportParser

    parser = get_report_parser("trivy")
    report = parser.parse(b"...trivy json...")
    summary = report.severity_summary
    top10 = report.top_findings
"""
from __future__ import annotations

from ._types import ParsedReport, ReportParser
from .aggregator import AggregatorParser
from .checkov import CheckovParser
from .cloudsploit import CloudSploitParser
from .prowler import ProwlerParser
from .trivy import TrivyParser

# Registry of singleton parser instances keyed by scanner name.
_REGISTRY: dict[str, ReportParser] = {
    "trivy": TrivyParser(),  # type: ignore[assignment]
    "cloudsploit": CloudSploitParser(),  # type: ignore[assignment]
    "prowler": ProwlerParser(),  # type: ignore[assignment]
    "checkov": CheckovParser(),  # type: ignore[assignment]
    "aggregator": AggregatorParser(),  # type: ignore[assignment]
}


def get_report_parser(scanner: str) -> ReportParser:
    """Return the parser registered for the given scanner name.

    Args:
        scanner: One of ``"trivy"``, ``"cloudsploit"``, ``"prowler"``,
            ``"checkov"``, ``"aggregator"``.

    Returns:
        A :class:`ReportParser` instance for the requested scanner.

    Raises:
        ValueError: If no parser is registered for the given scanner name.
    """
    try:
        return _REGISTRY[scanner]
    except KeyError as exc:
        raise ValueError(
            f"No parser registered for scanner: {scanner!r}. "
            f"Available scanners: {sorted(_REGISTRY)}"
        ) from exc


__all__ = [
    "get_report_parser",
    "ParsedReport",
    "ReportParser",
    "TrivyParser",
    "CloudSploitParser",
    "ProwlerParser",
    "CheckovParser",
    "AggregatorParser",
]
