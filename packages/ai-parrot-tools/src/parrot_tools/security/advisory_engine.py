"""SecurityAdvisoryEngine — day-over-day diff and SOC2 control mapping.

Pure-logic module: no LLM, no agent, no I/O beyond the injected store and
mapper.  The agent narrates the structured ``AdvisoryReport`` via its LLM.

Implements FEAT-226 spec §3 Module 1.
"""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from parrot.storage.security_reports import (
    ReportFilter,
    ReportKind,
    ReportRef,
    SecurityReportStore,
    SeverityBreakdown,
)
from parrot_tools.security.models import (
    ComparisonDelta,  # noqa: F401 — imported for caller convenience
    ComplianceFramework,
    FindingSource,
    SecurityFinding,
    SeverityLevel,
)
from parrot_tools.security.parsers import get_report_parser
from parrot_tools.security.reports import ComplianceMapper

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

_MATERIAL_SEVERITIES: frozenset[SeverityLevel] = frozenset(
    {SeverityLevel.CRITICAL, SeverityLevel.HIGH}
)


class FindingDelta(BaseModel):
    """Day-over-day change for a single finding (aligned to SecurityFinding).

    Attributes:
        finding_id: Unique finding identifier (SecurityFinding.id).
        status: Change classification — new, resolved, persisting, or
            severity_changed.
        severity: Current severity level (SeverityLevel value).
        previous_severity: Prior severity when status == 'severity_changed'.
        title: Short finding title.
        resource: Affected resource identifier (SecurityFinding.resource).
        check_id: Scanner-specific check ID (SecurityFinding.check_id).
        soc2_control_ids: SOC2 control IDs from ComplianceMapper.
    """

    finding_id: str
    status: Literal["new", "resolved", "persisting", "severity_changed"]
    severity: str
    previous_severity: str | None = None
    title: str
    resource: str | None = None
    check_id: str | None = None
    soc2_control_ids: list[str] = Field(default_factory=list)


class AdvisoryRecommendation(BaseModel):
    """One actionable recommendation tied to SOC2 controls.

    Attributes:
        title: Short recommendation title.
        severity: Severity level driving this recommendation.
        soc2_control_ids: SOC2 control IDs from ComplianceMapper.
        affected_resources: Resource identifiers affected.
        recommended_action: Concrete remediation step.
        is_material: True for new/severity-increased CRITICAL or HIGH
            findings; gates Jira ticket creation.
    """

    title: str
    severity: str
    soc2_control_ids: list[str]
    affected_resources: list[str] = Field(default_factory=list)
    recommended_action: str
    is_material: bool


class AdvisoryReport(BaseModel):
    """Structured day-over-day SOC2 advisory for one framework.

    No narrative: the agent's LLM writes prose from this model.

    Attributes:
        framework: Compliance framework identifier (e.g. ``'soc2'``).
        baseline_report_id: Prior-day report ID (``None`` on first run).
        current_report_id: ID of the most-recent report analysed.
        severity_delta: Signed severity counts (current − baseline).
        deltas: Per-finding delta records, sorted by severity desc then id.
        soc2_coverage: Output of ``ComplianceMapper.get_framework_coverage``.
        control_findings: Mapping of control_id → number of failing findings.
        recommendations: Actionable recommendations, material items first.
        provider: Cloud provider (recorded for the persisted ReportRef).
    """

    framework: str
    baseline_report_id: str | None
    current_report_id: str
    severity_delta: SeverityBreakdown
    deltas: list[FindingDelta]
    soc2_coverage: dict
    control_findings: dict[str, int]
    recommendations: list[AdvisoryRecommendation]
    provider: str = "aws"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEV_ORDER: dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "INFO": 0,
    "INFORMATIONAL": 0,
    "PASS": 0,
    "UNKNOWN": 0,
}


def _sev_rank(sev: str) -> int:
    """Return a sortable rank for a severity string (higher = worse)."""
    return _SEV_ORDER.get(sev.upper(), 0)


