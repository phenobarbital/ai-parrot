"""Cloud Security Posture Management Toolkit.

Agent-facing toolkit that wraps Prowler for multi-cloud security scanning.
All public async methods automatically become agent tools.
"""

from typing import Optional

from ..toolkit import AbstractToolkit
from .models import (
    ComparisonDelta,
    ScanResult,
    SecurityFinding,
    SeverityLevel,
)
from .prowler.config import ProwlerConfig
from .prowler.executor import ProwlerExecutor
from .prowler.parser import ProwlerParser


class CloudPostureToolkit(AbstractToolkit):
    """Cloud Security Posture Management toolkit powered by Prowler.

    Runs multi-cloud security assessments, compliance scans, and posture
    tracking against AWS, Azure, GCP and Kubernetes.

    All public async methods automatically become agent tools.

    Example:
        toolkit = CloudPostureToolkit()
        result = await toolkit.prowler_run_scan(provider="aws", services=["s3", "iam"])
        findings = await toolkit.prowler_get_findings(severity="CRITICAL")
    """

    name: str = "cloud_posture"
    description: str = "Cloud security posture management powered by Prowler"

    def __init__(self, config: Optional[ProwlerConfig] = None, **kwargs):
        """Initialize CloudPostureToolkit.

        Args:
            config: Optional ProwlerConfig. Uses defaults if not provided.
            **kwargs: Additional arguments passed to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self.config = config or ProwlerConfig()
        self.executor = ProwlerExecutor(self.config)
        self.parser = ProwlerParser()
        self._last_result: Optional[ScanResult] = None

    async def prowler_run_scan(
        self,
        provider: str = "aws",
        services: Optional[list[str]] = None,
        checks: Optional[list[str]] = None,
        regions: Optional[list[str]] = None,
        severity: Optional[list[str]] = None,
        exclude_passing: bool = False,
    ) -> ScanResult:
        """Run a Prowler security scan against cloud infrastructure.

        Executes a comprehensive security assessment using Prowler to identify
        misconfigurations, compliance violations, and security risks.

        Args:
            provider: Cloud provider to scan. Options: aws, azure, gcp, kubernetes.
            services: Specific services to scan (e.g., ['s3', 'iam', 'ec2']).
                If None, scans all available services.
            checks: Specific check IDs to run. If None, runs all checks.
            regions: AWS regions to scan (e.g., ['us-east-1', 'eu-west-1']).
                If None, scans all available regions.
            severity: Filter by severity levels. Options: critical, high, medium, low.
            exclude_passing: If True, exclude PASS findings from results.

        Returns:
            ScanResult with normalized findings and summary statistics.

        Example:
            result = await toolkit.prowler_run_scan(
                provider="aws",
                services=["s3", "iam"],
                severity=["critical", "high"]
            )
        """
        stdout, stderr, code = await self.executor.run_scan(
            provider=provider,
            services=services,
            checks=checks,
            filter_regions=regions,
            severity=severity,
        )

        if code != 0:
            self.logger.error("Prowler scan failed with code %d: %s", code, stderr)

        result = self.parser.parse(stdout)

        if exclude_passing:
            result.findings = [
                f for f in result.findings if f.severity != SeverityLevel.PASS
            ]

        self._last_result = result
        return result

    async def prowler_compliance_scan(
        self,
        framework: str,
        provider: str = "aws",
        regions: Optional[list[str]] = None,
        exclude_passing: bool = True,
    ) -> ScanResult:
        """Run a compliance-focused security scan.

        Executes Prowler with checks filtered to a specific compliance framework
        such as CIS, SOC2, HIPAA, PCI-DSS, or GDPR.

        Args:
            framework: Compliance framework to assess. Examples:
                - AWS: cis_1.5_aws, soc2, hipaa, pci_dss_v4.0, gdpr
                - Azure: cis_2.0_azure, nist_800_53_revision_5_azure
                - GCP: cis_2.0_gcp
            provider: Cloud provider to scan. Options: aws, azure, gcp, kubernetes.
            regions: AWS regions to scan. If None, scans all available regions.
            exclude_passing: If True, exclude PASS findings (default True for
                compliance scans to focus on violations).

        Returns:
            ScanResult filtered to the specified compliance framework.

        Example:
            result = await toolkit.prowler_compliance_scan(
                framework="cis_1.5_aws",
                provider="aws"
            )
        """
        # Update config with compliance framework
        original_framework = self.config.compliance_framework
        self.config.compliance_framework = framework

        try:
            stdout, stderr, code = await self.executor.run_scan(
                provider=provider,
                filter_regions=regions,
            )

            if code != 0:
                self.logger.error(
                    "Prowler compliance scan failed with code %d: %s", code, stderr
                )

            result = self.parser.parse(stdout)

            if exclude_passing:
                result.findings = [
                    f for f in result.findings if f.severity != SeverityLevel.PASS
                ]

            self._last_result = result
            return result
        finally:
            # Restore original framework
            self.config.compliance_framework = original_framework

    async def prowler_scan_service(
        self,
        service: str,
        provider: str = "aws",
        regions: Optional[list[str]] = None,
        exclude_passing: bool = False,
    ) -> ScanResult:
        """Scan a specific cloud service.

        Runs Prowler checks limited to a single service for targeted assessment.

        Args:
            service: Service to scan. Examples:
                - AWS: s3, iam, ec2, rds, lambda, cloudtrail, kms
                - Azure: storage, keyvault, sql, network
                - GCP: compute, storage, iam, bigquery
            provider: Cloud provider. Options: aws, azure, gcp, kubernetes.
            regions: AWS regions to scan. If None, scans all available regions.
            exclude_passing: If True, exclude PASS findings from results.

        Returns:
            ScanResult with findings limited to the specified service.

        Example:
            result = await toolkit.prowler_scan_service(
                service="s3",
                provider="aws",
                regions=["us-east-1"]
            )
        """
        stdout, stderr, code = await self.executor.run_scan(
            provider=provider,
            services=[service],
            filter_regions=regions,
        )

        if code != 0:
            self.logger.error(
                "Prowler service scan failed with code %d: %s", code, stderr
            )

        result = self.parser.parse(stdout)

        if exclude_passing:
            result.findings = [
                f for f in result.findings if f.severity != SeverityLevel.PASS
            ]

        self._last_result = result
        return result

    async def prowler_list_checks(
        self,
        provider: str = "aws",
        service: Optional[str] = None,
    ) -> list[dict]:
        """List available Prowler security checks.

        Returns metadata about available checks including ID, title, severity,
        and associated compliance frameworks.

        Args:
            provider: Cloud provider. Options: aws, azure, gcp, kubernetes.
            service: Filter checks to a specific service. If None, lists all.

        Returns:
            List of check metadata dictionaries with keys:
                - check_id: Unique check identifier
                - title: Human-readable check name
                - severity: Check severity level
                - service: Associated service
                - compliance: List of compliance frameworks

        Example:
            checks = await toolkit.prowler_list_checks(provider="aws", service="s3")
        """
        stdout, stderr, code = await self.executor.list_checks(
            provider=provider,
            service=service,
        )

        if code != 0:
            self.logger.error("Failed to list checks: %s", stderr)
            return []

        # Parse check listing output
        checks = []
        for line in stdout.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Prowler outputs check IDs one per line
            checks.append({"check_id": line, "provider": provider})

        return checks

    async def prowler_list_services(
        self,
        provider: str = "aws",
    ) -> list[str]:
        """List scannable services for a cloud provider.

        Returns the list of services that Prowler can scan for the given provider.

        Args:
            provider: Cloud provider. Options: aws, azure, gcp, kubernetes.

        Returns:
            List of service names (e.g., ['s3', 'iam', 'ec2', ...]).

        Example:
            services = await toolkit.prowler_list_services(provider="aws")
        """
        stdout, stderr, code = await self.executor.list_services(provider=provider)

        if code != 0:
            self.logger.error("Failed to list services: %s", stderr)
            return []

        # Parse service listing output
        services = []
        for line in stdout.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                services.append(line)

        return services

    async def prowler_get_summary(self) -> dict:
        """Get summary statistics from the last scan.

        Returns aggregated metrics from the most recent scan including
        finding counts by severity, services scanned, and compliance status.

        Returns:
            Dictionary with summary statistics:
                - total_findings: Total number of findings
                - critical_count: Critical severity findings
                - high_count: High severity findings
                - medium_count: Medium severity findings
                - low_count: Low severity findings
                - pass_count: Passing checks
                - services_scanned: List of scanned services
                - provider: Cloud provider that was scanned
            Returns empty dict if no scan has been run.

        Example:
            summary = await toolkit.prowler_get_summary()
            print(f"Critical: {summary['critical_count']}")
        """
        if self._last_result is None:
            return {}

        summary = self._last_result.summary
        return {
            "total_findings": summary.total_findings,
            "critical_count": summary.critical_count,
            "high_count": summary.high_count,
            "medium_count": summary.medium_count,
            "low_count": summary.low_count,
            "info_count": summary.info_count,
            "pass_count": summary.pass_count,
            "services_scanned": summary.services_scanned,
            "regions_scanned": summary.regions_scanned,
            "provider": summary.provider.value if summary.provider else None,
            "scan_timestamp": (
                summary.scan_timestamp.isoformat() if summary.scan_timestamp else None
            ),
        }

    async def prowler_get_findings(
        self,
        severity: Optional[str] = None,
        service: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[SecurityFinding]:
        """Get findings from the last scan with optional filters.

        Retrieves security findings from the most recent scan, optionally
        filtered by severity, service, or status.

        Args:
            severity: Filter by severity level. Options: CRITICAL, HIGH,
                MEDIUM, LOW, INFO, PASS.
            service: Filter by service name (e.g., 's3', 'iam').
            status: Filter by finding status. Options: FAIL, PASS, MANUAL.
            limit: Maximum number of findings to return.

        Returns:
            List of SecurityFinding objects matching the filters.
            Returns empty list if no scan has been run.

        Example:
            critical = await toolkit.prowler_get_findings(severity="CRITICAL")
            s3_issues = await toolkit.prowler_get_findings(service="s3", limit=10)
        """
        if self._last_result is None:
            return []

        findings = self._last_result.findings

        # Apply severity filter
        if severity:
            try:
                severity_level = SeverityLevel(severity.upper())
                findings = [f for f in findings if f.severity == severity_level]
            except ValueError:
                self.logger.warning("Invalid severity filter: %s", severity)

        # Apply service filter
        if service:
            findings = [f for f in findings if f.service == service]

        # Apply status filter (map to severity for PASS)
        if status:
            status_upper = status.upper()
            if status_upper == "PASS":
                findings = [f for f in findings if f.severity == SeverityLevel.PASS]
            elif status_upper == "FAIL":
                findings = [f for f in findings if f.severity != SeverityLevel.PASS]
            elif status_upper == "MANUAL":
                findings = [f for f in findings if f.severity == SeverityLevel.INFO]

        # Apply limit
        if limit and limit > 0:
            findings = findings[:limit]

        return findings

    async def prowler_generate_report(
        self,
        output_path: str,
        format: str = "html",
    ) -> str:
        """Generate a report from the last scan results.

        Creates a formatted report file from the most recent scan findings.

        Args:
            output_path: Path where the report file will be saved.
            format: Report format. Options: html, json, csv.

        Returns:
            Path to the generated report file.

        Raises:
            ValueError: If no scan has been run yet.

        Example:
            path = await toolkit.prowler_generate_report(
                output_path="/tmp/security-report.html",
                format="html"
            )
        """
        if self._last_result is None:
            raise ValueError("No scan results available. Run a scan first.")

        # For now, save as JSON (HTML generation would require templates)
        if format.lower() == "json":
            self.parser.save_result(self._last_result, output_path)
        else:
            # Placeholder for HTML/CSV generation
            # In production, this would use templates
            self.parser.save_result(self._last_result, output_path)
            self.logger.info(
                "Report format '%s' not fully implemented, saved as JSON", format
            )

        return output_path

    async def prowler_compare_scans(
        self,
        baseline_path: str,
    ) -> ComparisonDelta:
        """Compare current scan results against a baseline.

        Identifies new findings (regressions), resolved findings (improvements),
        and unchanged findings between the current scan and a saved baseline.

        Args:
            baseline_path: Path to the baseline scan result JSON file.

        Returns:
            ComparisonDelta with:
                - new_findings: Findings in current but not in baseline
                - resolved_findings: Findings in baseline but not in current
                - unchanged_findings: Findings present in both

        Raises:
            ValueError: If no current scan results or baseline cannot be loaded.

        Example:
            delta = await toolkit.prowler_compare_scans(
                baseline_path="/scans/baseline-2024-01-01.json"
            )
            print(f"New issues: {len(delta.new_findings)}")
            print(f"Resolved: {len(delta.resolved_findings)}")
        """
        if self._last_result is None:
            raise ValueError("No current scan results. Run a scan first.")

        # Load baseline
        baseline = self.parser.load_result(baseline_path)

        # Build sets of finding IDs for comparison
        baseline_ids = {f.id for f in baseline.findings}
        current_ids = {f.id for f in self._last_result.findings}

        # Find new, resolved, and unchanged
        new_ids = current_ids - baseline_ids
        resolved_ids = baseline_ids - current_ids
        unchanged_ids = current_ids & baseline_ids

        # Map IDs back to findings
        current_by_id = {f.id: f for f in self._last_result.findings}
        baseline_by_id = {f.id: f for f in baseline.findings}

        new_findings = [current_by_id[fid] for fid in new_ids]
        resolved_findings = [baseline_by_id[fid] for fid in resolved_ids]
        unchanged_findings = [current_by_id[fid] for fid in unchanged_ids]

        # Compute severity trend
        severity_trend = {}
        for level in SeverityLevel:
            baseline_count = sum(
                1 for f in baseline.findings if f.severity == level
            )
            current_count = sum(
                1 for f in self._last_result.findings if f.severity == level
            )
            diff = current_count - baseline_count
            if diff != 0:
                severity_trend[level.value] = diff

        # Build summary
        summary_parts = []
        if new_findings:
            summary_parts.append(f"{len(new_findings)} new findings")
        if resolved_findings:
            summary_parts.append(f"{len(resolved_findings)} resolved")
        if unchanged_findings:
            summary_parts.append(f"{len(unchanged_findings)} unchanged")
        summary = ", ".join(summary_parts) if summary_parts else "No changes"

        return ComparisonDelta(
            baseline_timestamp=baseline.summary.scan_timestamp,
            current_timestamp=self._last_result.summary.scan_timestamp,
            new_findings=new_findings,
            resolved_findings=resolved_findings,
            unchanged_findings=unchanged_findings,
            severity_trend=severity_trend,
            summary=summary,
        )
