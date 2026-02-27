"""Compliance Report Toolkit — Multi-scanner orchestration and reporting.

Agent-facing toolkit that orchestrates all security scanners (Prowler, Trivy, Checkov)
and produces unified compliance reports. Uses executors and parsers directly to avoid
circular dependencies with individual toolkits.

All public async methods automatically become agent tools.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Optional

from ..toolkit import AbstractToolkit
from .checkov.config import CheckovConfig
from .checkov.executor import CheckovExecutor
from .checkov.parser import CheckovParser
from .models import (
    ComparisonDelta,
    ComplianceFramework,
    ConsolidatedReport,
    ScanResult,
    SecurityFinding,
    SeverityLevel,
)
from .prowler.config import ProwlerConfig
from .prowler.executor import ProwlerExecutor
from .prowler.parser import ProwlerParser
from .reports.compliance_mapper import ComplianceMapper
from .reports.generator import ReportGenerator
from .trivy.config import TrivyConfig
from .trivy.executor import TrivyExecutor
from .trivy.parser import TrivyParser


# Severity priority for sorting (lower = more critical)
SEVERITY_PRIORITY = {
    SeverityLevel.CRITICAL: 0,
    SeverityLevel.HIGH: 1,
    SeverityLevel.MEDIUM: 2,
    SeverityLevel.LOW: 3,
    SeverityLevel.INFO: 4,
    SeverityLevel.PASS: 5,
    SeverityLevel.UNKNOWN: 6,
}


class ComplianceReportToolkit(AbstractToolkit):
    """Multi-scanner compliance reporting toolkit.

    Orchestrates Prowler, Trivy, and Checkov to produce unified compliance
    reports. Runs scans in parallel and handles partial failures gracefully.

    All public async methods automatically become agent tools.

    Example:
        toolkit = ComplianceReportToolkit()
        report = await toolkit.compliance_full_scan(
            provider="aws",
            target_image="nginx:latest",
            iac_path="/terraform"
        )
        path = await toolkit.compliance_soc2_report()
    """

    name: str = "compliance_report"
    description: str = (
        "Multi-scanner compliance reporting toolkit that orchestrates Prowler, "
        "Trivy, and Checkov for comprehensive security assessments"
    )

    def __init__(
        self,
        prowler_config: Optional[ProwlerConfig] = None,
        trivy_config: Optional[TrivyConfig] = None,
        checkov_config: Optional[CheckovConfig] = None,
        report_output_dir: str = "/tmp/security-reports",
        **kwargs,
    ):
        """Initialize ComplianceReportToolkit.

        Args:
            prowler_config: Configuration for Prowler scanner.
            trivy_config: Configuration for Trivy scanner.
            checkov_config: Configuration for Checkov scanner.
            report_output_dir: Directory for generated reports.
            **kwargs: Additional arguments passed to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self.logger = logging.getLogger(__name__)

        # Direct executor/parser composition (not using other toolkits)
        self.prowler_executor = ProwlerExecutor(prowler_config or ProwlerConfig())
        self.prowler_parser = ProwlerParser()
        self.trivy_executor = TrivyExecutor(trivy_config or TrivyConfig())
        self.trivy_parser = TrivyParser()
        self.checkov_executor = CheckovExecutor(checkov_config or CheckovConfig())
        self.checkov_parser = CheckovParser()

        # Report infrastructure
        self.report_generator = ReportGenerator(output_dir=report_output_dir)
        self.compliance_mapper = ComplianceMapper()

        # State
        self._last_consolidated: Optional[ConsolidatedReport] = None
        self._report_history: list[ConsolidatedReport] = []

    async def _run_prowler_scan(
        self,
        provider: str,
        regions: Optional[list[str]] = None,
        framework: Optional[str] = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ScanResult:
        """Run Prowler scan and parse results."""
        self.logger.info("Starting Prowler scan for provider=%s", provider)
        if progress_callback:
            stdout, stderr, code = await self.prowler_executor.run_scan_streaming(
                progress_callback=progress_callback,
                provider=provider,
                filter_regions=regions,
                compliance_framework=framework,
            )
        else:
            stdout, stderr, code = await self.prowler_executor.run_scan(
                provider=provider,
                filter_regions=regions,
                compliance_framework=framework,
            )
        if code not in [0, 3]:
            self.logger.warning("Prowler scan exited with code %d: %s", code, stderr)
        return self.prowler_parser.parse(stdout)

    async def _run_trivy_config_scan(self, directory: str) -> ScanResult:
        """Run Trivy config scan for IaC and parse results."""
        self.logger.info("Starting Trivy config scan for %s", directory)
        stdout, stderr, code = await self.trivy_executor.scan_config(directory)
        if code != 0:
            self.logger.warning("Trivy config scan exited with code %d: %s", code, stderr)
        return self.trivy_parser.parse(stdout)

    async def _run_trivy_image_scan(self, image: str) -> ScanResult:
        """Run Trivy image scan and parse results."""
        self.logger.info("Starting Trivy image scan for %s", image)
        stdout, stderr, code = await self.trivy_executor.scan_image(image)
        if code != 0:
            self.logger.warning("Trivy image scan exited with code %d: %s", code, stderr)
        return self.trivy_parser.parse(stdout)

    async def _run_trivy_k8s_scan(self, context: str) -> ScanResult:
        """Run Trivy Kubernetes scan and parse results."""
        self.logger.info("Starting Trivy K8s scan for context=%s", context)
        stdout, stderr, code = await self.trivy_executor.scan_k8s(context=context)
        if code != 0:
            self.logger.warning("Trivy K8s scan exited with code %d: %s", code, stderr)
        return self.trivy_parser.parse(stdout)

    async def _run_checkov_scan(self, directory: str) -> ScanResult:
        """Run Checkov scan and parse results."""
        self.logger.info("Starting Checkov scan for %s", directory)
        stdout, stderr, code = await self.checkov_executor.scan_directory(directory)
        if code != 0:
            self.logger.warning("Checkov scan exited with code %d: %s", code, stderr)
        return self.checkov_parser.parse(stdout)

    def _consolidate_results(
        self, scan_results: dict[str, ScanResult]
    ) -> ConsolidatedReport:
        """Consolidate multiple scan results into unified report."""
        all_findings: list[SecurityFinding] = []
        severity_counts: dict[str, int] = defaultdict(int)
        service_counts: dict[str, int] = defaultdict(int)

        for result in scan_results.values():
            all_findings.extend(result.findings)
            for finding in result.findings:
                severity_counts[finding.severity.value] += 1
                if finding.service:
                    service_counts[finding.service] += 1

        # Calculate compliance coverage for each framework
        compliance_coverage: dict[str, dict] = {}
        for framework in [
            ComplianceFramework.SOC2,
            ComplianceFramework.HIPAA,
            ComplianceFramework.PCI_DSS,
        ]:
            coverage = self.compliance_mapper.get_framework_coverage(
                all_findings, framework
            )
            compliance_coverage[framework.value] = coverage

        return ConsolidatedReport(
            scan_results=scan_results,
            total_findings=len(all_findings),
            findings_by_severity=dict(severity_counts),
            findings_by_service=dict(service_counts),
            compliance_coverage=compliance_coverage,
            generated_at=datetime.now(),
        )

    def _get_all_findings(
        self, consolidated: Optional[ConsolidatedReport] = None
    ) -> list[SecurityFinding]:
        """Extract all findings from a consolidated report."""
        report = consolidated or self._last_consolidated
        if not report:
            return []
        all_findings = []
        for result in report.scan_results.values():
            all_findings.extend(result.findings)
        return all_findings

    async def compliance_full_scan(
        self,
        provider: str = "aws",
        target_image: Optional[str] = None,
        iac_path: Optional[str] = None,
        k8s_context: Optional[str] = None,
        framework: Optional[str] = None,
        regions: Optional[list[str]] = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ConsolidatedReport:
        """Run comprehensive security scan across all configured scanners.

        Executes available scanners in parallel and consolidates results into
        a unified report. Handles partial failures gracefully, returning
        available data even if some scanners fail.

        Args:
            provider: Cloud provider for Prowler scan (aws, azure, gcp, kubernetes).
            target_image: Docker image to scan with Trivy (e.g., 'nginx:latest').
            iac_path: Path to IaC files for Checkov scan.
            k8s_context: Kubernetes context for Trivy K8s scan.
            framework: Compliance framework filter for Prowler.
            regions: Cloud regions to scan.
            progress_callback: Called with each scanner stderr line for progress.

        Returns:
            ConsolidatedReport with findings from all scanners.

        Example:
            report = await toolkit.compliance_full_scan(
                provider="aws",
                target_image="myapp:latest",
                iac_path="./terraform"
            )
        """
        tasks: list = []
        task_names: list[str] = []

        # Always run Prowler for cloud posture
        tasks.append(self._run_prowler_scan(
            provider, regions, framework, progress_callback
        ))
        task_names.append("prowler")

        # Optionally run Trivy for container scanning
        if target_image:
            tasks.append(self._run_trivy_image_scan(target_image))
            task_names.append("trivy_image")

        # Optionally run Trivy for K8s scanning
        if k8s_context:
            tasks.append(self._run_trivy_k8s_scan(k8s_context))
            task_names.append("trivy_k8s")

        # Optionally run Checkov and Trivy for IaC scanning
        if iac_path:
            tasks.append(self._run_checkov_scan(iac_path))
            task_names.append("checkov")
            
            tasks.append(self._run_trivy_config_scan(iac_path))
            task_names.append("trivy_config")

        # Run all scans in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results, handling partial failures
        scan_results: dict[str, ScanResult] = {}
        for name, result in zip(task_names, results):
            if isinstance(result, Exception):
                self.logger.warning("Scanner %s failed: %s", name, result)
            else:
                scan_results[name] = result

        # Consolidate and store
        consolidated = self._consolidate_results(scan_results)
        self._last_consolidated = consolidated
        self._report_history.append(consolidated)

        return consolidated

    async def compliance_soc2_report(
        self,
        provider: str = "aws",
        output_path: Optional[str] = None,
        include_evidence: bool = True,
    ) -> str:
        """Generate SOC2 compliance report.

        Runs a full scan if no previous scan exists, then generates a SOC2
        compliance report mapping findings to Trust Service Criteria.

        Args:
            provider: Cloud provider to scan if no existing data.
            output_path: Custom path for the report file.
            include_evidence: Include detailed evidence section.

        Returns:
            Path to the generated HTML report.

        Example:
            path = await toolkit.compliance_soc2_report(provider="aws")
        """
        if not self._last_consolidated:
            await self.compliance_full_scan(provider=provider)

        return await self.report_generator.generate_compliance_report(
            self._last_consolidated,
            ComplianceFramework.SOC2,
            output_path=output_path,
            include_evidence=include_evidence,
        )

    async def compliance_hipaa_report(
        self,
        provider: str = "aws",
        output_path: Optional[str] = None,
        include_evidence: bool = True,
    ) -> str:
        """Generate HIPAA compliance report.

        Runs a full scan if no previous scan exists, then generates a HIPAA
        Security Rule compliance report.

        Args:
            provider: Cloud provider to scan if no existing data.
            output_path: Custom path for the report file.
            include_evidence: Include detailed evidence section.

        Returns:
            Path to the generated HTML report.

        Example:
            path = await toolkit.compliance_hipaa_report(provider="aws")
        """
        if not self._last_consolidated:
            await self.compliance_full_scan(provider=provider)

        return await self.report_generator.generate_compliance_report(
            self._last_consolidated,
            ComplianceFramework.HIPAA,
            output_path=output_path,
            include_evidence=include_evidence,
        )

    async def compliance_pci_report(
        self,
        provider: str = "aws",
        output_path: Optional[str] = None,
        include_evidence: bool = True,
    ) -> str:
        """Generate PCI-DSS compliance report.

        Runs a full scan if no previous scan exists, then generates a PCI-DSS
        v4.0 compliance report.

        Args:
            provider: Cloud provider to scan if no existing data.
            output_path: Custom path for the report file.
            include_evidence: Include detailed evidence section.

        Returns:
            Path to the generated HTML report.

        Example:
            path = await toolkit.compliance_pci_report(provider="aws")
        """
        if not self._last_consolidated:
            await self.compliance_full_scan(provider=provider)

        return await self.report_generator.generate_compliance_report(
            self._last_consolidated,
            ComplianceFramework.PCI_DSS,
            output_path=output_path,
            include_evidence=include_evidence,
        )

    async def compliance_custom_report(
        self,
        framework: str,
        provider: str = "aws",
        output_path: Optional[str] = None,
        include_evidence: bool = True,
    ) -> str:
        """Generate compliance report for any supported framework.

        Runs a full scan if no previous scan exists, then generates a
        compliance report for the specified framework.

        Args:
            framework: Compliance framework (soc2, hipaa, pci_dss, cis_aws, etc.).
            provider: Cloud provider to scan if no existing data.
            output_path: Custom path for the report file.
            include_evidence: Include detailed evidence section.

        Returns:
            Path to the generated HTML report.

        Example:
            path = await toolkit.compliance_custom_report(framework="cis_aws")
        """
        if not self._last_consolidated:
            await self.compliance_full_scan(provider=provider)

        # Parse framework string to enum
        try:
            compliance_framework = ComplianceFramework(framework.lower())
        except ValueError:
            self.logger.warning(
                "Unknown framework %s, defaulting to SOC2", framework
            )
            compliance_framework = ComplianceFramework.SOC2

        return await self.report_generator.generate_compliance_report(
            self._last_consolidated,
            compliance_framework,
            output_path=output_path,
            include_evidence=include_evidence,
        )

    async def compliance_executive_summary(
        self,
        provider: str = "aws",
    ) -> dict:
        """Generate executive summary of security posture.

        Returns a structured summary suitable for dashboards and management
        reporting. Includes risk score, severity breakdown, compliance coverage,
        and top findings.

        Args:
            provider: Cloud provider to scan if no existing data.

        Returns:
            Dictionary with executive summary data:
            - total_findings: Total number of findings
            - findings_by_severity: Count per severity level
            - compliance_coverage: Coverage percentage per framework
            - top_critical_findings: List of most critical issues
            - overall_risk_score: Calculated risk score (0-100)
            - scanners_used: List of scanners that ran

        Example:
            summary = await toolkit.compliance_executive_summary()
            print(f"Risk Score: {summary['overall_risk_score']}")
        """
        if not self._last_consolidated:
            await self.compliance_full_scan(provider=provider)

        report = self._last_consolidated
        all_findings = self._get_all_findings(report)

        # Calculate risk score (weighted by severity)
        severity_weights = {
            "CRITICAL": 40,
            "HIGH": 20,
            "MEDIUM": 10,
            "LOW": 5,
            "INFO": 1,
            "PASS": 0,
        }
        total_weight = sum(
            severity_weights.get(f.severity.value, 0) for f in all_findings
        )
        max_possible = len(all_findings) * 40 if all_findings else 1
        risk_score = min(100, int((total_weight / max_possible) * 100))

        # Get top critical findings
        critical_findings = [
            f for f in all_findings if f.severity == SeverityLevel.CRITICAL
        ][:5]

        return {
            "total_findings": report.total_findings,
            "findings_by_severity": report.findings_by_severity,
            "findings_by_service": getattr(report, "findings_by_service", {}),
            "compliance_coverage": report.compliance_coverage,
            "top_critical_findings": [
                {
                    "id": f.id,
                    "title": f.title,
                    "source": f.source.value if f.source else None,
                    "resource": f.resource,
                }
                for f in critical_findings
            ],
            "overall_risk_score": risk_score,
            "scanners_used": list(report.scan_results.keys()),
            "scan_timestamp": report.generated_at.isoformat(),
        }

    async def compliance_get_gaps(
        self,
        framework: str = "soc2",
        provider: str = "aws",
    ) -> list[dict]:
        """Get compliance gaps for a specific framework.

        Identifies controls that have failed or unchecked findings,
        organized by control category.

        Args:
            framework: Compliance framework to analyze.
            provider: Cloud provider to scan if no existing data.

        Returns:
            List of gap dictionaries with control_id, control_name,
            status, finding_count, and findings.

        Example:
            gaps = await toolkit.compliance_get_gaps(framework="hipaa")
            for gap in gaps:
                print(f"{gap['control_id']}: {gap['finding_count']} findings")
        """
        if not self._last_consolidated:
            await self.compliance_full_scan(provider=provider)

        all_findings = self._get_all_findings()

        # Parse framework
        try:
            compliance_framework = ComplianceFramework(framework.lower())
        except ValueError:
            compliance_framework = ComplianceFramework.SOC2

        # Get all controls and their findings
        all_controls = self.compliance_mapper.get_all_controls(compliance_framework)
        findings_by_control = self.compliance_mapper.get_findings_by_control(
            all_findings, compliance_framework
        )

        gaps = []
        for control_id, control_info in all_controls.items():
            control_findings = findings_by_control.get(control_id, [])
            # Filter to non-passing findings
            failed_findings = [
                f for f in control_findings if f.severity != SeverityLevel.PASS
            ]

            if failed_findings:
                gaps.append({
                    "control_id": control_id,
                    "control_name": control_info.get("name", control_id),
                    "category": control_info.get("category", "unknown"),
                    "status": "failed",
                    "finding_count": len(failed_findings),
                    "findings": [
                        {
                            "id": f.id,
                            "title": f.title,
                            "severity": f.severity.value,
                            "resource": f.resource,
                        }
                        for f in failed_findings[:5]  # Limit to 5 per control
                    ],
                })

        # Sort by finding count descending
        gaps.sort(key=lambda x: x["finding_count"], reverse=True)
        return gaps

    async def compliance_get_remediation_plan(
        self,
        max_items: int = 20,
        provider: str = "aws",
    ) -> list[dict]:
        """Get prioritized remediation plan.

        Returns findings sorted by priority (severity and compliance impact)
        with remediation guidance.

        Args:
            max_items: Maximum number of items to return.
            provider: Cloud provider to scan if no existing data.

        Returns:
            List of remediation items with finding details, priority,
            and remediation steps.

        Example:
            plan = await toolkit.compliance_get_remediation_plan(max_items=10)
            for item in plan:
                print(f"[{item['priority']}] {item['finding'].title}")
        """
        if not self._last_consolidated:
            await self.compliance_full_scan(provider=provider)

        all_findings = self._get_all_findings()

        # Filter out passing findings
        actionable = [f for f in all_findings if f.severity != SeverityLevel.PASS]

        # Sort by severity priority
        actionable.sort(key=lambda f: SEVERITY_PRIORITY.get(f.severity, 99))

        # Build remediation plan
        plan = []
        for i, finding in enumerate(actionable[:max_items]):
            # Calculate compliance impact
            compliance_impact = []
            for framework in [
                ComplianceFramework.SOC2,
                ComplianceFramework.HIPAA,
                ComplianceFramework.PCI_DSS,
            ]:
                controls = self.compliance_mapper.map_finding_to_controls(
                    finding, framework
                )
                if controls:
                    compliance_impact.append(framework.value)

            plan.append({
                "priority": i + 1,
                "finding": finding,
                "severity": finding.severity.value,
                "title": finding.title,
                "resource": finding.resource,
                "remediation": finding.remediation or "No remediation guidance available",
                "compliance_impact": compliance_impact,
                "source": finding.source.value if finding.source else None,
            })

        return plan

    async def compliance_compare_reports(
        self,
        baseline_index: int = -2,
        current_index: int = -1,
    ) -> ComparisonDelta:
        """Compare two scan reports to detect drift.

        Compares findings between two historical scans to identify new,
        resolved, and unchanged findings.

        Args:
            baseline_index: Index in report history for baseline (-2 = second to last).
            current_index: Index in report history for current (-1 = most recent).

        Returns:
            ComparisonDelta with new, resolved, and unchanged findings.

        Example:
            delta = await toolkit.compliance_compare_reports()
            print(f"New findings: {len(delta.new_findings)}")
            print(f"Resolved: {len(delta.resolved_findings)}")
        """
        if len(self._report_history) < 2:
            self.logger.warning("Not enough reports for comparison")
            now = datetime.now()
            return ComparisonDelta(
                new_findings=[],
                resolved_findings=[],
                unchanged_findings=[],
                baseline_timestamp=now,
                current_timestamp=now,
            )

        try:
            baseline = self._report_history[baseline_index]
            current = self._report_history[current_index]
        except IndexError:
            self.logger.warning("Invalid report indices")
            now = datetime.now()
            return ComparisonDelta(
                new_findings=[],
                resolved_findings=[],
                unchanged_findings=[],
                baseline_timestamp=now,
                current_timestamp=now,
            )

        baseline_findings = self._get_all_findings(baseline)
        current_findings = self._get_all_findings(current)

        # Create sets for comparison (using finding IDs)
        baseline_ids = {f.id for f in baseline_findings if f.id}
        current_ids = {f.id for f in current_findings if f.id}

        new_ids = current_ids - baseline_ids
        resolved_ids = baseline_ids - current_ids
        unchanged_ids = baseline_ids & current_ids

        # Map IDs back to findings
        current_by_id = {f.id: f for f in current_findings if f.id}
        baseline_by_id = {f.id: f for f in baseline_findings if f.id}

        return ComparisonDelta(
            new_findings=[current_by_id[fid] for fid in new_ids if fid in current_by_id],
            resolved_findings=[
                baseline_by_id[fid] for fid in resolved_ids if fid in baseline_by_id
            ],
            unchanged_findings=[
                current_by_id[fid] for fid in unchanged_ids if fid in current_by_id
            ],
            baseline_timestamp=baseline.generated_at,
            current_timestamp=current.generated_at,
        )

    async def compliance_export_findings(
        self,
        output_path: str,
        format: str = "csv",
        provider: str = "aws",
    ) -> str:
        """Export findings to CSV or JSON format.

        Exports all findings from the most recent scan to a file for
        integration with other tools or archival.

        Args:
            output_path: Path for the output file.
            format: Export format ('csv' or 'json').
            provider: Cloud provider to scan if no existing data.

        Returns:
            Path to the exported file.

        Example:
            path = await toolkit.compliance_export_findings(
                output_path="/tmp/findings.csv",
                format="csv"
            )
        """
        if not self._last_consolidated:
            await self.compliance_full_scan(provider=provider)

        all_findings = self._get_all_findings()

        if format.lower() == "csv":
            return await self.report_generator.export_findings_csv(
                all_findings, output_path
            )
        else:
            # JSON export
            import json
            from pathlib import Path

            findings_data = [
                {
                    "id": f.id,
                    "source": f.source.value if f.source else None,
                    "severity": f.severity.value if f.severity else None,
                    "title": f.title,
                    "description": f.description,
                    "resource": f.resource,
                    "resource_type": f.resource_type,
                    "service": f.service,
                    "region": f.region,
                    "check_id": f.check_id,
                    "remediation": f.remediation,
                    "compliance_tags": f.compliance_tags,
                }
                for f in all_findings
            ]

            Path(output_path).write_text(
                json.dumps(findings_data, indent=2, default=str),
                encoding="utf-8",
            )
            self.logger.info("Exported %d findings to JSON: %s", len(all_findings), output_path)
            return output_path
