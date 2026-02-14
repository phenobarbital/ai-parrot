"""AWS GuardDuty Toolkit for AI-Parrot.

Provides inspection of GuardDuty detectors, findings, IP sets, and threat intel sets.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from ...interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit


# ------------------------------------------------------------------
# Input Schemas
# ------------------------------------------------------------------


class ListDetectorsInput(BaseModel):
    """Input for listing GuardDuty detectors."""

    max_results: int = Field(
        50, description="Maximum number of detectors to return"
    )


class ListFindingsInput(BaseModel):
    """Input for listing GuardDuty findings."""

    detector_id: str = Field(
        ..., description="GuardDuty detector ID"
    )
    max_results: int = Field(
        50, description="Maximum number of findings"
    )
    severity: Optional[str] = Field(
        None,
        description="Filter by severity: LOW, MEDIUM, HIGH",
    )


class GetFindingDetailsInput(BaseModel):
    """Input for getting detailed finding information."""

    detector_id: str = Field(
        ..., description="GuardDuty detector ID"
    )
    finding_id: str = Field(
        ..., description="Finding ID to retrieve"
    )


class GetFindingsStatisticsInput(BaseModel):
    """Input for getting finding statistics."""

    detector_id: str = Field(
        ..., description="GuardDuty detector ID"
    )


class ListIPSetsInput(BaseModel):
    """Input for listing GuardDuty IP sets."""

    detector_id: str = Field(
        ..., description="GuardDuty detector ID"
    )
    max_results: int = Field(
        50, description="Maximum number of IP sets"
    )


class ListThreatIntelSetsInput(BaseModel):
    """Input for listing GuardDuty threat intel sets."""

    detector_id: str = Field(
        ..., description="GuardDuty detector ID"
    )
    max_results: int = Field(
        50, description="Maximum number of threat intel sets"
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class GuardDutyToolkit(AbstractToolkit):
    """Toolkit for inspecting AWS GuardDuty detectors and findings.

    Available Operations:
    - aws_guardduty_list_detectors: List GuardDuty detectors
    - aws_guardduty_list_findings: List findings with optional severity filter
    - aws_guardduty_get_finding_details: Get detailed finding info
    - aws_guardduty_get_findings_statistics: Get findings statistics
    - aws_guardduty_list_ip_sets: List trusted IP sets
    - aws_guardduty_list_threat_intel_sets: List threat intelligence sets
    """

    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.aws = AWSInterface(
            aws_id=aws_id,
            region_name=region_name,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # List Detectors
    # ------------------------------------------------------------------

    @tool_schema(ListDetectorsInput)
    async def aws_guardduty_list_detectors(
        self, max_results: int = 50
    ) -> Dict[str, Any]:
        """List all GuardDuty detectors in the account."""
        try:
            async with self.aws.client("guardduty") as gd:
                response = await gd.list_detectors(
                    MaxResults=max_results
                )
                detector_ids = response.get("DetectorIds", [])

                detectors = []
                for did in detector_ids:
                    try:
                        det = await gd.get_detector(DetectorId=did)
                        detectors.append(
                            {
                                "detector_id": did,
                                "status": det.get("Status"),
                                "service_role": det.get("ServiceRole"),
                                "created_at": det.get("CreatedAt"),
                                "updated_at": det.get("UpdatedAt"),
                                "finding_publishing_frequency": det.get(
                                    "FindingPublishingFrequency"
                                ),
                            }
                        )
                    except ClientError:
                        detectors.append(
                            {"detector_id": did, "status": "unknown"}
                        )

                return {
                    "detectors": detectors,
                    "count": len(detectors),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS GuardDuty error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Findings
    # ------------------------------------------------------------------

    @tool_schema(ListFindingsInput)
    async def aws_guardduty_list_findings(
        self,
        detector_id: str,
        max_results: int = 50,
        severity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List GuardDuty findings for a detector."""
        try:
            async with self.aws.client("guardduty") as gd:
                params: Dict[str, Any] = {
                    "DetectorId": detector_id,
                    "MaxResults": max_results,
                    "SortCriteria": {
                        "AttributeName": "severity",
                        "OrderBy": "DESC",
                    },
                }

                if severity:
                    severity_map = {
                        "LOW": {"Gte": 1, "Lt": 4},
                        "MEDIUM": {"Gte": 4, "Lt": 7},
                        "HIGH": {"Gte": 7, "Lt": 9},
                    }
                    sev_range = severity_map.get(severity.upper())
                    if sev_range:
                        params["FindingCriteria"] = {
                            "Criterion": {
                                "severity": sev_range,
                            }
                        }

                response = await gd.list_findings(**params)
                finding_ids = response.get("FindingIds", [])

                findings = []
                if finding_ids:
                    details_resp = await gd.get_findings(
                        DetectorId=detector_id,
                        FindingIds=finding_ids,
                    )
                    for f in details_resp.get("Findings", []):
                        findings.append(
                            {
                                "id": f.get("Id"),
                                "type": f.get("Type"),
                                "severity": f.get("Severity"),
                                "title": f.get("Title"),
                                "description": f.get("Description"),
                                "created_at": f.get("CreatedAt"),
                                "updated_at": f.get("UpdatedAt"),
                                "resource_type": f.get(
                                    "Resource", {}
                                ).get("ResourceType"),
                            }
                        )

                return {
                    "detector_id": detector_id,
                    "findings": findings,
                    "count": len(findings),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS GuardDuty error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Finding Details
    # ------------------------------------------------------------------

    @tool_schema(GetFindingDetailsInput)
    async def aws_guardduty_get_finding_details(
        self, detector_id: str, finding_id: str
    ) -> Dict[str, Any]:
        """Get detailed information about a specific GuardDuty finding."""
        try:
            async with self.aws.client("guardduty") as gd:
                response = await gd.get_findings(
                    DetectorId=detector_id,
                    FindingIds=[finding_id],
                )
                findings = response.get("Findings", [])
                if not findings:
                    raise ValueError(
                        f"Finding {finding_id} not found"
                    )

                f = findings[0]
                resource = f.get("Resource", {})
                service = f.get("Service", {})

                return {
                    "id": f.get("Id"),
                    "type": f.get("Type"),
                    "severity": f.get("Severity"),
                    "title": f.get("Title"),
                    "description": f.get("Description"),
                    "created_at": f.get("CreatedAt"),
                    "updated_at": f.get("UpdatedAt"),
                    "region": f.get("Region"),
                    "account_id": f.get("AccountId"),
                    "resource": {
                        "type": resource.get("ResourceType"),
                        "details": resource,
                    },
                    "service": {
                        "action": service.get("Action"),
                        "evidence": service.get("Evidence"),
                        "event_first_seen": service.get(
                            "EventFirstSeen"
                        ),
                        "event_last_seen": service.get(
                            "EventLastSeen"
                        ),
                        "count": service.get("Count"),
                    },
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS GuardDuty error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Findings Statistics
    # ------------------------------------------------------------------

    @tool_schema(GetFindingsStatisticsInput)
    async def aws_guardduty_get_findings_statistics(
        self, detector_id: str
    ) -> Dict[str, Any]:
        """Get statistics for GuardDuty findings."""
        try:
            async with self.aws.client("guardduty") as gd:
                response = await gd.get_findings_statistics(
                    DetectorId=detector_id,
                    FindingStatisticTypes=["COUNT_BY_SEVERITY"],
                )
                stats = response.get("FindingStatistics", {})
                count_by_severity = stats.get(
                    "CountBySeverity", {}
                )

                return {
                    "detector_id": detector_id,
                    "count_by_severity": count_by_severity,
                    "total_findings": sum(
                        count_by_severity.values()
                    ),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS GuardDuty error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List IP Sets
    # ------------------------------------------------------------------

    @tool_schema(ListIPSetsInput)
    async def aws_guardduty_list_ip_sets(
        self, detector_id: str, max_results: int = 50
    ) -> Dict[str, Any]:
        """List trusted IP sets for a GuardDuty detector."""
        try:
            async with self.aws.client("guardduty") as gd:
                response = await gd.list_ip_sets(
                    DetectorId=detector_id,
                    MaxResults=max_results,
                )
                ip_set_ids = response.get("IpSetIds", [])

                ip_sets = []
                for ipset_id in ip_set_ids:
                    try:
                        detail = await gd.get_ip_set(
                            DetectorId=detector_id,
                            IpSetId=ipset_id,
                        )
                        ip_sets.append(
                            {
                                "ip_set_id": ipset_id,
                                "name": detail.get("Name"),
                                "format": detail.get("Format"),
                                "location": detail.get("Location"),
                                "status": detail.get("Status"),
                            }
                        )
                    except ClientError:
                        ip_sets.append(
                            {
                                "ip_set_id": ipset_id,
                                "status": "unknown",
                            }
                        )

                return {
                    "detector_id": detector_id,
                    "ip_sets": ip_sets,
                    "count": len(ip_sets),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS GuardDuty error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Threat Intel Sets
    # ------------------------------------------------------------------

    @tool_schema(ListThreatIntelSetsInput)
    async def aws_guardduty_list_threat_intel_sets(
        self, detector_id: str, max_results: int = 50
    ) -> Dict[str, Any]:
        """List threat intelligence sets for a GuardDuty detector."""
        try:
            async with self.aws.client("guardduty") as gd:
                response = await gd.list_threat_intel_sets(
                    DetectorId=detector_id,
                    MaxResults=max_results,
                )
                ti_set_ids = response.get(
                    "ThreatIntelSetIds", []
                )

                ti_sets = []
                for ti_id in ti_set_ids:
                    try:
                        detail = await gd.get_threat_intel_set(
                            DetectorId=detector_id,
                            ThreatIntelSetId=ti_id,
                        )
                        ti_sets.append(
                            {
                                "threat_intel_set_id": ti_id,
                                "name": detail.get("Name"),
                                "format": detail.get("Format"),
                                "location": detail.get("Location"),
                                "status": detail.get("Status"),
                            }
                        )
                    except ClientError:
                        ti_sets.append(
                            {
                                "threat_intel_set_id": ti_id,
                                "status": "unknown",
                            }
                        )

                return {
                    "detector_id": detector_id,
                    "threat_intel_sets": ti_sets,
                    "count": len(ti_sets),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS GuardDuty error ({error_code}): {e}"
            ) from e
