"""Parser for ScoutSuite security findings."""

import json
from datetime import datetime
from typing import Any

from navconfig.logging import logging

from ..base_parser import BaseParser
from ..models import (
    ScanResult,
    ScanSummary,
    SecurityFinding,
    SeverityLevel,
    ToolSource,
)


class ScoutSuiteParser(BaseParser):
    """Parses ScoutSuite JSON output into unified SecurityFinding models."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def _normalize_severity(self, level: str) -> SeverityLevel:
        """Map ScoutSuite severity levels to unified SeverityLevel."""
        lvl = level.lower()
        if lvl == "danger" or lvl == "critical":
            return SeverityLevel.CRITICAL
        elif lvl == "warning" or lvl == "high":
            return SeverityLevel.HIGH
        elif lvl == "medium":
            return SeverityLevel.MEDIUM
        elif lvl == "info" or lvl == "low":
            return SeverityLevel.LOW
        return SeverityLevel.UNKNOWN

    def parse(self, output: str) -> ScanResult:
        """Parse ScoutSuite JSON output string."""
        if not output or not output.strip():
            self.logger.warning("Empty output provided to ScoutSuite parser")
            return self._empty_result()

        try:
            # We assume execute_with_json_capture cleaned the JS variable declaration
            data = json.loads(output)
            return self.parse_dict(data)
        except json.JSONDecodeError as e:
            self.logger.error("Failed to parse ScoutSuite JSON: %s", e)
            self.logger.debug("Raw output begins: %s", output[:200])
            return self._empty_result()

    def parse_dict(self, data: dict[str, Any]) -> ScanResult:
        """Parse loaded ScoutSuite JSON dictionary."""
        findings = []
        
        # In ScoutSuite, findings exist under nested provider services, usually looking like
        # data["services"]["iam"]["findings"]
        services = data.get("services", {})
        
        for service_name, service_data in services.items():
            service_findings = service_data.get("findings", {})
            
            # The structure of findings in ScoutSuite is a dict of ID -> metadata
            for finding_id, details in service_findings.items():
                
                # Iterate on `items` or `flagged_items` that represent actual violations per rule
                flagged_items = details.get("items", []) + details.get("flagged_items", [])
                
                for item in flagged_items:
                    # Depending on how the item is reported
                    resource_name = str(item)
                    if isinstance(item, str):
                        resource_name = item
                    elif isinstance(item, dict):
                        # Some mappings extract name or id depending on the service context
                        resource_name = item.get("name") or item.get("Id") or item.get("id") or str(item)
                        
                    finding = SecurityFinding(
                        id=f"scout-{finding_id}-{len(findings)}",
                        source=ToolSource.OTHER,
                        severity=self._normalize_severity(details.get("level", "unknown")),
                        title=details.get("description", finding_id),
                        description=details.get("rationale", ""),
                        resource=resource_name,
                        resource_type=f"aws-{service_name}",  # Typically defaults to aws
                        service=service_name,
                        remediation=details.get("remediation", ""),
                        check_id=finding_id,
                        compliance_tags=[],
                        timestamp=datetime.now(),
                        raw_data=details,
                    )
                    findings.append(finding)

        return ScanResult(
            findings=findings,
            summary=ScanSummary(
                total_findings=len(findings),
                source=ToolSource.OTHER,
                generated_at=datetime.now(),
            ),
        )

    def _empty_result(self) -> ScanResult:
        """Return an empty scan result for failed parses."""
        return ScanResult(
            findings=[],
            summary=ScanSummary(
                total_findings=0,
                source=ToolSource.OTHER,
                generated_at=datetime.now(),
            ),
        )
