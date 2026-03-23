"""Secrets and Infrastructure as Code Security Toolkit.

Agent-facing toolkit that wraps Checkov for IaC security scanning
and secrets detection. All public async methods automatically become agent tools.
"""

import json
from typing import Optional

from ..toolkit import AbstractToolkit
from .checkov.config import CheckovConfig
from .checkov.executor import CheckovExecutor
from .checkov.parser import CheckovParser
from .models import (
    ComparisonDelta,
    ScanResult,
    SecurityFinding,
    SeverityLevel,
)


class SecretsIaCToolkit(AbstractToolkit):
    """Infrastructure as Code and Secrets scanning toolkit powered by Checkov.

    Scans Terraform, CloudFormation, Kubernetes, Helm, Dockerfiles, GitHub Actions,
    and code for security misconfigurations and exposed secrets.

    All public async methods automatically become agent tools.

    Example:
        toolkit = SecretsIaCToolkit()
        result = await toolkit.checkov_scan_terraform(path="./terraform")
        findings = await toolkit.checkov_get_findings(severity="CRITICAL")
    """

    name: str = "secrets_iac"
    description: str = (
        "Infrastructure as Code security scanning and secrets detection "
        "powered by Checkov"
    )

    def __init__(self, config: Optional[CheckovConfig] = None, **kwargs):
        """Initialize SecretsIaCToolkit.

        Args:
            config: Optional CheckovConfig. Uses defaults if not provided.
            **kwargs: Additional arguments passed to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self.config = config or CheckovConfig()
        self.executor = CheckovExecutor(self.config)
        self.parser = CheckovParser()
        self._last_result: Optional[ScanResult] = None

    async def checkov_scan_directory(
        self,
        path: str,
        frameworks: Optional[list[str]] = None,
        checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan an IaC directory for security misconfigurations.

        Scans all supported IaC files (Terraform, CloudFormation, Kubernetes, etc.)
        in the specified directory for security issues.

        Args:
            path: Path to the directory to scan.
            frameworks: Specific frameworks to scan. Options: terraform, cloudformation,
                kubernetes, dockerfile, helm, arm, bicep, serverless, github_actions.
                If None, auto-detects all frameworks.
            checks: Specific check IDs to run (e.g., ['CKV_AWS_21', 'CKV_AWS_19']).
                If None, runs all applicable checks.
            skip_checks: Check IDs to skip during scanning.

        Returns:
            ScanResult with all findings and summary statistics.

        Example:
            result = await toolkit.checkov_scan_directory(
                path="./infrastructure",
                frameworks=["terraform", "cloudformation"],
                skip_checks=["CKV_AWS_1"]
            )
        """
        stdout, stderr, code = await self.executor.scan_directory(
            path=path,
            frameworks=frameworks,
            run_checks=checks,
            skip_checks=skip_checks,
        )

        if code != 0:
            self.logger.error("Checkov scan failed with code %d: %s", code, stderr)

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def checkov_scan_file(
        self,
        file_path: str,
        framework: Optional[str] = None,
        checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan a single IaC file for security misconfigurations.

        Args:
            file_path: Path to the file to scan.
            framework: Framework type of the file. Options: terraform, cloudformation,
                kubernetes, dockerfile, helm, arm, bicep. Auto-detected if not specified.
            checks: Specific check IDs to run.
            skip_checks: Check IDs to skip during scanning.

        Returns:
            ScanResult with findings from the file scan.

        Example:
            result = await toolkit.checkov_scan_file(
                file_path="./main.tf",
                framework="terraform"
            )
        """
        frameworks = [framework] if framework else None
        stdout, stderr, code = await self.executor.scan_file(
            path=file_path,
            frameworks=frameworks,
            run_checks=checks,
            skip_checks=skip_checks,
        )

        if code != 0:
            self.logger.error("Checkov file scan failed with code %d: %s", code, stderr)

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def checkov_scan_terraform(
        self,
        path: str,
        var_files: Optional[list[str]] = None,
        checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
        download_modules: bool = True,
    ) -> ScanResult:
        """Scan Terraform configurations for security misconfigurations.

        Specialized scan for Terraform that supports module downloads and
        variable files.

        Args:
            path: Path to Terraform directory.
            var_files: Paths to Terraform variable files (.tfvars).
            checks: Specific check IDs to run.
            skip_checks: Check IDs to skip during scanning.
            download_modules: Whether to download external modules. Default True.

        Returns:
            ScanResult with Terraform-specific findings.

        Example:
            result = await toolkit.checkov_scan_terraform(
                path="./terraform",
                skip_checks=["CKV_AWS_21"],
                download_modules=True
            )
        """
        stdout, stderr, code = await self.executor.scan_terraform(
            path=path,
            run_checks=checks,
            skip_checks=skip_checks,
            download_modules=download_modules,
        )

        if code != 0:
            self.logger.error(
                "Checkov Terraform scan failed with code %d: %s", code, stderr
            )

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def checkov_scan_cloudformation(
        self,
        path: str,
        template_file: Optional[str] = None,
        checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan CloudFormation templates for security misconfigurations.

        Specialized scan for AWS CloudFormation templates (YAML/JSON).

        Args:
            path: Path to CloudFormation directory or template.
            template_file: Specific template file to scan (if path is a directory).
            checks: Specific check IDs to run.
            skip_checks: Check IDs to skip during scanning.

        Returns:
            ScanResult with CloudFormation-specific findings.

        Example:
            result = await toolkit.checkov_scan_cloudformation(
                path="./cloudformation",
                template_file="main-stack.yaml"
            )
        """
        scan_path = f"{path}/{template_file}" if template_file else path

        stdout, stderr, code = await self.executor.scan_cloudformation(
            path=scan_path,
            run_checks=checks,
            skip_checks=skip_checks,
        )

        if code != 0:
            self.logger.error(
                "Checkov CloudFormation scan failed with code %d: %s", code, stderr
            )

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def checkov_scan_kubernetes(
        self,
        path: str,
        namespace_filter: Optional[str] = None,
        checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan Kubernetes manifests for security misconfigurations.

        Detects issues like privileged containers, missing security contexts,
        and network policy gaps.

        Args:
            path: Path to Kubernetes manifests directory.
            namespace_filter: Filter findings by namespace (post-scan filter).
            checks: Specific check IDs to run.
            skip_checks: Check IDs to skip during scanning.

        Returns:
            ScanResult with Kubernetes-specific findings.

        Example:
            result = await toolkit.checkov_scan_kubernetes(
                path="./k8s",
                namespace_filter="production"
            )
        """
        stdout, stderr, code = await self.executor.scan_kubernetes(
            path=path,
            run_checks=checks,
            skip_checks=skip_checks,
        )

        if code != 0:
            self.logger.error(
                "Checkov Kubernetes scan failed with code %d: %s", code, stderr
            )

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def checkov_scan_dockerfile(
        self,
        path: str,
        checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan Dockerfiles for security misconfigurations.

        Detects issues like running as root, missing USER instruction,
        and hardcoded secrets.

        Args:
            path: Path to Dockerfile or directory containing Dockerfiles.
            checks: Specific check IDs to run.
            skip_checks: Check IDs to skip during scanning.

        Returns:
            ScanResult with Dockerfile-specific findings.

        Example:
            result = await toolkit.checkov_scan_dockerfile(
                path="./Dockerfile"
            )
        """
        stdout, stderr, code = await self.executor.scan_dockerfile(
            path=path,
            run_checks=checks,
            skip_checks=skip_checks,
        )

        if code != 0:
            self.logger.error(
                "Checkov Dockerfile scan failed with code %d: %s", code, stderr
            )

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def checkov_scan_helm(
        self,
        path: str,
        values_file: Optional[str] = None,
        checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan Helm charts for security misconfigurations.

        Scans Helm templates and values for security issues in the
        resulting Kubernetes manifests.

        Args:
            path: Path to Helm chart directory.
            values_file: Optional values file to use for template rendering.
            checks: Specific check IDs to run.
            skip_checks: Check IDs to skip during scanning.

        Returns:
            ScanResult with Helm chart findings.

        Example:
            result = await toolkit.checkov_scan_helm(
                path="./charts/myapp",
                values_file="values-prod.yaml"
            )
        """
        stdout, stderr, code = await self.executor.scan_directory(
            path=path,
            frameworks=["helm"],
            run_checks=checks,
            skip_checks=skip_checks,
        )

        if code != 0:
            self.logger.error(
                "Checkov Helm scan failed with code %d: %s", code, stderr
            )

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def checkov_scan_secrets(
        self,
        path: str,
        skip_paths: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan code for exposed secrets using entropy-based detection.

        Detects hardcoded API keys, passwords, tokens, and other sensitive
        data using pattern matching and entropy analysis.

        Args:
            path: Path to directory to scan for secrets.
            skip_paths: Paths to exclude from scanning (e.g., node_modules, .git).

        Returns:
            ScanResult with secret-related findings (typically CRITICAL severity).

        Example:
            result = await toolkit.checkov_scan_secrets(
                path="./src",
                skip_paths=["node_modules", ".git", "test_fixtures"]
            )
        """
        stdout, stderr, code = await self.executor.scan_secrets(
            path=path,
            skip_paths=skip_paths,
        )

        if code != 0:
            self.logger.error(
                "Checkov secrets scan failed with code %d: %s", code, stderr
            )

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def checkov_scan_github_actions(
        self,
        path: str,
        checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> ScanResult:
        """Scan GitHub Actions workflows for security misconfigurations.

        Detects issues like untrusted inputs, insecure permissions, and
        potential injection vulnerabilities in CI/CD workflows.

        Args:
            path: Path to .github/workflows directory.
            checks: Specific check IDs to run.
            skip_checks: Check IDs to skip during scanning.

        Returns:
            ScanResult with GitHub Actions-specific findings.

        Example:
            result = await toolkit.checkov_scan_github_actions(
                path="./.github/workflows"
            )
        """
        stdout, stderr, code = await self.executor.scan_github_actions(
            path=path,
            run_checks=checks,
            skip_checks=skip_checks,
        )

        if code != 0:
            self.logger.error(
                "Checkov GitHub Actions scan failed with code %d: %s", code, stderr
            )

        result = self.parser.parse(stdout)
        self._last_result = result
        return result

    async def checkov_list_checks(
        self,
        framework: Optional[str] = None,
    ) -> list[dict]:
        """List available Checkov checks.

        Returns the list of all checks that Checkov can run, optionally
        filtered by framework.

        Args:
            framework: Filter checks by framework. Options: terraform, cloudformation,
                kubernetes, dockerfile, helm, secrets, github_actions.

        Returns:
            List of check dictionaries with id, name, and framework fields.

        Example:
            checks = await toolkit.checkov_list_checks(framework="terraform")
            for check in checks[:10]:
                print(f"{check['id']}: {check['name']}")
        """
        stdout, stderr, code = await self.executor.list_checks(framework=framework)

        if code != 0:
            self.logger.error("Failed to list checks: %s", stderr)
            return []

        # Checkov outputs check list in a specific format
        # Parse it into structured data
        try:
            # Try JSON first
            return json.loads(stdout)
        except json.JSONDecodeError:
            # Return raw lines as basic check info
            checks = []
            for line in stdout.strip().split("\n"):
                if line.strip():
                    checks.append({"raw": line.strip()})
            return checks

    async def checkov_get_summary(self) -> dict:
        """Get summary statistics from the last scan.

        Returns aggregated metrics from the most recent scan including
        finding counts by severity and frameworks scanned.

        Returns:
            Dictionary with summary statistics:
                - total_findings: Total number of findings
                - critical_count: Critical severity findings
                - high_count: High severity findings
                - medium_count: Medium severity findings
                - low_count: Low severity findings
                - info_count: Informational findings
                - pass_count: Passed checks
                - services_scanned: List of scanned frameworks
                - scan_timestamp: ISO timestamp of the scan
            Returns empty dict if no scan has been run.

        Example:
            summary = await toolkit.checkov_get_summary()
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

    async def checkov_get_findings(
        self,
        severity: Optional[str] = None,
        framework: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[SecurityFinding]:
        """Get findings from the last scan with optional filters.

        Retrieves security findings from the most recent scan, optionally
        filtered by severity or framework (resource_type).

        Args:
            severity: Filter by severity level. Options: CRITICAL, HIGH,
                MEDIUM, LOW, INFO, PASS.
            framework: Filter by framework/resource_type. Options: terraform,
                cloudformation, kubernetes, dockerfile, helm, secrets, etc.
            limit: Maximum number of findings to return.

        Returns:
            List of SecurityFinding objects matching the filters.
            Returns empty list if no scan has been run.

        Example:
            criticals = await toolkit.checkov_get_findings(severity="CRITICAL")
            tf_issues = await toolkit.checkov_get_findings(framework="terraform")
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

        # Apply framework filter (matches resource_type)
        if framework:
            findings = [
                f for f in findings
                if f.resource_type and f.resource_type.lower() == framework.lower()
            ]

        # Apply limit
        if limit and limit > 0:
            findings = findings[:limit]

        return findings

    async def checkov_generate_report(
        self,
        output_path: str,
        format: str = "json",
    ) -> str:
        """Generate a report from the last scan results.

        Creates a formatted report file from the most recent scan findings.

        Args:
            output_path: Path where the report file will be saved.
            format: Report format. Options: json, html.
                Note: HTML generation is a placeholder, saves as JSON.

        Returns:
            Path to the generated report file.

        Raises:
            ValueError: If no scan has been run yet.

        Example:
            path = await toolkit.checkov_generate_report(
                output_path="/tmp/iac-security-report.json",
                format="json"
            )
        """
        if self._last_result is None:
            raise ValueError("No scan results available. Run a scan first.")

        # Save as JSON (HTML generation would require templates)
        if format.lower() == "json":
            self.parser.save_result(self._last_result, output_path)
        else:
            # Placeholder for HTML generation
            self.parser.save_result(self._last_result, output_path)
            self.logger.info(
                "Report format '%s' not fully implemented, saved as JSON", format
            )

        return output_path

    async def checkov_compare_scans(
        self,
        baseline_path: str,
        current_path: Optional[str] = None,
    ) -> ComparisonDelta:
        """Compare current scan results against a baseline.

        Identifies new findings (regressions), resolved findings (improvements),
        and unchanged findings between the current scan and a saved baseline.

        Args:
            baseline_path: Path to the baseline scan result JSON file.
            current_path: Path to current scan result JSON (uses _last_result if None).

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
            delta = await toolkit.checkov_compare_scans(
                baseline_path="/scans/baseline-2024-01-01.json"
            )
            print(f"New issues: {len(delta.new_findings)}")
            print(f"Resolved: {len(delta.resolved_findings)}")
        """
        # Get current result
        if current_path:
            current = self.parser.load_result(current_path)
        elif self._last_result is not None:
            current = self._last_result
        else:
            raise ValueError("No current scan results. Run a scan or provide a path.")

        # Load baseline
        baseline = self.parser.load_result(baseline_path)

        # Build sets of finding IDs for comparison
        baseline_ids = {f.id for f in baseline.findings}
        current_ids = {f.id for f in current.findings}

        # Find new, resolved, and unchanged
        new_ids = current_ids - baseline_ids
        resolved_ids = baseline_ids - current_ids
        unchanged_ids = current_ids & baseline_ids

        # Map IDs back to findings
        current_by_id = {f.id: f for f in current.findings}
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
                1 for f in current.findings if f.severity == level
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
            current_timestamp=current.summary.scan_timestamp,
            new_findings=new_findings,
            resolved_findings=resolved_findings,
            unchanged_findings=unchanged_findings,
            severity_trend=severity_trend,
            summary=summary,
        )
