"""Checkov output parser.

Parses Checkov's JSON output (IaC misconfigurations) into unified
SecurityFinding and ScanResult models.
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


class CheckovParser(BaseParser):
    """Parser for Checkov JSON output.

    Normalizes Checkov findings from IaC scans into the unified SecurityFinding
    format, enabling cross-tool aggregation with Prowler and Trivy.

    Checkov scans Terraform, CloudFormation, Kubernetes, Helm, Dockerfiles,
    and many other IaC formats.

    Example:
        parser = CheckovParser()
        result = parser.parse(checkov_json_output)
        for finding in result.findings:
            print(f"{finding.severity}: {finding.title}")
    """

    # High-severity check patterns (IAM, encryption, secrets, public access)
    HIGH_SEVERITY_PATTERNS = [
        "iam",
        "password",
        "mfa",
        "root",
        "encryption",
        "encrypt",
        "kms",
        "public",
        "exposed",
        "secret",
        "credential",
        "key",
        "token",
        "auth",
    ]

    # Critical-severity check patterns
    CRITICAL_SEVERITY_PATTERNS = [
        "secret",
        "credential",
        "hardcoded",
        "plaintext",
        "password_in",
    ]

    def parse(self, raw_output: str) -> ScanResult:
        """Parse raw Checkov JSON output into a ScanResult.

        Handles Checkov's JSON format with passed_checks, failed_checks,
        and skipped_checks arrays.

        Args:
            raw_output: Raw JSON string from Checkov scan.

        Returns:
            ScanResult with normalized findings and summary.
        """
        if not raw_output or not raw_output.strip():
            return self._empty_result()

        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError as e:
            self.logger.warning("Failed to parse Checkov JSON: %s", e)
            return self._empty_result()

        findings: list[SecurityFinding] = []
        check_type = data.get("check_type", "unknown")

        # Get results section
        results = data.get("results", {})

        # Process passed checks
        passed_checks = results.get("passed_checks", [])
        for check in passed_checks:
            try:
                finding = self.normalize_finding(check, passed=True, check_type=check_type)
                findings.append(finding)
            except Exception as e:
                self.logger.warning("Failed to normalize passed check: %s", e)

        # Process failed checks
        failed_checks = results.get("failed_checks", [])
        for check in failed_checks:
            try:
                finding = self.normalize_finding(check, passed=False, check_type=check_type)
                findings.append(finding)
            except Exception as e:
                self.logger.warning("Failed to normalize failed check: %s", e)

        # Process skipped checks
        skipped_checks = results.get("skipped_checks", [])
        for check in skipped_checks:
            try:
                finding = self.normalize_finding(check, passed=None, check_type=check_type)
                findings.append(finding)
            except Exception as e:
                self.logger.warning("Failed to normalize skipped check: %s", e)

        # Build summary
        summary = self._build_summary(findings, data.get("summary", {}), check_type)

        return ScanResult(findings=findings, summary=summary)

    def normalize_finding(
        self,
        raw_check: dict,
        passed: Optional[bool] = None,
        check_type: str = "unknown",
    ) -> SecurityFinding:
        """Normalize a Checkov check finding.

        Args:
            raw_check: Check dictionary from Checkov output.
            passed: True for passed, False for failed, None for skipped.
            check_type: Framework type (terraform, cloudformation, etc.)

        Returns:
            Normalized SecurityFinding.
        """
        check_id = raw_check.get("check_id", "unknown")
        check_name = raw_check.get("check_name", "Unknown check")
        resource = raw_check.get("resource", "")
        file_path = raw_check.get("file_path", "")
        line_range = raw_check.get("file_line_range", [])
        guideline = raw_check.get("guideline", "")

        # Determine severity
        if passed is True:
            severity = SeverityLevel.PASS
        elif passed is None:
            # Skipped check
            severity = SeverityLevel.INFO
        else:
            # Failed check - derive severity from check patterns
            severity = self._derive_severity(check_id, check_name)

        # Build description with file location
        description_parts = []
        if file_path:
            description_parts.append(f"File: {file_path}")
        if line_range and len(line_range) >= 2:
            description_parts.append(f"Lines: {line_range[0]}-{line_range[1]}")
        if resource:
            description_parts.append(f"Resource: {resource}")

        # Add evaluation reason if present
        evaluations = raw_check.get("evaluations", {})
        if evaluations and isinstance(evaluations, dict):
            default_eval = evaluations.get("default", {})
            if isinstance(default_eval, dict) and default_eval.get("reason"):
                description_parts.append(f"Reason: {default_eval['reason']}")

        # For skipped checks, include suppress comment
        check_result = raw_check.get("check_result", {})
        if isinstance(check_result, dict):
            suppress_comment = check_result.get("suppress_comment")
            if suppress_comment:
                description_parts.append(f"Skipped: {suppress_comment}")

        description = " | ".join(description_parts) if description_parts else check_name

        # Build remediation
        remediation = None
        if guideline:
            remediation = f"See: {guideline}"

        # Build unique ID
        finding_id = f"checkov-{check_id}-{resource}".replace("/", "-")

        return SecurityFinding(
            id=finding_id,
            source=FindingSource.CHECKOV,
            severity=severity,
            title=check_name,
            description=description,
            resource=resource,
            resource_type=check_type,
            check_id=check_id,
            remediation=remediation,
            raw=raw_check,
            timestamp=datetime.now(),
        )

    def _derive_severity(self, check_id: str, check_name: str) -> SeverityLevel:
        """Derive severity from check ID and name patterns.

        Checkov doesn't provide severity in output, so we derive it based
        on check patterns.

        Args:
            check_id: Check ID (e.g., CKV_AWS_40).
            check_name: Human-readable check name.

        Returns:
            Derived SeverityLevel.
        """
        combined = f"{check_id} {check_name}".lower()

        # Check for critical patterns first
        for pattern in self.CRITICAL_SEVERITY_PATTERNS:
            if pattern in combined:
                return SeverityLevel.CRITICAL

        # Check for high severity patterns
        for pattern in self.HIGH_SEVERITY_PATTERNS:
            if pattern in combined:
                return SeverityLevel.HIGH

        # Default to MEDIUM for failed checks
        return SeverityLevel.MEDIUM

    def _build_summary(
        self,
        findings: list[SecurityFinding],
        checkov_summary: dict,
        check_type: str,
    ) -> ScanSummary:
        """Build scan summary from findings.

        Args:
            findings: List of normalized SecurityFinding objects.
            checkov_summary: Original Checkov summary dict.
            check_type: Framework type scanned.

        Returns:
            ScanSummary with counts and metadata.
        """
        critical_count = 0
        high_count = 0
        medium_count = 0
        low_count = 0
        info_count = 0
        pass_count = 0

        for finding in findings:
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

        # Use Checkov's pass count if available
        if checkov_summary.get("passed"):
            pass_count = checkov_summary["passed"]

        return ScanSummary(
            source=FindingSource.CHECKOV,
            provider=CloudProvider.LOCAL,  # Checkov scans IaC files locally
            total_findings=len(findings),
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            info_count=info_count,
            pass_count=pass_count,
            scan_timestamp=datetime.now(),
            services_scanned=[check_type] if check_type != "unknown" else [],
        )

    def _empty_result(self) -> ScanResult:
        """Return an empty ScanResult for error cases."""
        return ScanResult(
            findings=[],
            summary=ScanSummary(
                source=FindingSource.CHECKOV,
                provider=CloudProvider.LOCAL,
                total_findings=0,
                scan_timestamp=datetime.now(),
            ),
        )
