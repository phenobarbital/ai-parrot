"""AWS Route53 Toolkit for AI-Parrot.

Provides inspection and management of Route53 hosted zones, DNS records,
health checks and traffic policies.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field
from ...interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit


# ------------------------------------------------------------------
# Input Schemas
# ------------------------------------------------------------------
class ListHostedZonesInput(BaseModel):
    """Input for listing Route53 hosted zones."""

    limit: int = Field(
        100, description="Maximum number of hosted zones to return"
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token from a previous response"
    )


class GetHostedZoneDetailsInput(BaseModel):
    """Input for getting hosted zone details."""

    zone_id: str = Field(
        ...,
        description=(
            "Route53 hosted zone ID "
            "(e.g. '/hostedzone/Z1234567890' or 'Z1234567890')"
        ),
    )


class ListResourceRecordSetsInput(BaseModel):
    """Input for listing DNS records in a hosted zone."""

    zone_id: str = Field(
        ..., description="Route53 hosted zone ID"
    )
    record_type: Optional[str] = Field(
        None,
        description=(
            "DNS record type filter "
            "(A, AAAA, CNAME, MX, NS, SOA, TXT, etc.)"
        ),
    )
    record_name: Optional[str] = Field(
        None,
        description="DNS record name filter (e.g. 'api.example.com')",
    )
    limit: int = Field(
        100, description="Maximum number of records to return"
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token from a previous response"
    )


class ListHealthChecksInput(BaseModel):
    """Input for listing Route53 health checks."""

    limit: int = Field(
        100, description="Maximum number of health checks to return"
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token from a previous response"
    )


class ListTrafficPoliciesInput(BaseModel):
    """Input for listing Route53 traffic policies."""

    limit: int = Field(
        100, description="Maximum number of policies to return"
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token from a previous response"
    )


class CreateHostedZoneInput(BaseModel):
    """Input for creating a new hosted zone."""

    domain_name: str = Field(
        ...,
        description=(
            "Domain name for the hosted zone "
            "(e.g. 'example.com')"
        ),
    )
    comment: Optional[str] = Field(
        None,
        description="Comment to associate with the hosted zone",
    )
    is_private: bool = Field(
        False,
        description="Whether to create a private hosted zone",
    )
    vpc_id: Optional[str] = Field(
        None,
        description=(
            "VPC ID to associate with a private hosted zone "
            "(required when is_private=True)"
        ),
    )
    vpc_region: Optional[str] = Field(
        None,
        description=(
            "VPC region (required when is_private=True "
            "and vpc_id is specified)"
        ),
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class Route53Toolkit(AbstractToolkit):
    """Toolkit for managing AWS Route53 hosted zones, DNS records and health checks.

    Each public method is exposed as a separate tool with the `aws_route53_` prefix.

    Available Operations:
    - aws_route53_list_hosted_zones: List hosted zones with pagination
    - aws_route53_get_hosted_zone_details: Get hosted zone details
    - aws_route53_list_resource_record_sets: List DNS records for a zone
    - aws_route53_list_health_checks: List health checks
    - aws_route53_list_traffic_policies: List traffic policies
    - aws_route53_create_hosted_zone: Create a new hosted zone

    Example Usage:
        toolkit = Route53Toolkit()
        tools = toolkit.get_tools()

        result = await toolkit.aws_route53_list_hosted_zones(limit=50)
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
    # List Hosted Zones
    # ------------------------------------------------------------------

    @tool_schema(ListHostedZonesInput)
    async def aws_route53_list_hosted_zones(
        self,
        limit: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List Route53 hosted zones with pagination."""
        try:
            async with self.aws.client("route53") as r53:
                params: Dict[str, Any] = {"MaxItems": str(limit)}
                if next_token:
                    params["Marker"] = next_token

                response = await r53.list_hosted_zones(**params)

                zones = response.get("HostedZones", [])
                is_truncated = response.get("IsTruncated", False)
                next_marker = (
                    response.get("NextMarker") if is_truncated else None
                )

                return {
                    "zones": zones,
                    "count": len(zones),
                    "is_truncated": is_truncated,
                    "next_token": next_marker,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Route53 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Hosted Zone Details
    # ------------------------------------------------------------------

    @tool_schema(GetHostedZoneDetailsInput)
    async def aws_route53_get_hosted_zone_details(
        self, zone_id: str
    ) -> Dict[str, Any]:
        """Get details for a specific hosted zone."""
        try:
            async with self.aws.client("route53") as r53:
                response = await r53.get_hosted_zone(Id=zone_id)

                zone_info = response.get("HostedZone", {})
                delegation_set = response.get("DelegationSet", {})
                vpcs = response.get("VPCs", [])

                return {
                    "hosted_zone": zone_info,
                    "delegation_set": delegation_set,
                    "vpcs": vpcs,
                    "record_count": zone_info.get(
                        "ResourceRecordSetCount", 0
                    ),
                    "is_private": zone_info.get("Config", {}).get(
                        "PrivateZone", False
                    ),
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Route53 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Resource Record Sets
    # ------------------------------------------------------------------

    @tool_schema(ListResourceRecordSetsInput)
    async def aws_route53_list_resource_record_sets(
        self,
        zone_id: str,
        record_type: Optional[str] = None,
        record_name: Optional[str] = None,
        limit: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List DNS records in a hosted zone with optional filtering."""
        try:
            async with self.aws.client("route53") as r53:
                params: Dict[str, Any] = {
                    "HostedZoneId": zone_id,
                    "MaxItems": str(limit),
                }

                if next_token:
                    parts = next_token.split("|")
                    if len(parts) == 2:
                        params["StartRecordName"] = parts[0]
                        params["StartRecordType"] = parts[1]

                response = await r53.list_resource_record_sets(**params)

                records: List[Dict[str, Any]] = response.get(
                    "ResourceRecordSets", []
                )

                if record_type:
                    records = [
                        r for r in records if r.get("Type") == record_type
                    ]
                if record_name:
                    name = record_name.rstrip(".") + "."
                    records = [
                        r for r in records if r.get("Name") == name
                    ]

                is_truncated = response.get("IsTruncated", False)
                next_marker = None
                if is_truncated:
                    next_rec_name = response.get("NextRecordName")
                    next_rec_type = response.get("NextRecordType")
                    if next_rec_name and next_rec_type:
                        next_marker = f"{next_rec_name}|{next_rec_type}"

                return {
                    "records": records,
                    "count": len(records),
                    "is_truncated": is_truncated,
                    "next_token": next_marker,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Route53 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Health Checks
    # ------------------------------------------------------------------

    @tool_schema(ListHealthChecksInput)
    async def aws_route53_list_health_checks(
        self,
        limit: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List Route53 health checks with pagination."""
        try:
            async with self.aws.client("route53") as r53:
                params: Dict[str, Any] = {"MaxItems": str(limit)}
                if next_token:
                    params["Marker"] = next_token

                response = await r53.list_health_checks(**params)

                checks = response.get("HealthChecks", [])
                is_truncated = response.get("IsTruncated", False)
                next_marker = (
                    response.get("Marker") if is_truncated else None
                )

                return {
                    "health_checks": checks,
                    "count": len(checks),
                    "is_truncated": is_truncated,
                    "next_token": next_marker,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Route53 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Traffic Policies
    # ------------------------------------------------------------------

    @tool_schema(ListTrafficPoliciesInput)
    async def aws_route53_list_traffic_policies(
        self,
        limit: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List Route53 traffic policies with pagination."""
        try:
            async with self.aws.client("route53") as r53:
                params: Dict[str, Any] = {"MaxItems": str(limit)}
                if next_token:
                    params["TrafficPolicyIdMarker"] = next_token

                response = await r53.list_traffic_policies(**params)

                policies = response.get("TrafficPolicySummaries", [])
                is_truncated = response.get("IsTruncated", False)
                next_marker = (
                    response.get("TrafficPolicyIdMarker")
                    if is_truncated
                    else None
                )

                return {
                    "policies": policies,
                    "count": len(policies),
                    "is_truncated": is_truncated,
                    "next_token": next_marker,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Route53 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Create Hosted Zone
    # ------------------------------------------------------------------

    @tool_schema(CreateHostedZoneInput)
    async def aws_route53_create_hosted_zone(
        self,
        domain_name: str,
        comment: Optional[str] = None,
        is_private: bool = False,
        vpc_id: Optional[str] = None,
        vpc_region: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new Route53 hosted zone.

        Requires appropriate IAM permissions (route53:CreateHostedZone).
        For private zones, vpc_id and vpc_region are required.
        """
        try:
            async with self.aws.client("route53") as r53:
                params: Dict[str, Any] = {
                    "Name": domain_name,
                    "CallerReference": str(uuid.uuid4()),
                }

                config: Dict[str, Any] = {"PrivateZone": is_private}
                if comment:
                    config["Comment"] = comment
                params["HostedZoneConfig"] = config

                if is_private:
                    if not vpc_id:
                        raise ValueError(
                            "vpc_id is required for private hosted zones"
                        )
                    vpc: Dict[str, str] = {"VPCId": vpc_id}
                    if vpc_region:
                        vpc["VPCRegion"] = vpc_region
                    params["VPC"] = vpc

                response = await r53.create_hosted_zone(**params)

                zone_info = response.get("HostedZone", {})
                delegation_set = response.get("DelegationSet", {})
                change_info = response.get("ChangeInfo", {})

                return {
                    "hosted_zone": zone_info,
                    "delegation_set": delegation_set,
                    "change_info": change_info,
                    "zone_id": zone_info.get("Id", ""),
                    "name_servers": delegation_set.get(
                        "NameServers", []
                    ),
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Route53 error ({error_code}): {e}"
            ) from e
