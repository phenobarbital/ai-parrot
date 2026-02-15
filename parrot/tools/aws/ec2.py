"""AWS EC2 Toolkit for AI-Parrot.

Provides inspection of EC2 instances, security groups, VPCs, subnets,
and route tables for operations and security analysis.
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


class ListInstancesInput(BaseModel):
    """Input for listing EC2 instances."""

    state: str = Field(
        "running",
        description="Filter by state: running, stopped, terminated, etc.",
    )
    limit: int = Field(
        100, description="Maximum number of instances"
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token"
    )


class DescribeInstancesInput(BaseModel):
    """Input for describing specific EC2 instances."""

    instance_ids: List[str] = Field(
        ..., description="EC2 instance IDs to describe"
    )


class ListSecurityGroupsInput(BaseModel):
    """Input for listing EC2 security groups."""

    limit: int = Field(
        100, description="Maximum number of security groups"
    )
    vpc_id: Optional[str] = Field(
        None, description="Filter by VPC ID"
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token"
    )


class FindPublicSecurityGroupsInput(BaseModel):
    """Input for finding security groups with public access."""

    port: Optional[int] = Field(
        None,
        description="Specific port to check for public access (e.g. 22, 3389)",
    )


class ListVPCsInput(BaseModel):
    """Input for listing VPCs."""

    limit: int = Field(
        50, description="Maximum number of VPCs"
    )


class ListSubnetsInput(BaseModel):
    """Input for listing subnets."""

    vpc_id: Optional[str] = Field(
        None, description="Filter by VPC ID"
    )
    limit: int = Field(
        100, description="Maximum number of subnets"
    )


class ListRouteTablesInput(BaseModel):
    """Input for listing route tables."""

    vpc_id: Optional[str] = Field(
        None, description="Filter by VPC ID"
    )
    limit: int = Field(
        100, description="Maximum number of route tables"
    )


class FindResourceByIPInput(BaseModel):
    """Input for finding AWS resources by IP address."""

    ip_address: str = Field(
        ...,
        description="IP address to search for (public or private)",
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class EC2Toolkit(AbstractToolkit):
    """Toolkit for inspecting AWS EC2 instances, security groups, and networking.

    Available Operations:
    - aws_ec2_list_instances: List instances with filters
    - aws_ec2_describe_instances: Describe specific instances
    - aws_ec2_list_security_groups: List security groups
    - aws_ec2_find_public_security_groups: Find SGs with 0.0.0.0/0 rules
    - aws_ec2_list_vpcs: List VPCs
    - aws_ec2_list_subnets: List subnets
    - aws_ec2_list_route_tables: List route tables
    - aws_ec2_find_resource_by_ip: Find resources by IP
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
    # Helper
    # ------------------------------------------------------------------

    def _extract_tags(self, resource: Dict[str, Any]) -> Dict[str, str]:
        """Extract tags as a key-value dict."""
        return {
            t.get("Key", ""): t.get("Value", "")
            for t in resource.get("Tags", [])
        }

    def _get_name_tag(self, resource: Dict[str, Any]) -> Optional[str]:
        """Extract the Name tag from a resource."""
        return self._extract_tags(resource).get("Name")

    # ------------------------------------------------------------------
    # List Instances
    # ------------------------------------------------------------------

    @tool_schema(ListInstancesInput)
    async def aws_ec2_list_instances(
        self,
        state: str = "running",
        limit: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List EC2 instances with optional state filter."""
        try:
            params: Dict[str, Any] = {}
            filters: List[Dict[str, Any]] = []
            if state:
                filters.append(
                    {
                        "Name": "instance-state-name",
                        "Values": [state],
                    }
                )
            if filters:
                params["Filters"] = filters
            if next_token:
                params["NextToken"] = next_token
            params["MaxResults"] = min(limit, 1000)

            async with self.aws.client("ec2") as ec2:
                response = await ec2.describe_instances(**params)

                instances = []
                for res in response.get("Reservations", []):
                    for inst in res.get("Instances", []):
                        instances.append(
                            {
                                "instance_id": inst.get(
                                    "InstanceId"
                                ),
                                "name": self._get_name_tag(inst),
                                "instance_type": inst.get(
                                    "InstanceType"
                                ),
                                "state": inst.get("State", {}).get(
                                    "Name"
                                ),
                                "private_ip": inst.get(
                                    "PrivateIpAddress"
                                ),
                                "public_ip": inst.get(
                                    "PublicIpAddress"
                                ),
                                "vpc_id": inst.get("VpcId"),
                                "subnet_id": inst.get("SubnetId"),
                                "launch_time": (
                                    inst.get(
                                        "LaunchTime"
                                    ).isoformat()
                                    if inst.get("LaunchTime")
                                    else None
                                ),
                                "architecture": inst.get(
                                    "Architecture"
                                ),
                                "image_id": inst.get("ImageId"),
                                "key_name": inst.get("KeyName"),
                                "security_groups": [
                                    {
                                        "id": sg.get("GroupId"),
                                        "name": sg.get(
                                            "GroupName"
                                        ),
                                    }
                                    for sg in inst.get(
                                        "SecurityGroups", []
                                    )
                                ],
                                "tags": self._extract_tags(inst),
                            }
                        )

                return {
                    "instances": instances[:limit],
                    "count": len(instances[:limit]),
                    "next_token": response.get("NextToken"),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EC2 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Describe Instances
    # ------------------------------------------------------------------

    @tool_schema(DescribeInstancesInput)
    async def aws_ec2_describe_instances(
        self, instance_ids: List[str]
    ) -> Dict[str, Any]:
        """Describe specific EC2 instances by ID."""
        try:
            async with self.aws.client("ec2") as ec2:
                response = await ec2.describe_instances(
                    InstanceIds=instance_ids
                )
                instances = []
                for res in response.get("Reservations", []):
                    for inst in res.get("Instances", []):
                        instances.append(
                            {
                                "instance_id": inst.get(
                                    "InstanceId"
                                ),
                                "name": self._get_name_tag(inst),
                                "instance_type": inst.get(
                                    "InstanceType"
                                ),
                                "state": inst.get("State", {}).get(
                                    "Name"
                                ),
                                "private_ip": inst.get(
                                    "PrivateIpAddress"
                                ),
                                "public_ip": inst.get(
                                    "PublicIpAddress"
                                ),
                                "private_dns": inst.get(
                                    "PrivateDnsName"
                                ),
                                "public_dns": inst.get(
                                    "PublicDnsName"
                                ),
                                "vpc_id": inst.get("VpcId"),
                                "subnet_id": inst.get("SubnetId"),
                                "availability_zone": inst.get(
                                    "Placement", {}
                                ).get("AvailabilityZone"),
                                "launch_time": (
                                    inst.get(
                                        "LaunchTime"
                                    ).isoformat()
                                    if inst.get("LaunchTime")
                                    else None
                                ),
                                "architecture": inst.get(
                                    "Architecture"
                                ),
                                "platform": inst.get("Platform"),
                                "image_id": inst.get("ImageId"),
                                "key_name": inst.get("KeyName"),
                                "iam_profile": inst.get(
                                    "IamInstanceProfile", {}
                                ).get("Arn"),
                                "security_groups": [
                                    {
                                        "id": sg.get("GroupId"),
                                        "name": sg.get(
                                            "GroupName"
                                        ),
                                    }
                                    for sg in inst.get(
                                        "SecurityGroups", []
                                    )
                                ],
                                "tags": self._extract_tags(inst),
                            }
                        )

                return {
                    "instances": instances,
                    "count": len(instances),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EC2 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Security Groups
    # ------------------------------------------------------------------

    @tool_schema(ListSecurityGroupsInput)
    async def aws_ec2_list_security_groups(
        self,
        limit: int = 100,
        vpc_id: Optional[str] = None,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List EC2 security groups."""
        try:
            params: Dict[str, Any] = {
                "MaxResults": min(limit, 1000)
            }
            if vpc_id:
                params["Filters"] = [
                    {"Name": "vpc-id", "Values": [vpc_id]}
                ]
            if next_token:
                params["NextToken"] = next_token

            async with self.aws.client("ec2") as ec2:
                response = await ec2.describe_security_groups(
                    **params
                )
                groups = [
                    {
                        "group_id": sg.get("GroupId"),
                        "group_name": sg.get("GroupName"),
                        "description": sg.get("Description"),
                        "vpc_id": sg.get("VpcId"),
                        "inbound_rules": len(
                            sg.get("IpPermissions", [])
                        ),
                        "outbound_rules": len(
                            sg.get("IpPermissionsEgress", [])
                        ),
                        "tags": self._extract_tags(sg),
                    }
                    for sg in response.get(
                        "SecurityGroups", []
                    )
                ]

                return {
                    "security_groups": groups[:limit],
                    "count": len(groups[:limit]),
                    "next_token": response.get("NextToken"),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EC2 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Find Public Security Groups
    # ------------------------------------------------------------------

    @tool_schema(FindPublicSecurityGroupsInput)
    async def aws_ec2_find_public_security_groups(
        self, port: Optional[int] = None
    ) -> Dict[str, Any]:
        """Find security groups with public internet access (0.0.0.0/0)."""
        try:
            async with self.aws.client("ec2") as ec2:
                response = await ec2.describe_security_groups()
                public_groups = []

                for sg in response.get("SecurityGroups", []):
                    for rule in sg.get("IpPermissions", []):
                        is_public = any(
                            r.get("CidrIp") == "0.0.0.0/0"
                            for r in rule.get("IpRanges", [])
                        ) or any(
                            r.get("CidrIpv6") == "::/0"
                            for r in rule.get(
                                "Ipv6Ranges", []
                            )
                        )

                        if not is_public:
                            continue

                        if port is not None:
                            from_port = rule.get("FromPort", 0)
                            to_port = rule.get("ToPort", 0)
                            if not (
                                from_port <= port <= to_port
                            ):
                                continue

                        public_groups.append(
                            {
                                "group_id": sg.get("GroupId"),
                                "group_name": sg.get(
                                    "GroupName"
                                ),
                                "vpc_id": sg.get("VpcId"),
                                "protocol": rule.get(
                                    "IpProtocol"
                                ),
                                "from_port": rule.get(
                                    "FromPort"
                                ),
                                "to_port": rule.get("ToPort"),
                                "tags": self._extract_tags(sg),
                            }
                        )
                        break

                return {
                    "public_security_groups": public_groups,
                    "count": len(public_groups),
                    "port_filter": port,
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EC2 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List VPCs
    # ------------------------------------------------------------------

    @tool_schema(ListVPCsInput)
    async def aws_ec2_list_vpcs(
        self, limit: int = 50
    ) -> Dict[str, Any]:
        """List VPCs in the account."""
        try:
            async with self.aws.client("ec2") as ec2:
                response = await ec2.describe_vpcs()
                vpcs = [
                    {
                        "vpc_id": v.get("VpcId"),
                        "cidr_block": v.get("CidrBlock"),
                        "state": v.get("State"),
                        "is_default": v.get("IsDefault", False),
                        "name": self._get_name_tag(v),
                        "tags": self._extract_tags(v),
                    }
                    for v in response.get("Vpcs", [])[:limit]
                ]
                return {"vpcs": vpcs, "count": len(vpcs)}
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EC2 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Subnets
    # ------------------------------------------------------------------

    @tool_schema(ListSubnetsInput)
    async def aws_ec2_list_subnets(
        self,
        vpc_id: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List subnets, optionally filtered by VPC."""
        try:
            params: Dict[str, Any] = {}
            if vpc_id:
                params["Filters"] = [
                    {"Name": "vpc-id", "Values": [vpc_id]}
                ]

            async with self.aws.client("ec2") as ec2:
                response = await ec2.describe_subnets(**params)
                subnets = [
                    {
                        "subnet_id": s.get("SubnetId"),
                        "vpc_id": s.get("VpcId"),
                        "cidr_block": s.get("CidrBlock"),
                        "availability_zone": s.get(
                            "AvailabilityZone"
                        ),
                        "state": s.get("State"),
                        "available_ips": s.get(
                            "AvailableIpAddressCount"
                        ),
                        "map_public_ip": s.get(
                            "MapPublicIpOnLaunch", False
                        ),
                        "default_for_az": s.get(
                            "DefaultForAz", False
                        ),
                        "name": self._get_name_tag(s),
                        "tags": self._extract_tags(s),
                    }
                    for s in response.get("Subnets", [])[
                        :limit
                    ]
                ]
                return {"subnets": subnets, "count": len(subnets)}
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EC2 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Route Tables
    # ------------------------------------------------------------------

    @tool_schema(ListRouteTablesInput)
    async def aws_ec2_list_route_tables(
        self,
        vpc_id: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List route tables, optionally filtered by VPC."""
        try:
            params: Dict[str, Any] = {}
            if vpc_id:
                params["Filters"] = [
                    {"Name": "vpc-id", "Values": [vpc_id]}
                ]

            async with self.aws.client("ec2") as ec2:
                response = await ec2.describe_route_tables(
                    **params
                )
                tables = []
                for rt in response.get("RouteTables", [])[
                    :limit
                ]:
                    routes = [
                        {
                            "destination": r.get(
                                "DestinationCidrBlock",
                                r.get(
                                    "DestinationIpv6CidrBlock"
                                ),
                            ),
                            "target": (
                                r.get("GatewayId")
                                or r.get("NatGatewayId")
                                or r.get("InstanceId")
                                or r.get(
                                    "VpcPeeringConnectionId"
                                )
                                or r.get(
                                    "TransitGatewayId"
                                )
                                or "local"
                            ),
                            "state": r.get("State"),
                        }
                        for r in rt.get("Routes", [])
                    ]
                    associations = [
                        {
                            "subnet_id": a.get("SubnetId"),
                            "main": a.get("Main", False),
                        }
                        for a in rt.get("Associations", [])
                    ]
                    tables.append(
                        {
                            "route_table_id": rt.get(
                                "RouteTableId"
                            ),
                            "vpc_id": rt.get("VpcId"),
                            "routes": routes,
                            "associations": associations,
                            "name": self._get_name_tag(rt),
                            "tags": self._extract_tags(rt),
                        }
                    )

                return {
                    "route_tables": tables,
                    "count": len(tables),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EC2 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Find Resource by IP
    # ------------------------------------------------------------------

    @tool_schema(FindResourceByIPInput)
    async def aws_ec2_find_resource_by_ip(
        self, ip_address: str
    ) -> Dict[str, Any]:
        """Find AWS resources associated with a specific IP address."""
        try:
            results: Dict[str, Any] = {
                "ip_address": ip_address,
                "instances": [],
                "network_interfaces": [],
            }

            async with self.aws.client("ec2") as ec2:
                # Search instances
                for ip_filter in [
                    "private-ip-address",
                    "ip-address",
                ]:
                    try:
                        resp = await ec2.describe_instances(
                            Filters=[
                                {
                                    "Name": ip_filter,
                                    "Values": [ip_address],
                                }
                            ]
                        )
                        for res in resp.get(
                            "Reservations", []
                        ):
                            for inst in res.get(
                                "Instances", []
                            ):
                                results["instances"].append(
                                    {
                                        "instance_id": inst.get(
                                            "InstanceId"
                                        ),
                                        "name": self._get_name_tag(
                                            inst
                                        ),
                                        "state": inst.get(
                                            "State", {}
                                        ).get("Name"),
                                        "private_ip": inst.get(
                                            "PrivateIpAddress"
                                        ),
                                        "public_ip": inst.get(
                                            "PublicIpAddress"
                                        ),
                                    }
                                )
                    except ClientError:
                        continue

                # Search network interfaces
                for ni_filter in [
                    "addresses.private-ip-address",
                    "association.public-ip",
                ]:
                    try:
                        resp = await ec2.describe_network_interfaces(
                            Filters=[
                                {
                                    "Name": ni_filter,
                                    "Values": [ip_address],
                                }
                            ]
                        )
                        for ni in resp.get(
                            "NetworkInterfaces", []
                        ):
                            results[
                                "network_interfaces"
                            ].append(
                                {
                                    "interface_id": ni.get(
                                        "NetworkInterfaceId"
                                    ),
                                    "status": ni.get("Status"),
                                    "vpc_id": ni.get("VpcId"),
                                    "subnet_id": ni.get(
                                        "SubnetId"
                                    ),
                                    "private_ip": ni.get(
                                        "PrivateIpAddress"
                                    ),
                                    "description": ni.get(
                                        "Description"
                                    ),
                                    "attachment": ni.get(
                                        "Attachment", {}
                                    ).get("InstanceId"),
                                }
                            )
                    except ClientError:
                        continue

            results["found"] = bool(
                results["instances"]
                or results["network_interfaces"]
            )
            return results
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EC2 error ({error_code}): {e}"
            ) from e
