"""Prowler output parser.

Parses Prowler's JSON-OCSF output into unified SecurityFinding and ScanResult models.
Supports both JSON array and newline-delimited JSON (NDJSON) formats.
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


class ProwlerParser(BaseParser):
    """Parser for Prowler JSON-OCSF output.

    Normalizes Prowler findings into unified SecurityFinding format,
    enabling cross-tool aggregation with Trivy and Checkov.

    Supported formats:
    - JSON array: [{"finding_info": ...}, ...]
    - NDJSON: {"finding_info": ...}\\n{"finding_info": ...}
    """

    # Map Prowler severity strings to unified SeverityLevel
    SEVERITY_MAP: dict[str, SeverityLevel] = {
        "critical": SeverityLevel.CRITICAL,
        "high": SeverityLevel.HIGH,
        "medium": SeverityLevel.MEDIUM,
        "low": SeverityLevel.LOW,
        "informational": SeverityLevel.INFO,
        "info": SeverityLevel.INFO,
    }

    # Map Prowler resource types to cloud providers
    PROVIDER_MAP: dict[str, CloudProvider] = {
        "aws": CloudProvider.AWS,
        "azure": CloudProvider.AZURE,
        "gcp": CloudProvider.GCP,
        "kubernetes": CloudProvider.KUBERNETES,
    }

    def parse(self, raw_output: str) -> ScanResult:
        """Parse raw Prowler output into a ScanResult.

        Handles both JSON array and NDJSON formats.

        Args:
            raw_output: Raw string output from Prowler (JSON-OCSF format).

        Returns:
            ScanResult with normalized findings and summary.
        """
        if not raw_output or not raw_output.strip():
            return self._empty_result()

        # Try parsing as JSON array first
        raw_findings = self._parse_json(raw_output)
        if raw_findings is None:
            return self._empty_result()

        # Normalize all findings
        findings = []
        for raw in raw_findings:
            try:
                finding = self.normalize_finding(raw)
                findings.append(finding)
            except Exception as e:
                self.logger.warning("Failed to normalize finding: %s", e)
                continue

        # Build summary
        summary = self._build_summary(findings)

        return ScanResult(findings=findings, summary=summary)

    def normalize_finding(self, raw_finding: dict) -> SecurityFinding:
        """Convert a Prowler OCSF finding to unified SecurityFinding.

        Args:
            raw_finding: Dictionary from Prowler JSON-OCSF output.

        Returns:
            Normalized SecurityFinding instance.
        """
        # Extract finding_info
        finding_info = raw_finding.get("finding_info", {})
        uid = finding_info.get("uid", "unknown")
        title = finding_info.get("title", "")
        description = finding_info.get("desc", "")

        # Determine severity based on status
        status = raw_finding.get("status", "FAIL")
        if status == "PASS":
            severity = SeverityLevel.PASS
        elif status == "MANUAL":
            severity = SeverityLevel.INFO
        else:
            # Map Prowler severity to unified level
            prowler_severity = raw_finding.get("severity", "medium")
            severity = self._map_severity(prowler_severity)

        # Extract resource info
        resources = raw_finding.get("resources", [])
        resource_uid = None
        region = "global"
        resource_type = None

        if resources and isinstance(resources, list) and len(resources) > 0:
            first_resource = resources[0]
            resource_uid = first_resource.get("uid")
            region = first_resource.get("region", "global")
            resource_type = first_resource.get("type")

        # Extract unmapped fields (compliance tags, service)
        unmapped = raw_finding.get("unmapped", {})
        compliance_tags = unmapped.get("check_type", [])
        if isinstance(compliance_tags, str):
            compliance_tags = [compliance_tags]
        service = unmapped.get("service_name")

        # Extract remediation
        remediation_data = raw_finding.get("remediation", {})
        remediation = remediation_data.get("desc") if isinstance(remediation_data, dict) else None

        # Determine cloud provider from resource type or UID
        provider = self._detect_provider(resource_uid, resource_type)

        # Extract check_id from uid (format: prowler-<provider>-<check_id>-<resource>)
        check_id = self._extract_check_id(uid)

        return SecurityFinding(
            id=uid,
            source=FindingSource.PROWLER,
            severity=severity,
            title=title,
            description=description,
            resource=resource_uid,
            resource_type=resource_type,
            region=region,
            provider=provider,
            service=service,
            check_id=check_id,
            compliance_tags=compliance_tags,
            remediation=remediation,
            raw=raw_finding,
            timestamp=datetime.now(),
        )

    def _parse_json(self, raw_output: str) -> Optional[list[dict]]:
        """Parse JSON from raw output (array or NDJSON).

        Args:
            raw_output: Raw string that may be JSON array or NDJSON.

        Returns:
            List of finding dictionaries, or None if parsing fails.
        """
        stripped = raw_output.strip()

        # Try JSON array first
        if stripped.startswith("["):
            try:
                data = json.loads(stripped)
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        # Try NDJSON (newline-delimited JSON)
        findings = []
        for line in stripped.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    findings.append(obj)
                elif isinstance(obj, list):
                    # Handle case where entire array is on one line
                    findings.extend(obj)
            except json.JSONDecodeError:
                self.logger.warning("Failed to parse line as JSON: %s...", line[:50])
                continue

        return findings if findings else None

    def _map_severity(self, prowler_severity: str) -> SeverityLevel:
        """Map Prowler severity string to unified SeverityLevel.

        Args:
            prowler_severity: Prowler severity string (e.g., "High", "critical").

        Returns:
            Unified SeverityLevel enum value.
        """
        if not prowler_severity:
            return SeverityLevel.UNKNOWN
        return self.SEVERITY_MAP.get(
            prowler_severity.lower(), SeverityLevel.UNKNOWN
        )

    def _detect_provider(
        self, resource_uid: Optional[str], resource_type: Optional[str]
    ) -> Optional[CloudProvider]:
        """Detect cloud provider from resource information.

        Args:
            resource_uid: Resource ARN or identifier.
            resource_type: Resource type string.

        Returns:
            CloudProvider enum value or None.
        """
        if resource_uid:
            if resource_uid.startswith("arn:aws:"):
                return CloudProvider.AWS
            if resource_uid.startswith("/subscriptions/"):
                return CloudProvider.AZURE
            if "projects/" in resource_uid:
                return CloudProvider.GCP

        if resource_type:
            type_lower = resource_type.lower()
            if type_lower.startswith("aws"):
                return CloudProvider.AWS
            if type_lower.startswith("azure"):
                return CloudProvider.AZURE
            if type_lower.startswith("gcp") or type_lower.startswith("google"):
                return CloudProvider.GCP

        return None

    def _extract_check_id(self, uid: str) -> Optional[str]:
        """Extract check ID from Prowler finding UID.

        Prowler UID format: prowler-<provider>-<check_id>-<resource_suffix>

        Args:
            uid: Finding UID string.

        Returns:
            Check ID or None if cannot extract.
        """
        if not uid or not uid.startswith("prowler-"):
            return uid

        parts = uid.split("-")
        if len(parts) >= 3:
            # Skip "prowler" and provider, take the check_id parts
            # Format: prowler-aws-s3_bucket_public_access-bucket1
            # We want: s3_bucket_public_access
            # Find the last part that looks like a resource suffix
            check_parts = parts[2:-1] if len(parts) > 3 else parts[2:]
            return "-".join(check_parts) if check_parts else parts[2]

        return uid

    def _build_summary(self, findings: list[SecurityFinding]) -> ScanSummary:
        """Build scan summary from findings.

        Args:
            findings: List of normalized SecurityFinding objects.

        Returns:
            ScanSummary with counts and metadata.
        """
        critical_count = 0
        high_count = 0
        medium_count = 0
        low_count = 0
        info_count = 0
        pass_count = 0

        services: set[str] = set()
        regions: set[str] = set()

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
            elif finding.severity == SeverityLevel.PASS:
                pass_count += 1

            # Collect services and regions
            if finding.service:
                services.add(finding.service)
            if finding.region and finding.region != "global":
                regions.add(finding.region)

        # Determine provider from findings
        provider = CloudProvider.AWS  # Default
        for finding in findings:
            if finding.provider:
                provider = finding.provider
                break

        return ScanSummary(
            source=FindingSource.PROWLER,
            provider=provider,
            total_findings=len(findings),
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            info_count=info_count,
            pass_count=pass_count,
            scan_timestamp=datetime.now(),
            services_scanned=list(services),
            regions_scanned=list(regions),
        )

    def _empty_result(self) -> ScanResult:
        """Return an empty ScanResult for error cases."""
        return ScanResult(
            findings=[],
            summary=ScanSummary(
                source=FindingSource.PROWLER,
                provider=CloudProvider.AWS,
                total_findings=0,
                scan_timestamp=datetime.now(),
            ),
        )
