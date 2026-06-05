"""SOC2AdvisoryToolkit — LLM-facing read-only SOC2 advisory tools.

Wraps ``SecurityAdvisoryEngine`` and the existing ``ComplianceMapper`` as
agent-callable tools.  All tools return structured dicts; narrative is left
to the caller's LLM.  The store is required; the toolkit is strictly
read-only (never calls ``save_report`` or any write path).

Implements FEAT-226 spec §3 Module 2.
"""
from __future__ import annotations

import logging
from uuid import UUID

from parrot.storage.security_reports import (
    ReportFilter,
    ReportKind,
    SecurityReportStore,
)
from parrot_tools.security.advisory_engine import SecurityAdvisoryEngine
from parrot_tools.security.models import ComplianceFramework
from parrot_tools.security.reports import ComplianceMapper

from ..toolkit import AbstractToolkit


class SOC2AdvisoryToolkit(AbstractToolkit):
    """LLM-facing tools for SOC2-oriented security advisory.

    Provides three read-only tools (``soc2_`` prefix):

    - ``soc2_map_report_to_soc2`` — map a stored report's findings to
      SOC2 controls via ``ComplianceMapper.get_findings_by_control``.
    - ``soc2_soc2_gap_analysis`` — coverage + unmapped findings from the
      latest SCAN report for a framework.
    - ``soc2_daily_soc2_advisory`` — day-over-day diff advisory via
      ``SecurityAdvisoryEngine.build_daily_advisory``.

    All tools return JSON-serialisable dicts.  On error they return
    ``{"error": "...", "hint": "..."}`` and never raise to the LLM.

    Args:
        report_store: Required catalog backend (read-only).
        mapper: Optional ``ComplianceMapper``; a fresh default instance
            is created when not provided.
        **kwargs: Forwarded to ``AbstractToolkit.__init__``.
    """

    tool_prefix: str = "soc2"

    def __init__(
        self,
        report_store: SecurityReportStore,
        mapper: ComplianceMapper | None = None,
        **kwargs,
    ) -> None:
        """Initialise SOC2AdvisoryToolkit.

        Args:
            report_store: Required catalog backend.
            mapper: Optional ComplianceMapper; defaults to
                ``ComplianceMapper()`` with the package's bundled YAML files.
            **kwargs: Forwarded to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self._store = report_store
        self._mapper = mapper or ComplianceMapper()
        self._engine = SecurityAdvisoryEngine(report_store, self._mapper)
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public async methods — auto-discovered as agent tools (soc2_ prefix)
    # ------------------------------------------------------------------

    async def map_report_to_soc2(self, report_id: str) -> dict:
        """Map findings from a stored report to SOC2 Trust Service Criteria.

        Fetches the report, parses its findings, and groups them by SOC2
        control ID using ``ComplianceMapper.get_findings_by_control``.
        Also returns overall SOC2 coverage metrics.

        Args:
            report_id: UUID string of the stored report to analyse.

        Returns:
            Dict with keys:
                - ``control_findings``: mapping of control_id →
                  list of finding summaries.
                - ``coverage``: SOC2 coverage metrics dict from
                  ``ComplianceMapper.get_framework_coverage``.
                - ``report_id``: the analysed report UUID string.
            On error: ``{"error": "...", "hint": "..."}``.
        """
        try:
            uid = UUID(report_id)
        except (ValueError, AttributeError):
            return {
                "error": f"Invalid report_id: {report_id!r}",
                "hint": "Provide a valid UUID string.",
            }

        try:
            ref = await self._store.get(uid)
        except Exception as exc:
            return {
                "error": f"Could not retrieve report {report_id}: {exc}",
                "hint": "Check that the report exists in the catalog.",
            }

        if ref is None:
            return {
                "error": f"Report {report_id} not found in catalog.",
                "hint": "Use soc2_daily_soc2_advisory or find_security_report to locate valid report IDs.",
            }

        # Fetch and parse findings
        try:
            content = await self._store.fetch_content(uid)
        except Exception as exc:
            return {
                "error": f"Could not fetch content for report {report_id}: {exc}",
                "hint": "The report may not have stored content.",
            }

        from parrot_tools.security.advisory_engine import _parse_findings  # local import
        findings = _parse_findings(ref, content)

        if not findings:
            return {
                "error": "No parseable findings in report.",
                "hint": "The report may be HTML-only or use an unsupported format.",
                "report_id": report_id,
                "coverage": {},
                "control_findings": {},
            }

        cf = ComplianceFramework.SOC2
        findings_by_control = self._mapper.get_findings_by_control(findings, cf)
        coverage = self._mapper.get_framework_coverage(findings, cf)

        return {
            "report_id": report_id,
            "control_findings": {
                ctrl: [
                    {
                        "id": f.id,
                        "title": f.title,
                        "severity": f.severity.value,
                        "resource": f.resource,
                    }
                    for f in flist
                ]
                for ctrl, flist in findings_by_control.items()
            },
            "coverage": coverage,
        }

    async def soc2_gap_analysis(self, framework: str = "soc2") -> dict:
        """Analyse SOC2 coverage gaps from the latest report for a framework.

        Queries the most-recent SCAN report and returns:
        - SOC2 coverage metrics (what % of controls were checked).
        - List of unmapped findings (findings with no SOC2 control mapping).

        Args:
            framework: Compliance framework to analyse. Defaults to
                ``"soc2"`` — the primary framework for this toolkit.

        Returns:
            Dict with keys:
                - ``coverage``: coverage metrics from
                  ``ComplianceMapper.get_framework_coverage``.
                - ``unmapped_findings``: list of finding summaries with no
                  SOC2 control mapping.
                - ``framework``: the framework analysed.
            On error: ``{"error": "...", "hint": "..."}``.
        """
        try:
            refs = await self._store.query(
                ReportFilter(
                    framework=framework,
                    report_kind=ReportKind.SCAN,
                    order_by="produced_at_desc",
                    limit=1,
                )
            )
        except Exception as exc:
            return {
                "error": f"Store query failed: {exc}",
                "hint": "Check catalog connectivity.",
            }

        if not refs:
            return {
                "error": f"No SCAN reports found for framework={framework!r}.",
                "hint": "Run the SecurityAgent to produce reports first.",
                "framework": framework,
            }

        ref = refs[0]
        try:
            content = await self._store.fetch_content(ref.report_id)
        except Exception as exc:
            return {
                "error": f"Could not fetch content for latest report: {exc}",
                "hint": "The report may not have stored content.",
                "framework": framework,
            }

        from parrot_tools.security.advisory_engine import _parse_findings
        findings = _parse_findings(ref, content)

        cf = ComplianceFramework.SOC2
        coverage = self._mapper.get_framework_coverage(findings, cf)
        unmapped = self._mapper.get_unmapped_findings(findings, cf)

        return {
            "framework": framework,
            "report_id": str(ref.report_id),
            "coverage": coverage,
            "unmapped_findings": [
                {
                    "id": f.id,
                    "title": f.title,
                    "severity": f.severity.value,
                    "resource": f.resource,
                }
                for f in unmapped
            ],
        }

    async def daily_soc2_advisory(
        self, framework: str = "soc2", provider: str = "aws"
    ) -> dict:
        """Produce a day-over-day SOC2 advisory for a framework.

        Delegates to ``SecurityAdvisoryEngine.build_daily_advisory`` and
        returns the ``AdvisoryReport`` as a JSON-serialisable dict.

        Args:
            framework: Compliance framework identifier. Defaults to
                ``"soc2"``.
            provider: Cloud provider. Defaults to ``"aws"``.

        Returns:
            JSON-serialisable dict of ``AdvisoryReport.model_dump``.
            On error: ``{"error": "...", "hint": "..."}``.
        """
        try:
            report = await self._engine.build_daily_advisory(
                framework=framework, provider=provider
            )
            return report.model_dump(mode="json")
        except Exception as exc:
            self.logger.exception("daily_soc2_advisory failed: %s", exc)
            return {
                "error": f"Advisory generation failed: {exc}",
                "hint": "Check that at least one SCAN report exists for the framework.",
                "framework": framework,
            }
