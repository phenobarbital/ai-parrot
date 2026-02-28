"""Report Generator for security scan results.

Generates multi-format compliance and security reports from consolidated
scan results using Jinja2 templates.
"""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from jinja2 import Environment, FileSystemLoader
from ..models import (
    ComplianceFramework,
    ConsolidatedReport,
    ScanResult,
    SecurityFinding,
    SeverityLevel,
)
from .compliance_mapper import ComplianceMapper


class ReportGenerator:
    """Multi-format report generator with Jinja2 templates.

    Generates compliance reports (SOC2, HIPAA, PCI-DSS), executive summaries,
    and consolidated multi-scanner reports from security scan results.

    Example:
        generator = ReportGenerator(output_dir="/tmp/reports")
        path = await generator.generate_compliance_report(
            consolidated_report,
            ComplianceFramework.SOC2
        )
    """

    def __init__(self, output_dir: str = "/tmp/reports"):
        """Initialize the ReportGenerator.

        Args:
            output_dir: Directory where generated reports will be saved.
                Created if it doesn't exist.
        """
        self.logger = logging.getLogger(__name__)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.template_dir = Path(__file__).parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=True,
        )
        self.compliance_mapper = ComplianceMapper()

    def _get_all_findings(self, consolidated: ConsolidatedReport) -> list[SecurityFinding]:
        """Extract all findings from a consolidated report."""
        all_findings = []
        for result in consolidated.scan_results.values():
            all_findings.extend(result.findings)
        return all_findings

    def _calculate_severity_counts(
        self, findings: list[SecurityFinding]
    ) -> dict[str, int]:
        """Calculate severity counts from findings."""
        counts = {
            "CRITICAL": 0,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "INFO": 0,
            "PASS": 0,
        }
        for finding in findings:
            severity_key = finding.severity.value.upper()
            if severity_key in counts:
                counts[severity_key] += 1
        return counts

    def _build_severity_breakdown(
        self, findings: list[SecurityFinding]
    ) -> dict[str, int]:
        """Build severity breakdown for template rendering."""
        counts = self._calculate_severity_counts(findings)
        # Only return non-zero entries
        return {k: v for k, v in counts.items() if v > 0}

    def _build_controls_by_category(
        self,
        findings: list[SecurityFinding],
        framework: ComplianceFramework,
    ) -> dict[str, list[dict]]:
        """Build control status organized by category for templates."""
        # Get all controls for the framework
        all_controls = self.compliance_mapper.get_all_controls(framework)
        findings_by_control = self.compliance_mapper.get_findings_by_control(
            findings, framework
        )

        # Build category groups
        categories: dict[str, list[dict]] = {}

        for control_id, control_info in all_controls.items():
            category = control_info.get("category", "other")
            control_findings = findings_by_control.get(control_id, [])

            # Determine status
            if not control_findings:
                status = "unchecked"
                finding_count = 0
            elif any(f.severity != SeverityLevel.PASS for f in control_findings):
                status = "failed"
                finding_count = len(control_findings)
            else:
                status = "passed"
                finding_count = len(control_findings)

            control_entry = {
                "id": control_id,
                "name": control_info.get("name", control_id),
                "description": control_info.get("description", ""),
                "status": status,
                "finding_count": finding_count,
            }

            # Organize by category for HIPAA and PCI-DSS
            if category not in categories:
                categories[category] = []
            categories[category].append(control_entry)

            # Also organize by control prefix for SOC2 (CC1, CC2, etc.)
            if framework == ComplianceFramework.SOC2:
                prefix = control_id[:3] if len(control_id) >= 3 else control_id
                if prefix not in categories:
                    categories[prefix] = []
                if control_entry not in categories[prefix]:
                    categories[prefix].append(control_entry)

        return categories

    async def generate_compliance_report(
        self,
        consolidated: ConsolidatedReport,
        framework: ComplianceFramework,
        format: str = "html",
        output_path: Optional[str] = None,
        include_evidence: bool = True,
    ) -> str:
        """Generate a compliance report for a specific framework.

        Args:
            consolidated: Consolidated report from multiple scanners.
            framework: Compliance framework to generate report for.
            format: Output format (currently only 'html' supported).
            output_path: Custom path for the output file.
            include_evidence: Whether to include detailed evidence section.

        Returns:
            Path to the generated report file.
        """
        # Get template
        template_name = f"{framework.value}_report.html"
        try:
            template = self.env.get_template(template_name)
        except Exception:
            # Fall back to SOC2 template structure for unsupported frameworks
            self.logger.warning(
                "No template found for %s, using generic compliance template",
                framework.value,
            )
            template = self.env.get_template("soc2_report.html")

        # Extract findings
        all_findings = self._get_all_findings(consolidated)

        # Calculate coverage
        coverage = self.compliance_mapper.get_framework_coverage(all_findings, framework)

        # Build template data
        severity_breakdown = self._build_severity_breakdown(all_findings)
        controls_by_category = self._build_controls_by_category(all_findings, framework)

        # Render HTML
        html = template.render(
            report=consolidated,
            framework=framework,
            coverage=coverage,
            severity_breakdown=severity_breakdown,
            controls_by_category=controls_by_category,
            findings=all_findings if include_evidence else [],
            include_evidence=include_evidence,
            generated_at=datetime.now(),
        )

        # Determine output path
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(
                self.output_dir / f"{framework.value}_report_{timestamp}.html"
            )

        # Write report
        Path(output_path).write_text(html, encoding="utf-8")
        self.logger.info("Generated %s report at %s", framework.value, output_path)

        return output_path

    async def generate_executive_summary(
        self,
        consolidated: ConsolidatedReport,
        format: str = "html",
        output_path: Optional[str] = None,
    ) -> str:
        """Generate an executive summary report.

        Args:
            consolidated: Consolidated report from multiple scanners.
            format: Output format (currently only 'html' supported).
            output_path: Custom path for the output file.

        Returns:
            Path to the generated report file.
        """
        template = self.env.get_template("executive_summary.html")

        # Extract findings and calculate metrics
        all_findings = self._get_all_findings(consolidated)
        severity_counts = self._calculate_severity_counts(all_findings)

        # Get top critical findings
        critical_findings = [
            f for f in all_findings if f.severity == SeverityLevel.CRITICAL
        ]
        top_critical = critical_findings[:5]

        # Render HTML
        html = template.render(
            report=consolidated,
            critical_count=severity_counts["CRITICAL"],
            high_count=severity_counts["HIGH"],
            medium_count=severity_counts["MEDIUM"],
            low_count=severity_counts["LOW"],
            info_count=severity_counts["INFO"],
            pass_count=severity_counts["PASS"],
            scanners_count=len(consolidated.scan_results),
            scanner_results=consolidated.scan_results,
            top_critical_findings=top_critical,
            generated_at=datetime.now(),
        )

        # Determine output path
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(
                self.output_dir / f"executive_summary_{timestamp}.html"
            )

        # Write report
        Path(output_path).write_text(html, encoding="utf-8")
        self.logger.info("Generated executive summary at %s", output_path)

        return output_path

    async def generate_consolidated_report(
        self,
        consolidated: ConsolidatedReport,
        format: str = "html",
        output_path: Optional[str] = None,
        include_all_findings: bool = False,
    ) -> str:
        """Generate a full consolidated report from all scanners.

        Args:
            consolidated: Consolidated report from multiple scanners.
            format: Output format (currently only 'html' supported).
            output_path: Custom path for the output file.
            include_all_findings: Whether to include all findings in detail.

        Returns:
            Path to the generated report file.
        """
        template = self.env.get_template("consolidated_report.html")

        # Extract findings and calculate metrics
        all_findings = self._get_all_findings(consolidated)
        severity_counts = self._calculate_severity_counts(all_findings)

        # Render HTML
        html = template.render(
            report=consolidated,
            critical_count=severity_counts["CRITICAL"],
            high_count=severity_counts["HIGH"],
            medium_count=severity_counts["MEDIUM"],
            low_count=severity_counts["LOW"],
            info_count=severity_counts["INFO"],
            pass_count=severity_counts["PASS"],
            scanners_count=len(consolidated.scan_results),
            scanner_results=consolidated.scan_results,
            all_findings=all_findings if include_all_findings else [],
            include_all_findings=include_all_findings,
            generated_at=datetime.now(),
        )

        # Determine output path
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(
                self.output_dir / f"consolidated_report_{timestamp}.html"
            )

        # Write report
        Path(output_path).write_text(html, encoding="utf-8")
        self.logger.info("Generated consolidated report at %s", output_path)

        return output_path

    async def export_findings_csv(
        self,
        findings: list[SecurityFinding],
        output_path: str,
    ) -> str:
        """Export findings to CSV format.

        Args:
            findings: List of security findings to export.
            output_path: Path for the CSV file.

        Returns:
            Path to the generated CSV file.
        """
        fieldnames = [
            "id",
            "source",
            "severity",
            "title",
            "description",
            "check_id",
            "resource",
            "resource_type",
            "remediation",
            "timestamp",
        ]

        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for finding in findings:
                writer.writerow({
                    "id": finding.id or "",
                    "source": finding.source.value if finding.source else "",
                    "severity": finding.severity.value if finding.severity else "",
                    "title": finding.title or "",
                    "description": finding.description or "",
                    "check_id": finding.check_id or "",
                    "resource": finding.resource or "",
                    "resource_type": finding.resource_type or "",
                    "remediation": finding.remediation or "",
                    "timestamp": (
                        finding.timestamp.isoformat() if finding.timestamp else ""
                    ),
                })

        self.logger.info("Exported %d findings to CSV: %s", len(findings), output_path)
        return output_path

    async def generate_report_from_scan_result(
        self,
        scan_result: ScanResult,
        report_type: str = "consolidated",
        output_path: Optional[str] = None,
    ) -> str:
        """Generate a report from a single scan result.

        Convenience method that wraps a single ScanResult in a ConsolidatedReport.

        Args:
            scan_result: Single scan result to generate report from.
            report_type: Type of report ('consolidated', 'executive').
            output_path: Custom path for the output file.

        Returns:
            Path to the generated report file.
        """
        # Wrap in consolidated report
        source_name = scan_result.summary.source.value if scan_result.summary.source else "scan"
        consolidated = ConsolidatedReport(
            scan_results={source_name: scan_result},
            total_findings=scan_result.summary.total_findings,
            findings_by_severity={},
            generated_at=datetime.now(),
        )

        if report_type == "executive":
            return await self.generate_executive_summary(consolidated, output_path=output_path)
        else:
            return await self.generate_consolidated_report(consolidated, output_path=output_path)