def _parse_findings(ref: ReportRef, content: bytes) -> list[SecurityFinding]:
    """Try to parse ``content`` into a list of SecurityFinding objects.

    The catalog-level parsers return ``ParsedReport`` with ``EmbeddedFinding``
    objects, not the richer ``SecurityFinding`` shape required by
    ``ComplianceMapper``.  We therefore call ``extract_section("full")``
    (returning raw scanner JSON) and reconstruct ``SecurityFinding`` objects.

    Degrades gracefully: if parsing fails or the scanner is unrecognised,
    returns an empty list so the caller falls back to severity-summary deltas.

    Args:
        ref: Report metadata (provides scanner name and framework).
        content: Raw scanner output bytes.

    Returns:
        Possibly-empty list of SecurityFinding objects.
    """
    logger = logging.getLogger(__name__)
    try:
        parser = get_report_parser(ref.scanner)
    except ValueError:
        logger.debug("No parser for scanner %r — skipping finding-level diff", ref.scanner)
        return []

    try:
        section = parser.extract_section(content, "full")
    except Exception as exc:
        logger.debug("extract_section failed for %s: %s", ref.scanner, exc)
        return []

    raw_findings: list[dict] = section.get("findings", [])
    if not raw_findings:
        return []

    # Determine the FindingSource from the scanner name
    _SCANNER_TO_SOURCE: dict[str, FindingSource] = {
        "prowler": FindingSource.PROWLER,
        "trivy": FindingSource.TRIVY,
        "checkov": FindingSource.CHECKOV,
        "cloudsploit": FindingSource.CLOUDSPLOIT,
        "scoutsuite": FindingSource.SCOUTSUITE,
    }
    source = _SCANNER_TO_SOURCE.get(ref.scanner.lower(), FindingSource.PROWLER)

    findings: list[SecurityFinding] = []
    for raw in raw_findings:
        if isinstance(raw, dict):
            try:
                # Normalise severity to SeverityLevel
                sev_raw = str(raw.get("severity") or "INFORMATIONAL").upper()
                try:
                    sev = SeverityLevel(sev_raw)
                except ValueError:
                    sev = SeverityLevel.UNKNOWN

                # Build a finding_id that matches what the catalog parser uses
                fi = raw.get("finding_info") or {}
                check_id = fi.get("uid") or raw.get("check_id") or ""
                resource_list = raw.get("resources") or [{}]
                resource_uid = resource_list[0].get("uid", "") if resource_list else ""
                region = resource_list[0].get("region", "global") if resource_list else "global"
                fid = (
                    f"{check_id}/{region}/{resource_uid}"
                    if resource_uid
                    else f"{check_id}/{region}"
                )
                title = (
                    fi.get("title")
                    or raw.get("check_title")
                    or raw.get("title")
                    or check_id
                )
                findings.append(
                    SecurityFinding(
                        id=fid or raw.get("id", f"finding-{len(findings)}"),
                        source=source,
                        severity=sev,
                        title=title,
                        description=raw.get("description"),
                        resource=resource_uid or None,
                        resource_type=raw.get("resource_type"),
                        check_id=check_id or None,
                        compliance_tags=raw.get("compliance_tags") or [],
                        remediation=raw.get("remediation"),
                        raw=raw,
                    )
                )
            except Exception as exc:
                logger.debug("Skipping malformed finding: %s", exc)
                continue
    return findings


