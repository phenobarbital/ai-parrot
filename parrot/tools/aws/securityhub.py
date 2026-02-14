"""AWS SecurityHub Toolkit for AI-Parrot.

Provides inspection of SecurityHub findings, failed standards, and security scores.
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


class GetFindingsInput(BaseModel):
    """Input for getting SecurityHub findings."""

    limit: int = Field(
        20, description="Maximum number of findings to return"
    )
    severity: str = Field(
        "ALL",
        description=(
            "Severity filter: CRITICAL, HIGH, MEDIUM, LOW, "
            "INFORMATIONAL, or ALL"
        ),
    )
    search_term: Optional[str] = Field(
        None,
        description="Search term to filter findings by title or description",
    )


class ListFailedStandardsInput(BaseModel):
    """Input for listing failed security standards."""

    limit: int = Field(
        20, description="Maximum number of failed standards"
    )


class GetSecurityScoreInput(BaseModel):
    """Input for getting the account security score."""


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class SecurityHubToolkit(AbstractToolkit):
    """Toolkit for inspecting AWS SecurityHub findings and compliance.

    Available Operations:
    - aws_securityhub_get_findings: Get findings with optional filters
    - aws_securityhub_list_failed_standards: List failed security standards
    - aws_securityhub_get_security_score: Get account security score
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
    # Get Findings
    # ------------------------------------------------------------------

    @tool_schema(GetFindingsInput)
    async def aws_securityhub_get_findings(
        self,
        limit: int = 20,
        severity: str = "ALL",
        search_term: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get findings from AWS SecurityHub."""
        try:
            filters: Dict[str, Any] = {
                "RecordState": [
                    {"Value": "ACTIVE", "Comparison": "EQUALS"}
                ],
                "WorkflowStatus": [
                    {"Value": "NEW", "Comparison": "EQUALS"},
                    {
                        "Value": "NOTIFIED",
                        "Comparison": "EQUALS",
                    },
                ],
            }

            if severity and severity.upper() != "ALL":
                filters["SeverityLabel"] = [
                    {
                        "Value": severity.upper(),
                        "Comparison": "EQUALS",
                    }
                ]

            if search_term:
                filters["Title"] = [
                    {
                        "Value": search_term,
                        "Comparison": "CONTAINS",
                    }
                ]

            async with self.aws.client("securityhub") as sh:
                response = await sh.get_findings(
                    Filters=filters,
                    MaxResults=min(limit, 100),
                    SortCriteria=[
                        {
                            "Field": "SeverityLabel",
                            "SortOrder": "desc",
                        }
                    ],
                )
                findings = [
                    {
                        "id": f.get("Id"),
                        "title": f.get("Title"),
                        "description": f.get("Description"),
                        "severity": f.get("Severity", {}).get(
                            "Label"
                        ),
                        "severity_normalized": f.get(
                            "Severity", {}
                        ).get("Normalized"),
                        "status": f.get("Workflow", {}).get(
                            "Status"
                        ),
                        "resource_type": (
                            f.get("Resources", [{}])[0].get(
                                "Type"
                            )
                            if f.get("Resources")
                            else None
                        ),
                        "resource_id": (
                            f.get("Resources", [{}])[0].get(
                                "Id"
                            )
                            if f.get("Resources")
                            else None
                        ),
                        "generator_id": f.get("GeneratorId"),
                        "product_name": f.get(
                            "ProductName"
                        ),
                        "created_at": f.get("CreatedAt"),
                        "updated_at": f.get("UpdatedAt"),
                        "compliance_status": f.get(
                            "Compliance", {}
                        ).get("Status"),
                    }
                    for f in response.get("Findings", [])
                ]

                return {
                    "findings": findings,
                    "count": len(findings),
                    "severity_filter": severity,
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS SecurityHub error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Failed Standards
    # ------------------------------------------------------------------

    @tool_schema(ListFailedStandardsInput)
    async def aws_securityhub_list_failed_standards(
        self, limit: int = 20
    ) -> Dict[str, Any]:
        """List failed security standards from SecurityHub."""
        try:
            async with self.aws.client("securityhub") as sh:
                # Get enabled standards
                standards_resp = (
                    await sh.get_enabled_standards()
                )
                subscriptions = standards_resp.get(
                    "StandardsSubscriptions", []
                )

                all_failed: List[Dict[str, Any]] = []

                for sub in subscriptions:
                    sub_arn = sub.get(
                        "StandardsSubscriptionArn"
                    )
                    standard_name = sub.get("StandardsArn", "")

                    try:
                        controls_resp = await sh.describe_standards_controls(
                            StandardsSubscriptionArn=sub_arn
                        )
                        for ctrl in controls_resp.get(
                            "Controls", []
                        ):
                            if ctrl.get(
                                "ControlStatus"
                            ) == "FAILED":
                                all_failed.append(
                                    {
                                        "control_id": ctrl.get(
                                            "ControlId"
                                        ),
                                        "title": ctrl.get(
                                            "Title"
                                        ),
                                        "description": ctrl.get(
                                            "Description"
                                        ),
                                        "severity": ctrl.get(
                                            "SeverityRating"
                                        ),
                                        "standard": standard_name,
                                        "remediation_url": ctrl.get(
                                            "RemediationUrl"
                                        ),
                                    }
                                )
                    except ClientError:
                        continue

                # Sort by severity
                severity_order = {
                    "CRITICAL": 0,
                    "HIGH": 1,
                    "MEDIUM": 2,
                    "LOW": 3,
                }
                all_failed.sort(
                    key=lambda x: severity_order.get(
                        x.get("severity", "LOW"), 4
                    )
                )

                return {
                    "failed_standards": all_failed[:limit],
                    "count": len(all_failed[:limit]),
                    "total_failed": len(all_failed),
                    "standards_checked": len(subscriptions),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS SecurityHub error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Security Score
    # ------------------------------------------------------------------

    @tool_schema(GetSecurityScoreInput)
    async def aws_securityhub_get_security_score(
        self,
    ) -> Dict[str, Any]:
        """Get the overall security score for the AWS account."""
        try:
            async with self.aws.client("securityhub") as sh:
                # Count findings by severity
                findings_resp = await sh.get_findings(
                    Filters={
                        "RecordState": [
                            {
                                "Value": "ACTIVE",
                                "Comparison": "EQUALS",
                            }
                        ],
                        "WorkflowStatus": [
                            {
                                "Value": "NEW",
                                "Comparison": "EQUALS",
                            },
                            {
                                "Value": "NOTIFIED",
                                "Comparison": "EQUALS",
                            },
                        ],
                    },
                    MaxResults=100,
                )

                severity_counts: Dict[str, int] = {
                    "CRITICAL": 0,
                    "HIGH": 0,
                    "MEDIUM": 0,
                    "LOW": 0,
                    "INFORMATIONAL": 0,
                }
                for f in findings_resp.get("Findings", []):
                    label = f.get("Severity", {}).get(
                        "Label", "INFORMATIONAL"
                    )
                    severity_counts[label] = (
                        severity_counts.get(label, 0) + 1
                    )

                total = sum(severity_counts.values())
                # Weighted score: critical=10, high=5, medium=2, low=1
                penalty = (
                    severity_counts["CRITICAL"] * 10
                    + severity_counts["HIGH"] * 5
                    + severity_counts["MEDIUM"] * 2
                    + severity_counts["LOW"] * 1
                )
                score = max(0, 100 - penalty)

                # Get enabled standards count
                try:
                    standards = (
                        await sh.get_enabled_standards()
                    )
                    standards_count = len(
                        standards.get(
                            "StandardsSubscriptions", []
                        )
                    )
                except ClientError:
                    standards_count = 0

                return {
                    "security_score": score,
                    "severity_counts": severity_counts,
                    "total_active_findings": total,
                    "enabled_standards": standards_count,
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS SecurityHub error ({error_code}): {e}"
            ) from e
