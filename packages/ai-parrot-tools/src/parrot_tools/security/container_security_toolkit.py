"""Container Security Toolkit.

Agent-facing toolkit that wraps Trivy for container, filesystem,
Kubernetes, and IaC security scanning.
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
from .trivy.config import TrivyConfig
from .trivy.executor import TrivyExecutor
from .trivy.parser import TrivyParser


class ContainerSecurityToolkit(AbstractToolkit):
    """Container and infrastructure security toolkit powered by Trivy.

    Scans container images, filesystems, git repositories, Kubernetes clusters,
    and Infrastructure as Code for vulnerabilities, secrets, and misconfigurations.

    All public async methods automatically become agent tools.

    Example:
        toolkit = ContainerSecurityToolkit()
        result = await toolkit.trivy_scan_image(image="nginx:latest")
        findings = await toolkit.trivy_get_findings(severity="CRITICAL")
    """

    name: str = "container_security"
    description: str = "Container and infrastructure security scanning powered by Trivy"

    def __init__(self, config: Optional[TrivyConfig] = None, **kwargs):
        """Initialize ContainerSecurityToolkit.

        Args:
            config: Optional TrivyConfig. Uses defaults if not provided.
            **kwargs: Additional arguments passed to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self.config = config or TrivyConfig()
        self.executor = TrivyExecutor(self.config)
        self.parser = TrivyParser()
        self._last_result: Optional[ScanResult] = None

    async def trivy_scan_image(
        self,
        image: str,
        severity: Optional[list[str]] = None,
        ignore_unfixed: bool = False,
        scanners: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan a container image for vulnerabilities, secrets, and misconfigurations.

        Executes a comprehensive security scan using Trivy to identify CVEs,
        exposed secrets, and Dockerfile misconfigurations.

        Args:
            image: Container image to scan (e.g., 'nginx:latest', 'myrepo/myapp:v1.2').
            severity: Filter by severity levels. Options: CRITICAL, HIGH, MEDIUM, LOW.
                Default: scan all severities.
            ignore_unfixed: If True, skip vulnerabilities without available fixes.
            scanners: Types of scanning to perform. Options: vuln, misconfig, secret, license.
                Default: ['vuln', 'secret'].

        Returns:
            ScanResult with CVEs, secrets, and misconfigs found in the image.

        Example:
            result = await toolkit.trivy_scan_image(
                image="nginx:latest",
                severity=["CRITICAL", "HIGH"],
                ignore_unfixed=True
            )
        """
        stdout, stderr, code = await self.executor.scan_image(
            image=image,
            severity=severity,
            ignore_unfixed=ignore_unfixed,
            scanners=scanners,
        )

        if code != 0:
            self.logger.error("Trivy image scan failed with code %d: %s", code, stderr)

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def trivy_scan_filesystem(
        self,
        path: str,
        severity: Optional[list[str]] = None,
        scanners: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan a local filesystem directory for vulnerabilities and secrets.

        Detects vulnerable dependencies, exposed secrets, and misconfigurations
        in a local directory.

        Args:
            path: Path to directory or file to scan.
            severity: Filter by severity levels. Options: CRITICAL, HIGH, MEDIUM, LOW.
            scanners: Types of scanning. Options: vuln, misconfig, secret, license.
                Default: ['vuln', 'secret', 'misconfig'].

        Returns:
            ScanResult with findings from the filesystem scan.

        Example:
            result = await toolkit.trivy_scan_filesystem(
                path="/app",
                scanners=["vuln", "secret"]
            )
        """
        stdout, stderr, code = await self.executor.scan_filesystem(
            path=path,
            severity=severity,
            scanners=scanners,
        )

        if code != 0:
            self.logger.error("Trivy fs scan failed with code %d: %s", code, stderr)

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def trivy_scan_repo(
        self,
        repo_url: str,
        branch: Optional[str] = None,
        severity: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan a Git repository for vulnerabilities.

        Clones and scans a Git repository to detect vulnerable dependencies
        and exposed secrets.

        Args:
            repo_url: Git repository URL (e.g., 'https://github.com/org/repo.git').
            branch: Branch to scan. If None, uses the default branch.
            severity: Filter by severity levels. Options: CRITICAL, HIGH, MEDIUM, LOW.

        Returns:
            ScanResult with findings from the repository scan.

        Example:
            result = await toolkit.trivy_scan_repo(
                repo_url="https://github.com/myorg/myapp.git",
                branch="main"
            )
        """
        stdout, stderr, code = await self.executor.scan_repository(
            repo_url=repo_url,
            branch=branch,
            severity=severity,
        )

        if code != 0:
            self.logger.error("Trivy repo scan failed with code %d: %s", code, stderr)

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def trivy_scan_k8s(
        self,
        context: Optional[str] = None,
        namespace: Optional[str] = None,
        compliance: Optional[str] = None,
        components: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan a Kubernetes cluster for vulnerabilities and misconfigurations.

        Scans running workloads, RBAC configurations, and cluster infrastructure
        for security issues.

        Args:
            context: Kubernetes context to use. If None, uses current context.
            namespace: Namespace to scan. If None, scans all namespaces.
            compliance: Compliance specification to check (e.g., 'k8s-cis-1.23').
            components: K8s components to scan. Options: workload, infra, rbac.

        Returns:
            ScanResult with findings from the Kubernetes cluster scan.

        Example:
            result = await toolkit.trivy_scan_k8s(
                context="prod-cluster",
                namespace="default",
                compliance="k8s-cis-1.23"
            )
        """
        stdout, stderr, code = await self.executor.scan_k8s(
            context=context,
            namespace=namespace,
            compliance=compliance,
            components=components,
        )

        if code != 0:
            self.logger.error("Trivy k8s scan failed with code %d: %s", code, stderr)

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def trivy_scan_iac(
        self,
        path: str,
        compliance: Optional[str] = None,
        config_type: Optional[str] = None,
    ) -> ScanResult:
        """Scan Infrastructure as Code configurations for misconfigurations.

        Detects security issues in Terraform, CloudFormation, Kubernetes manifests,
        Dockerfiles, and other IaC configurations.

        Args:
            path: Path to IaC configuration directory or file.
            compliance: Compliance specification (e.g., 'aws-cis-1.4.0').
            config_type: Configuration type hint (terraform, cloudformation,
                kubernetes, dockerfile). Auto-detected if not specified.

        Returns:
            ScanResult with IaC misconfigurations found.

        Example:
            result = await toolkit.trivy_scan_iac(
                path="./terraform",
                compliance="aws-cis-1.4.0"
            )
        """
        stdout, stderr, code = await self.executor.scan_config(
            path=path,
            compliance=compliance,
        )

        if code != 0:
            self.logger.error("Trivy IaC scan failed with code %d: %s", code, stderr)

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def trivy_generate_sbom(
        self,
        target: str,
        format: str = "cyclonedx",
        output_path: Optional[str] = None,
        scan_type: str = "image",
    ) -> str:
        """Generate a Software Bill of Materials (SBOM) for a target.

        Creates a machine-readable inventory of all software components,
        dependencies, and their versions.

        Args:
            target: Target to generate SBOM for (image name or filesystem path).
            format: SBOM format. Options: cyclonedx, spdx, spdx-json.
                Default: cyclonedx.
            output_path: Path to save the SBOM file. If None, returns content.
            scan_type: Type of target. Options: image, fs, repo.
                Default: image.

        Returns:
            Path to the generated SBOM file, or SBOM content if no output_path.

        Example:
            path = await toolkit.trivy_generate_sbom(
                target="myapp:v1",
                format="cyclonedx",
                output_path="/tmp/sbom.json"
            )
        """
        stdout, stderr, code = await self.executor.generate_sbom(
            target=target,
            scan_type=scan_type,
            sbom_format=format,
            output_file=output_path,
        )

        if code != 0:
            self.logger.error("SBOM generation failed with code %d: %s", code, stderr)

        if output_path:
            return output_path
        return stdout

    async def trivy_get_summary(self) -> dict:
        """Get summary statistics from the last scan.

        Returns aggregated metrics from the most recent scan including
        finding counts by severity and resource types scanned.

        Returns:
            Dictionary with summary statistics:
                - total_findings: Total number of findings
                - critical_count: Critical severity findings
                - high_count: High severity findings
                - medium_count: Medium severity findings
                - low_count: Low severity findings
                - info_count: Informational findings
                - services_scanned: List of scanned resource types
                - scan_timestamp: ISO timestamp of the scan
            Returns empty dict if no scan has been run.

        Example:
            summary = await toolkit.trivy_get_summary()
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
            "provider": summary.provider.value if summary.provider else None,
            "scan_timestamp": (
                summary.scan_timestamp.isoformat() if summary.scan_timestamp else None
            ),
        }

    async def trivy_get_findings(
        self,
        severity: Optional[str] = None,
        scanner_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[SecurityFinding]:
        """Get findings from the last scan with optional filters.

        Retrieves security findings from the most recent scan, optionally
        filtered by severity or scanner type (resource_type).

        Args:
            severity: Filter by severity level. Options: CRITICAL, HIGH,
                MEDIUM, LOW, INFO.
            scanner_type: Filter by scanner type (maps to resource_type).
                Options: vulnerability, secret, Dockerfile, etc.
            limit: Maximum number of findings to return.

        Returns:
            List of SecurityFinding objects matching the filters.
            Returns empty list if no scan has been run.

        Example:
            criticals = await toolkit.trivy_get_findings(severity="CRITICAL")
            vulns = await toolkit.trivy_get_findings(scanner_type="vulnerability")
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

        # Apply scanner_type filter (matches resource_type)
        if scanner_type:
            findings = [f for f in findings if f.resource_type == scanner_type]

        # Apply limit
        if limit and limit > 0:
            findings = findings[:limit]

        return findings

    async def trivy_generate_report(
        self,
        output_path: str,
        format: str = "html",
    ) -> str:
        """Generate a report from the last scan results.

        Creates a formatted report file from the most recent scan findings.

        Args:
            output_path: Path where the report file will be saved.
            format: Report format. Options: html, json.

        Returns:
            Path to the generated report file.

        Raises:
            ValueError: If no scan has been run yet.

        Example:
            path = await toolkit.trivy_generate_report(
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
            # Placeholder for HTML generation
            self.parser.save_result(self._last_result, output_path)
            self.logger.info(
                "Report format '%s' not fully implemented, saved as JSON", format
            )

        return output_path

    async def trivy_compare_scans(
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
                - severity_trend: Change in severity counts
                - summary: Human-readable summary of changes

        Raises:
            ValueError: If no current scan results or baseline cannot be loaded.

        Example:
            delta = await toolkit.trivy_compare_scans(
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