def _build_severity_breakdown(findings: list[SecurityFinding]) -> SeverityBreakdown:
    """Aggregate SecurityFinding severities into a SeverityBreakdown.

    Args:
        findings: List of findings to count.

    Returns:
        SeverityBreakdown with counts per severity level.
    """
    counts: dict[str, int] = {
        "critical": 0, "high": 0, "medium": 0, "low": 0, "informational": 0
    }
    for f in findings:
        sev = f.severity.value.lower()
        if sev in counts:
            counts[sev] += 1
        else:
            counts["informational"] += 1
    return SeverityBreakdown(**counts)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class SecurityAdvisoryEngine:
    """Deterministic day-over-day security advisory engine.

    Given a ``SecurityReportStore`` and an optional ``ComplianceMapper``,
    fetches the two most-recent reports for a framework, diffs their findings,
    maps the delta to SOC2 controls via the existing ``ComplianceMapper``,
    and returns a structured ``AdvisoryReport`` Pydantic model.

    No narrative is written here — the caller's LLM generates prose.

    Example:
        engine = SecurityAdvisoryEngine(report_store=store)
        report = await engine.build_daily_advisory(framework="soc2")
    """

    def __init__(
        self,
        report_store: SecurityReportStore,
        mapper: ComplianceMapper | None = None,
    ) -> None:
        """Initialise the engine.

        Args:
            report_store: Catalog backend (query + fetch_content only).
            mapper: Optional pre-constructed ComplianceMapper; a fresh
                instance with default mappings_dir is created when None.
        """
        self._store = report_store
        self._mapper = mapper or ComplianceMapper()
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build_daily_advisory(
        self,
        *,
        framework: str,
        provider: str = "aws",
    ) -> AdvisoryReport:
        """Build a day-over-day SOC2 advisory for one framework.

        Queries the two most-recent SCAN-kind reports for ``framework``,
        diffs their findings, maps to SOC2 controls, and returns a fully
        structured ``AdvisoryReport``.

        First run (only one report exists): ``baseline_report_id`` is
        ``None`` and every finding is classified as ``"new"``.

        Args:
            framework: Compliance framework identifier (e.g. ``'soc2'``).
            provider: Cloud provider (e.g. ``'aws'``). Recorded on the
                returned ``AdvisoryReport`` for the caller's ``ReportRef``.

        Returns:
            An ``AdvisoryReport`` with signed severity delta, per-finding
            deltas classified by status, SOC2 coverage, and recommendations.
        """
        # 1. Fetch the two most-recent SCAN reports for this framework.
        refs = await self._store.query(
            ReportFilter(
                framework=framework,
                report_kind=ReportKind.SCAN,
                order_by="produced_at_desc",
                limit=2,
            )
        )

        if not refs:
            self.logger.info("No reports found for framework=%r; returning empty advisory", framework)
            return self._empty_advisory(framework, provider)

        current_ref = refs[0]
        baseline_ref: ReportRef | None = refs[1] if len(refs) >= 2 else None

        # 2. Parse findings from the current (and optionally baseline) report.
        current_findings = await self._load_findings(current_ref)
        baseline_findings: list[SecurityFinding] = []
        if baseline_ref is not None:
            baseline_findings = await self._load_findings(baseline_ref)

        # 3. Diff the findings.
        deltas = self._compute_deltas(
            current_findings=current_findings,
            baseline_findings=baseline_findings,
            mapper=self._mapper,
            framework=framework,
        )

        # 4. Signed severity delta (current − baseline).
        severity_delta = self._signed_severity_delta(
            current_ref=current_ref,
            baseline_ref=baseline_ref,
            current_findings=current_findings,
            baseline_findings=baseline_findings,
        )

        # 5. SOC2 coverage and control-level counts.
        cf_enum = ComplianceFramework.SOC2  # advisory is always SOC2-mapped
        soc2_coverage = self._mapper.get_framework_coverage(current_findings, cf_enum)
        control_findings = self._control_finding_counts(current_findings, cf_enum)

        # 6. Build recommendations.
        recommendations = self._build_recommendations(deltas)

        return AdvisoryReport(
            framework=framework,
            baseline_report_id=(
                str(baseline_ref.report_id) if baseline_ref is not None else None
            ),
            current_report_id=str(current_ref.report_id),
            severity_delta=severity_delta,
            deltas=sorted(
                deltas,
                key=lambda d: (-_sev_rank(d.severity), d.finding_id),
            ),
            soc2_coverage=soc2_coverage,
            control_findings=control_findings,
            recommendations=sorted(
                recommendations,
                key=lambda r: (-_sev_rank(r.severity), not r.is_material),
            ),
            provider=provider,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_findings(self, ref: ReportRef) -> list[SecurityFinding]:
        """Fetch and parse report content into SecurityFinding objects.

        Degrades to an empty list if content cannot be parsed (e.g. HTML-only
        report, unrecognised scanner).

        Args:
            ref: Report metadata record.

        Returns:
            Possibly-empty list of SecurityFinding objects.
        """
        try:
            content = await self._store.fetch_content(ref.report_id)
            return _parse_findings(ref, content)
        except Exception as exc:
            self.logger.warning(
                "Could not load findings from report %s (%s): %s",
                ref.report_id, ref.scanner, exc,
            )
            return []

    def _compute_deltas(
        self,
        *,
        current_findings: list[SecurityFinding],
        baseline_findings: list[SecurityFinding],
        mapper: ComplianceMapper,
        framework: str,
    ) -> list[FindingDelta]:
        """Classify findings as new / resolved / persisting / severity_changed.

        Keys findings by ``SecurityFinding.id``.

        Args:
            current_findings: Findings from the most-recent report.
            baseline_findings: Findings from the prior report (may be empty).
            mapper: ComplianceMapper instance for SOC2 control lookup.
            framework: Framework string (only ``"soc2"`` maps controls).

        Returns:
            List of FindingDelta objects (not yet sorted).
        """
        cf_enum = ComplianceFramework.SOC2
        baseline_by_id: dict[str, SecurityFinding] = {f.id: f for f in baseline_findings}
        current_by_id: dict[str, SecurityFinding] = {f.id: f for f in current_findings}

        deltas: list[FindingDelta] = []

        # New and persisting / severity_changed
        for fid, f in current_by_id.items():
            controls: list[str] = []
            try:
                controls = mapper.map_finding_to_controls(f, cf_enum)
            except Exception:
                pass

            if fid not in baseline_by_id:
                status: Literal["new", "resolved", "persisting", "severity_changed"] = "new"
                prev_sev = None
            else:
                b = baseline_by_id[fid]
                if f.severity != b.severity:
                    status = "severity_changed"
                    prev_sev = b.severity.value
                else:
                    status = "persisting"
                    prev_sev = None

            deltas.append(
                FindingDelta(
                    finding_id=fid,
                    status=status,
                    severity=f.severity.value,
                    previous_severity=prev_sev,
                    title=f.title,
                    resource=f.resource,
                    check_id=f.check_id,
                    soc2_control_ids=controls,
                )
            )

        # Resolved
        for fid, b in baseline_by_id.items():
            if fid not in current_by_id:
                controls = []
                try:
                    controls = mapper.map_finding_to_controls(b, cf_enum)
                except Exception:
                    pass

                deltas.append(
                    FindingDelta(
                        finding_id=fid,
                        status="resolved",
                        severity=b.severity.value,
                        title=b.title,
                        resource=b.resource,
                        check_id=b.check_id,
                        soc2_control_ids=controls,
                    )
                )

        return deltas

    def _signed_severity_delta(
        self,
        *,
        current_ref: ReportRef,
        baseline_ref: ReportRef | None,
        current_findings: list[SecurityFinding],
        baseline_findings: list[SecurityFinding],
    ) -> SeverityBreakdown:
        """Compute signed severity delta (current − baseline).

        Falls back to ``ReportRef.severity_summary`` when findings are not
        parseable (graceful degradation for HTML-only reports).

        Args:
            current_ref: Current report metadata (contains severity_summary).
            baseline_ref: Baseline report metadata (may be None).
            current_findings: Parsed current findings (may be empty).
            baseline_findings: Parsed baseline findings (may be empty).

        Returns:
            SeverityBreakdown with signed (possibly negative) counts.
        """
        if current_findings or baseline_findings:
            curr_bd = _build_severity_breakdown(current_findings)
            base_bd = (
                _build_severity_breakdown(baseline_findings)
                if baseline_findings
                else SeverityBreakdown()
            )
        else:
            # Degrade to severity_summary from ReportRef
            curr_bd = current_ref.severity_summary
            base_bd = (
                baseline_ref.severity_summary
                if baseline_ref is not None
                else SeverityBreakdown()
            )

        return SeverityBreakdown(
            critical=curr_bd.critical - base_bd.critical,
            high=curr_bd.high - base_bd.high,
            medium=curr_bd.medium - base_bd.medium,
            low=curr_bd.low - base_bd.low,
            informational=curr_bd.informational - base_bd.informational,
        )

    def _control_finding_counts(
        self,
        findings: list[SecurityFinding],
        framework: ComplianceFramework,
    ) -> dict[str, int]:
        """Count failing findings per control ID.

        Args:
            findings: Findings to analyse.
            framework: Compliance framework to map against.

        Returns:
            dict mapping control_id to the count of non-PASS findings.
        """
        counts: dict[str, int] = {}
        for f in findings:
            if f.severity in (SeverityLevel.PASS,):
                continue
            try:
                controls = self._mapper.map_finding_to_controls(f, framework)
            except Exception:
                controls = []
            for ctrl in controls:
                counts[ctrl] = counts.get(ctrl, 0) + 1
        return counts

    def _build_recommendations(
        self, deltas: list[FindingDelta]
    ) -> list[AdvisoryRecommendation]:
        """Derive actionable recommendations from finding deltas.

        One recommendation per distinct (title, severity) combination to avoid
        duplicates.  A recommendation is material when its status is ``new``
        or ``severity_changed`` AND the severity is CRITICAL or HIGH.

        Args:
            deltas: List of FindingDelta objects.

        Returns:
            List of AdvisoryRecommendation objects.
        """
        seen: set[tuple[str, str]] = set()
        recs: list[AdvisoryRecommendation] = []

        for d in sorted(
            deltas,
            key=lambda x: (-_sev_rank(x.severity), x.finding_id),
        ):
            if d.status == "resolved":
                continue  # resolved findings don't need action

            key = (d.title, d.severity)
            if key in seen:
                # Accumulate resource for the existing recommendation
                for rec in recs:
                    if rec.title == d.title and rec.severity == d.severity:
                        if d.resource and d.resource not in rec.affected_resources:
                            rec.affected_resources.append(d.resource)
                continue
            seen.add(key)

            is_material = (
                d.status in ("new", "severity_changed")
                and d.severity.upper() in {sl.value for sl in _MATERIAL_SEVERITIES}
            )

            recs.append(
                AdvisoryRecommendation(
                    title=d.title,
                    severity=d.severity,
                    soc2_control_ids=d.soc2_control_ids,
                    affected_resources=[d.resource] if d.resource else [],
                    recommended_action=(
                        f"Investigate and remediate {d.title} ({d.severity})."
                        " Review SOC2 controls: "
                        + (", ".join(d.soc2_control_ids) or "N/A")
                        + "."
                    ),
                    is_material=is_material,
                )
            )

        return recs

    def _empty_advisory(self, framework: str, provider: str) -> AdvisoryReport:
        """Return an empty advisory when no reports exist for a framework.

        Args:
            framework: Framework identifier.
            provider: Cloud provider.

        Returns:
            AdvisoryReport with all empty/zero fields and no current report.
        """
        return AdvisoryReport(
            framework=framework,
            baseline_report_id=None,
            current_report_id="none",
            severity_delta=SeverityBreakdown(),
            deltas=[],
            soc2_coverage={},
            control_findings={},
            recommendations=[],
            provider=provider,
        )
