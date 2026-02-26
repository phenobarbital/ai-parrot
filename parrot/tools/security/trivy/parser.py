"""Trivy output parser.

Parses Trivy's JSON output (vulnerabilities, secrets, misconfigurations)
into unified SecurityFinding and ScanResult models.
"""

import json
from datetime import datetime
from typing import Optional

from ..base_parser import BaseParser
from ..models import (
    CloudProvider,
    FindingSource,
    ScanResult,
    ScanSummary,
    SecurityFinding,
    SeverityLevel,
)


class TrivyParser(BaseParser):
    """Parser for Trivy JSON output.

    Normalizes Trivy findings from vulnerability scans, secret detection,
    and misconfiguration checks into the unified SecurityFinding format.

    Supports:
    - Container image vulnerabilities
    - Filesystem and repository vulnerabilities
    - Secret detection findings
    - IaC misconfigurations (Dockerfile, Kubernetes, Terraform, etc.)

    Example:
        parser = TrivyParser()
        result = parser.parse(trivy_json_output)
        for finding in result.findings:
            print(f"{finding.severity}: {finding.title}")
    """

    # Map Trivy severity strings to unified SeverityLevel
    SEVERITY_MAP: dict[str, SeverityLevel] = {
        "CRITICAL": SeverityLevel.CRITICAL,
        "HIGH": SeverityLevel.HIGH,
        "MEDIUM": SeverityLevel.MEDIUM,
        "LOW": SeverityLevel.LOW,
        "UNKNOWN": SeverityLevel.UNKNOWN,
    }

    def parse(self, raw_output: str) -> ScanResult:
        """Parse raw Trivy JSON output into a ScanResult.

        Handles multiple result types (vulnerabilities, secrets, misconfigs)
        within a single Trivy output.

        Args:
            raw_output: Raw JSON string from Trivy scan.

        Returns:
            ScanResult with normalized findings and summary.
        """
        if not raw_output or not raw_output.strip():
            return self._empty_result()

        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError as e:
            self.logger.warning("Failed to parse Trivy JSON: %s", e)
            return self._empty_result()

        findings: list[SecurityFinding] = []
        artifact_name = data.get("ArtifactName", "unknown")

        # Process each result entry
        results = data.get("Results", [])
        for result_entry in results:
            target = result_entry.get("Target", "")

            # Process vulnerabilities
            vulns = result_entry.get("Vulnerabilities", [])
            for vuln in vulns:
                try:
                    finding = self.normalize_vulnerability(vuln, target=target)
                    findings.append(finding)
                except Exception as e:
                    self.logger.warning("Failed to normalize vulnerability: %s", e)

            # Process secrets
            secrets = result_entry.get("Secrets", [])
            for secret in secrets:
                try:
                    finding = self.normalize_secret(secret, target=target)
                    findings.append(finding)
                except Exception as e:
                    self.logger.warning("Failed to normalize secret: %s", e)

            # Process misconfigurations
            misconfigs = result_entry.get("Misconfigurations", [])
            for misconfig in misconfigs:
                try:
                    finding = self.normalize_misconfiguration(misconfig, target=target)
                    findings.append(finding)
                except Exception as e:
                    self.logger.warning("Failed to normalize misconfiguration: %s", e)

        # Build summary
        summary = self._build_summary(findings, artifact_name)

        return ScanResult(findings=findings, summary=summary)

    def normalize_finding(self, raw_finding: dict) -> SecurityFinding:
        """Normalize a raw finding (generic dispatch).

        This method dispatches to the appropriate normalize method based on
        the presence of specific keys in the raw finding.

        Args:
            raw_finding: Dictionary from Trivy output.

        Returns:
            Normalized SecurityFinding.
        """
        if "VulnerabilityID" in raw_finding:
            return self.normalize_vulnerability(raw_finding)
        elif "RuleID" in raw_finding:
            return self.normalize_secret(raw_finding)
        elif "ID" in raw_finding and "Type" in raw_finding:
            return self.normalize_misconfiguration(raw_finding)
        else:
            # Fallback for unknown finding type
            return SecurityFinding(
                id=raw_finding.get("id", "unknown"),
                source=FindingSource.TRIVY,
                severity=SeverityLevel.UNKNOWN,
                title=raw_finding.get("Title", "Unknown finding"),
                raw=raw_finding,
            )

    def normalize_vulnerability(
        self, raw_vuln: dict, target: Optional[str] = None
    ) -> SecurityFinding:
        """Normalize a Trivy vulnerability finding.

        Args:
            raw_vuln: Vulnerability dictionary from Trivy output.
            target: Optional target context (e.g., image layer).

        Returns:
            Normalized SecurityFinding.
        """
        vuln_id = raw_vuln.get("VulnerabilityID", "unknown")
        pkg_name = raw_vuln.get("PkgName", "")
        installed_version = raw_vuln.get("InstalledVersion", "")
        fixed_version = raw_vuln.get("FixedVersion")

        # Build resource identifier
        resource = f"{pkg_name}@{installed_version}" if pkg_name else None

        # Map severity
        severity_str = raw_vuln.get("Severity", "UNKNOWN")
        severity = self._map_severity(severity_str)

        # Build remediation text
        remediation = None
        if fixed_version:
            remediation = f"Upgrade {pkg_name} to version {fixed_version}"

        # Include references in remediation
        references = raw_vuln.get("References", [])
        if references:
            ref_text = "\n".join(references[:3])  # Limit to first 3 refs
            if remediation:
                remediation = f"{remediation}\n\nReferences:\n{ref_text}"
            else:
                remediation = f"References:\n{ref_text}"

        return SecurityFinding(
            id=f"trivy-{vuln_id}-{pkg_name}",
            source=FindingSource.TRIVY,
            severity=severity,
            title=raw_vuln.get("Title", vuln_id),
            description=raw_vuln.get("Description", ""),
            resource=resource,
            resource_type="vulnerability",
            check_id=vuln_id,
            service=target,
            remediation=remediation,
            raw=raw_vuln,
            timestamp=datetime.now(),
        )

    def normalize_secret(
        self, raw_secret: dict, target: Optional[str] = None
    ) -> SecurityFinding:
        """Normalize a Trivy secret detection finding.

        Secret values are masked for security.

        Args:
            raw_secret: Secret dictionary from Trivy output.
            target: Optional target context (e.g., file path).

        Returns:
            Normalized SecurityFinding with masked secret value.
        """
        rule_id = raw_secret.get("RuleID", "unknown")
        category = raw_secret.get("Category", "")
        match_value = raw_secret.get("Match", "")

        # Mask the secret value (show first 4 and last 4 chars if long enough)
        masked_value = self._mask_secret(match_value)

        # Build description with masked value
        description = f"Detected {category} secret: {masked_value}"
        if raw_secret.get("StartLine"):
            description += f" (line {raw_secret['StartLine']})"

        # Map severity
        severity_str = raw_secret.get("Severity", "CRITICAL")
        severity = self._map_severity(severity_str)

        return SecurityFinding(
            id=f"trivy-secret-{rule_id}-{hash(match_value) % 10000}",
            source=FindingSource.TRIVY,
            severity=severity,
            title=raw_secret.get("Title", f"Secret: {rule_id}"),
            description=description,
            resource=target,
            resource_type="secret",
            check_id=rule_id,
            service=category,
            remediation="Remove or rotate the exposed secret and add to .gitignore",
            raw={k: v for k, v in raw_secret.items() if k != "Match"},  # Exclude raw match
            timestamp=datetime.now(),
        )

    def normalize_misconfiguration(
        self, raw_misconfig: dict, target: Optional[str] = None
    ) -> SecurityFinding:
        """Normalize a Trivy misconfiguration finding.

        Args:
            raw_misconfig: Misconfiguration dictionary from Trivy output.
            target: Optional target context (e.g., file path).

        Returns:
            Normalized SecurityFinding.
        """
        check_id = raw_misconfig.get("ID", "unknown")
        config_type = raw_misconfig.get("Type", "unknown")

        # Map severity
        severity_str = raw_misconfig.get("Severity", "MEDIUM")
        severity = self._map_severity(severity_str)

        # Build remediation
        remediation = raw_misconfig.get("Resolution")
        references = raw_misconfig.get("References", [])
        if references and remediation:
            ref_text = "\n".join(references[:2])
            remediation = f"{remediation}\n\nReferences:\n{ref_text}"
        elif references:
            remediation = f"References:\n{references[0]}"

        return SecurityFinding(
            id=f"trivy-misconfig-{check_id}",
            source=FindingSource.TRIVY,
            severity=severity,
            title=raw_misconfig.get("Title", check_id),
            description=raw_misconfig.get("Description", ""),
            resource=target,
            resource_type=config_type,
            check_id=check_id,
            remediation=remediation,
            raw=raw_misconfig,
            timestamp=datetime.now(),
        )

    def _map_severity(self, trivy_severity: str) -> SeverityLevel:
        """Map Trivy severity string to unified SeverityLevel.

        Args:
            trivy_severity: Trivy severity string (e.g., "HIGH", "CRITICAL").

        Returns:
            Unified SeverityLevel enum value.
        """
        if not trivy_severity:
            return SeverityLevel.UNKNOWN
        return self.SEVERITY_MAP.get(trivy_severity.upper(), SeverityLevel.UNKNOWN)

    def _mask_secret(self, value: str) -> str:
        """Mask a secret value for safe display.

        Shows first 4 and last 4 characters if the value is long enough,
        otherwise shows partial masking appropriate to length.

        Args:
            value: Raw secret value.

        Returns:
            Masked version of the secret.
        """
        if not value:
            return "***"

        length = len(value)
        if length <= 4:
            return "***"
        elif length <= 8:
            return f"{value[:2]}***"
        else:
            return f"{value[:4]}***{value[-4:]}"

    def _build_summary(
        self, findings: list[SecurityFinding], artifact_name: str
    ) -> ScanSummary:
        """Build scan summary from findings.

        Args:
            findings: List of normalized SecurityFinding objects.
            artifact_name: Name of the scanned artifact.

        Returns:
            ScanSummary with counts and metadata.
        """
        critical_count = 0
        high_count = 0
        medium_count = 0
        low_count = 0
        info_count = 0

        resource_types: set[str] = set()

        for finding in findings:
            # Count by severity
            if finding.severity == SeverityLevel.CRITICAL:
                critical_count += 1
            elif finding.severity == SeverityLevel.HIGH:
                high_count += 1
            elif finding.severity == SeverityLevel.MEDIUM:
                medium_count += 1
            elif finding.severity == SeverityLevel.LOW:
                low_count += 1
            elif finding.severity == SeverityLevel.INFO:
                info_count += 1

            # Collect resource types
            if finding.resource_type:
                resource_types.add(finding.resource_type)

        return ScanSummary(
            source=FindingSource.TRIVY,
            provider=CloudProvider.LOCAL,  # Trivy scans containers/filesystems locally
            total_findings=len(findings),
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            info_count=info_count,
            pass_count=0,  # Trivy doesn't report passing checks
            scan_timestamp=datetime.now(),
            services_scanned=list(resource_types),
            regions_scanned=[],
        )

    def _empty_result(self) -> ScanResult:
        """Return an empty ScanResult for error cases."""
        return ScanResult(
            findings=[],
            summary=ScanSummary(
                source=FindingSource.TRIVY,
                provider=CloudProvider.LOCAL,
                total_findings=0,
                scan_timestamp=datetime.now(),
            ),
        )
