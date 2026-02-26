"""Compliance Mapper for security findings.

Maps normalized SecurityFinding objects to compliance framework controls
(SOC2, HIPAA, PCI-DSS, etc.), enabling cross-tool compliance reporting.
"""

import logging
from pathlib import Path
from typing import Optional

import yaml

from ..models import ComplianceFramework, FindingSource, SecurityFinding, SeverityLevel


class ComplianceMapper:
    """Maps security findings to compliance framework controls.

    Maintains a mapping database from:
    - Prowler check IDs → compliance controls
    - Trivy vulnerability types → compliance controls
    - Checkov policy IDs → compliance controls

    The mapper loads YAML mapping files that define the relationship between
    scanner-specific check IDs and framework controls.

    Example:
        mapper = ComplianceMapper()
        controls = mapper.map_finding_to_controls(finding, ComplianceFramework.SOC2)
        coverage = mapper.get_framework_coverage(findings, ComplianceFramework.SOC2)
    """

    # Map FindingSource to the key used in YAML mappings
    SOURCE_TO_KEY = {
        FindingSource.PROWLER: "prowler",
        FindingSource.TRIVY: "trivy",
        FindingSource.CHECKOV: "checkov",
    }

    def __init__(self, mappings_dir: Optional[str] = None):
        """Initialize the ComplianceMapper.

        Args:
            mappings_dir: Path to directory containing YAML mapping files.
                Defaults to the 'mappings' subdirectory next to this module.
        """
        self.logger = logging.getLogger(__name__)

        if mappings_dir:
            self.mappings_dir = Path(mappings_dir)
        else:
            self.mappings_dir = Path(__file__).parent / "mappings"

        # Lazy-loaded mapping data
        self._mappings: dict[str, dict[str, dict[str, list[str]]]] = {}
        self._controls: dict[str, dict[str, dict]] = {}
        self._loaded_frameworks: set[str] = set()

    def _load_framework(self, framework: ComplianceFramework) -> None:
        """Load mappings for a specific framework.

        Args:
            framework: The compliance framework to load mappings for.
        """
        framework_key = framework.value

        if framework_key in self._loaded_frameworks:
            return

        mapping_file = self.mappings_dir / f"{framework_key}_controls.yaml"

        if not mapping_file.exists():
            self.logger.debug("No mapping file found for %s at %s", framework_key, mapping_file)
            self._mappings[framework_key] = {}
            self._controls[framework_key] = {}
            self._loaded_frameworks.add(framework_key)
            return

        try:
            with open(mapping_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            self._mappings[framework_key] = data.get("check_mappings", {})
            self._controls[framework_key] = data.get("controls", {})
            self._loaded_frameworks.add(framework_key)

            self.logger.debug(
                "Loaded %d controls and mappings for %s",
                len(self._controls[framework_key]),
                framework_key,
            )
        except yaml.YAMLError as e:
            self.logger.error("Failed to parse YAML mapping file %s: %s", mapping_file, e)
            self._mappings[framework_key] = {}
            self._controls[framework_key] = {}
            self._loaded_frameworks.add(framework_key)

    def _get_check_key(self, finding: SecurityFinding) -> Optional[str]:
        """Get the check key to use for mapping lookup.

        For Prowler: uses check_id
        For Checkov: uses check_id
        For Trivy: uses resource_type + severity pattern

        Args:
            finding: The security finding.

        Returns:
            The check key to use for mapping lookup, or None if not determinable.
        """
        if finding.source == FindingSource.PROWLER:
            return finding.check_id

        if finding.source == FindingSource.CHECKOV:
            return finding.check_id

        if finding.source == FindingSource.TRIVY:
            # Trivy findings are mapped by type + severity
            resource_type = finding.resource_type or "unknown"

            # Determine finding type category
            if resource_type == "vulnerability" or "CVE" in (finding.id or ""):
                # Map severity to key
                severity_map = {
                    SeverityLevel.CRITICAL: "vulnerability_critical",
                    SeverityLevel.HIGH: "vulnerability_high",
                    SeverityLevel.MEDIUM: "vulnerability_medium",
                    SeverityLevel.LOW: "vulnerability_low",
                }
                return severity_map.get(finding.severity)

            if resource_type == "secret" or "secret" in resource_type.lower():
                return "secret_exposed"

            if "misconfig" in resource_type.lower():
                if finding.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH):
                    return "misconfig_high"
                return "misconfig_medium"

        return None

    def map_finding_to_controls(
        self,
        finding: SecurityFinding,
        framework: ComplianceFramework,
    ) -> list[str]:
        """Map a security finding to relevant compliance controls.

        Args:
            finding: The security finding to map.
            framework: The compliance framework to map to.

        Returns:
            List of control IDs that the finding maps to.
            Returns empty list if no mapping exists.

        Example:
            controls = mapper.map_finding_to_controls(finding, ComplianceFramework.SOC2)
            # Returns ["CC6.1", "CC6.6"] for an S3 public access finding
        """
        # Ensure framework mappings are loaded
        self._load_framework(framework)

        framework_key = framework.value
        source_key = self.SOURCE_TO_KEY.get(finding.source)

        if not source_key:
            return []

        # Get mappings for this source
        source_mappings = self._mappings.get(framework_key, {}).get(source_key, {})

        if not source_mappings:
            return []

        # Get the check key for this finding
        check_key = self._get_check_key(finding)

        if not check_key:
            return []

        # Look up controls
        controls = source_mappings.get(check_key, [])

        return list(controls) if controls else []

    def get_framework_coverage(
        self,
        findings: list[SecurityFinding],
        framework: ComplianceFramework,
    ) -> dict:
        """Calculate compliance coverage for a framework based on findings.

        Analyzes the findings to determine:
        - Which controls have been checked (have associated findings)
        - Which controls passed vs failed
        - Overall coverage percentage

        Args:
            findings: List of security findings to analyze.
            framework: The compliance framework to calculate coverage for.

        Returns:
            Dictionary with coverage metrics:
                - total_controls: Total number of controls in the framework
                - checked_controls: Number of controls with associated findings
                - passed_controls: Number of controls where all findings passed
                - failed_controls: Number of controls with at least one failed finding
                - unchecked_controls: Number of controls with no associated findings
                - coverage_pct: Percentage of controls that were checked
                - pass_pct: Percentage of checked controls that passed

        Example:
            coverage = mapper.get_framework_coverage(findings, ComplianceFramework.SOC2)
            print(f"Coverage: {coverage['coverage_pct']}%")
        """
        # Ensure framework mappings are loaded
        self._load_framework(framework)

        framework_key = framework.value
        controls = self._controls.get(framework_key, {})
        total_controls = len(controls)

        if total_controls == 0:
            return {
                "total_controls": 0,
                "checked_controls": 0,
                "passed_controls": 0,
                "failed_controls": 0,
                "unchecked_controls": 0,
                "coverage_pct": 0.0,
                "pass_pct": 0.0,
            }

        # Track control status
        control_status: dict[str, set[str]] = {
            control_id: set() for control_id in controls
        }

        # Map findings to controls
        for finding in findings:
            mapped_controls = self.map_finding_to_controls(finding, framework)

            for control_id in mapped_controls:
                if control_id in control_status:
                    # Record the finding status
                    if finding.severity == SeverityLevel.PASS:
                        control_status[control_id].add("pass")
                    else:
                        control_status[control_id].add("fail")

        # Count controls by status
        checked_controls = 0
        passed_controls = 0
        failed_controls = 0

        for control_id, statuses in control_status.items():
            if statuses:
                checked_controls += 1
                if "fail" in statuses:
                    failed_controls += 1
                else:
                    passed_controls += 1

        unchecked_controls = total_controls - checked_controls
        coverage_pct = (checked_controls / total_controls) * 100 if total_controls > 0 else 0.0
        pass_pct = (passed_controls / checked_controls) * 100 if checked_controls > 0 else 0.0

        return {
            "total_controls": total_controls,
            "checked_controls": checked_controls,
            "passed_controls": passed_controls,
            "failed_controls": failed_controls,
            "unchecked_controls": unchecked_controls,
            "coverage_pct": round(coverage_pct, 2),
            "pass_pct": round(pass_pct, 2),
        }

    def get_control_details(
        self,
        control_id: str,
        framework: ComplianceFramework,
    ) -> Optional[dict]:
        """Get details for a specific compliance control.

        Args:
            control_id: The ID of the control (e.g., "CC6.1" for SOC2).
            framework: The compliance framework the control belongs to.

        Returns:
            Dictionary with control details including name, description, and category.
            Returns None if the control is not found.

        Example:
            details = mapper.get_control_details("CC6.1", ComplianceFramework.SOC2)
            # Returns {"name": "Logical and Physical Access Controls", ...}
        """
        # Ensure framework mappings are loaded
        self._load_framework(framework)

        framework_key = framework.value
        controls = self._controls.get(framework_key, {})

        control = controls.get(control_id)

        if control:
            return dict(control)

        return None

    def get_all_controls(self, framework: ComplianceFramework) -> dict[str, dict]:
        """Get all controls for a compliance framework.

        Args:
            framework: The compliance framework.

        Returns:
            Dictionary of control_id -> control details.
        """
        self._load_framework(framework)
        framework_key = framework.value
        return dict(self._controls.get(framework_key, {}))

    def get_findings_by_control(
        self,
        findings: list[SecurityFinding],
        framework: ComplianceFramework,
    ) -> dict[str, list[SecurityFinding]]:
        """Group findings by the controls they map to.

        Args:
            findings: List of security findings.
            framework: The compliance framework to use for mapping.

        Returns:
            Dictionary mapping control IDs to lists of findings.

        Example:
            by_control = mapper.get_findings_by_control(findings, ComplianceFramework.SOC2)
            for control_id, control_findings in by_control.items():
                print(f"{control_id}: {len(control_findings)} findings")
        """
        result: dict[str, list[SecurityFinding]] = {}

        for finding in findings:
            controls = self.map_finding_to_controls(finding, framework)
            for control_id in controls:
                if control_id not in result:
                    result[control_id] = []
                result[control_id].append(finding)

        return result

    def get_unmapped_findings(
        self,
        findings: list[SecurityFinding],
        framework: ComplianceFramework,
    ) -> list[SecurityFinding]:
        """Get findings that don't map to any control in the framework.

        Args:
            findings: List of security findings.
            framework: The compliance framework to check against.

        Returns:
            List of findings that have no control mappings.
        """
        unmapped = []
        for finding in findings:
            controls = self.map_finding_to_controls(finding, framework)
            if not controls:
                unmapped.append(finding)
        return unmapped
