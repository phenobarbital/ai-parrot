"""AWS RDS Toolkit for AI-Parrot.

Provides inspection and management of RDS instances and snapshots.
"""
from __future__ import annotations

import time
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
    """Input for listing RDS instances."""

    limit: int = Field(
        100, description="Maximum number of instances to return"
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token from a previous response"
    )


class GetInstanceDetailsInput(BaseModel):
    """Input for getting RDS instance details."""

    instance_identifier: str = Field(
        ...,
        description="RDS instance identifier",
    )


class StartInstanceInput(BaseModel):
    """Input for starting an RDS instance."""

    instance_identifier: str = Field(
        ...,
        description="RDS instance identifier to start",
    )


class StopInstanceInput(BaseModel):
    """Input for stopping an RDS instance."""

    instance_identifier: str = Field(
        ...,
        description="RDS instance identifier to stop",
    )
    snapshot_identifier: Optional[str] = Field(
        None,
        description="Name of the DB snapshot to create before stopping",
    )


class RebootInstanceInput(BaseModel):
    """Input for rebooting an RDS instance."""

    instance_identifier: str = Field(
        ...,
        description="RDS instance identifier to reboot",
    )
    force_failover: bool = Field(
        False,
        description="Whether to force a failover (for Multi-AZ instances)",
    )


class ListSnapshotsInput(BaseModel):
    """Input for listing RDS snapshots."""

    instance_identifier: Optional[str] = Field(
        None,
        description="Filter snapshots by instance identifier",
    )
    snapshot_type: Optional[str] = Field(
        None,
        description="Filter by snapshot type (automated, manual, shared, public, awsbackup)",
    )
    limit: int = Field(
        100, description="Maximum number of snapshots to return"
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token from a previous response"
    )


class CreateSnapshotInput(BaseModel):
    """Input for creating a manual DB snapshot."""

    instance_identifier: str = Field(
        ...,
        description="RDS instance identifier to snapshot",
    )
    snapshot_identifier: str = Field(
        ...,
        description="Name for the new DB snapshot",
    )
    tags: Optional[Dict[str, str]] = Field(
        None,
        description="Tags to assign to the snapshot",
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class RDSToolkit(AbstractToolkit):
    """Toolkit for managing AWS RDS instances and snapshots.

    Each public method is exposed as a separate tool with the `aws_rds_` prefix.

    Available Operations:
    - aws_rds_list_instances: List RDS instances
    - aws_rds_get_instance_details: Get instance details
    - aws_rds_start_instance: Start an RDS instance
    - aws_rds_stop_instance: Stop an RDS instance
    - aws_rds_reboot_instance: Reboot an RDS instance
    - aws_rds_list_snapshots: List DB snapshots
    - aws_rds_create_snapshot: Create a manual DB snapshot
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
    # List Instances
    # ------------------------------------------------------------------

    @tool_schema(ListInstancesInput)
    async def aws_rds_list_instances(
        self,
        limit: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List RDS instances with pagination."""
        try:
            async with self.aws.client("rds") as rds:
                params: Dict[str, Any] = {"MaxRecords": limit}
                if next_token:
                    params["Marker"] = next_token

                response = await rds.describe_db_instances(**params)

                instances = response.get("DBInstances", [])
                next_marker = response.get("Marker")

                # Simplified instance info for list view
                simplified_instances = []
                for inst in instances:
                    simplified_instances.append({
                        "DBInstanceIdentifier": inst.get("DBInstanceIdentifier"),
                        "DBInstanceClass": inst.get("DBInstanceClass"),
                        "Engine": inst.get("Engine"),
                        "DBInstanceStatus": inst.get("DBInstanceStatus"),
                        "Endpoint": inst.get("Endpoint"),
                        "AllocatedStorage": inst.get("AllocatedStorage"),
                    })

                return {
                    "instances": simplified_instances,
                    "count": len(instances),
                    "next_token": next_marker,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS RDS error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Instance Details
    # ------------------------------------------------------------------

    @tool_schema(GetInstanceDetailsInput)
    async def aws_rds_get_instance_details(
        self, instance_identifier: str
    ) -> Dict[str, Any]:
        """Get detailed information about a specific RDS instance."""
        try:
            async with self.aws.client("rds") as rds:
                response = await rds.describe_db_instances(
                    DBInstanceIdentifier=instance_identifier
                )

                instances = response.get("DBInstances", [])
                if not instances:
                    raise RuntimeError(
                        f"RDS instance '{instance_identifier}' not found"
                    )

                return {"instance": instances[0]}
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS RDS error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Start Instance
    # ------------------------------------------------------------------

    @tool_schema(StartInstanceInput)
    async def aws_rds_start_instance(
        self, instance_identifier: str
    ) -> Dict[str, Any]:
        """Start a stopped RDS instance."""
        try:
            async with self.aws.client("rds") as rds:
                response = await rds.start_db_instance(
                    DBInstanceIdentifier=instance_identifier
                )
                return {
                    "instance": response.get("DBInstance"),
                    "status": "starting",
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS RDS error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Stop Instance
    # ------------------------------------------------------------------

    @tool_schema(StopInstanceInput)
    async def aws_rds_stop_instance(
        self,
        instance_identifier: str,
        snapshot_identifier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Stop a running RDS instance."""
        try:
            async with self.aws.client("rds") as rds:
                params = {"DBInstanceIdentifier": instance_identifier}
                if snapshot_identifier:
                    params["DBSnapshotIdentifier"] = snapshot_identifier

                response = await rds.stop_db_instance(**params)
                return {
                    "instance": response.get("DBInstance"),
                    "status": "stopping",
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS RDS error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Reboot Instance
    # ------------------------------------------------------------------

    @tool_schema(RebootInstanceInput)
    async def aws_rds_reboot_instance(
        self,
        instance_identifier: str,
        force_failover: bool = False,
    ) -> Dict[str, Any]:
        """Reboot an RDS instance."""
        try:
            async with self.aws.client("rds") as rds:
                response = await rds.reboot_db_instance(
                    DBInstanceIdentifier=instance_identifier,
                    ForceFailover=force_failover,
                )
                return {
                    "instance": response.get("DBInstance"),
                    "status": "rebooting",
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS RDS error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Snapshots
    # ------------------------------------------------------------------

    @tool_schema(ListSnapshotsInput)
    async def aws_rds_list_snapshots(
        self,
        instance_identifier: Optional[str] = None,
        snapshot_type: Optional[str] = None,
        limit: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List RDS snapshots with optional filtering."""
        try:
            async with self.aws.client("rds") as rds:
                params: Dict[str, Any] = {"MaxRecords": limit}
                
                if instance_identifier:
                    params["DBInstanceIdentifier"] = instance_identifier
                if snapshot_type:
                    params["SnapshotType"] = snapshot_type
                if next_token:
                    params["Marker"] = next_token

                response = await rds.describe_db_snapshots(**params)

                snapshots = response.get("DBSnapshots", [])
                next_marker = response.get("Marker")

                return {
                    "snapshots": snapshots,
                    "count": len(snapshots),
                    "next_token": next_marker,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS RDS error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Create Snapshot
    # ------------------------------------------------------------------

    @tool_schema(CreateSnapshotInput)
    async def aws_rds_create_snapshot(
        self,
        instance_identifier: str,
        snapshot_identifier: str,
        tags: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Create a manual DB snapshot."""
        try:
            async with self.aws.client("rds") as rds:
                params = {
                    "DBInstanceIdentifier": instance_identifier,
                    "DBSnapshotIdentifier": snapshot_identifier,
                }
                
                if tags:
                    tag_list = [
                        {"Key": k, "Value": v} for k, v in tags.items()
                    ]
                    params["Tags"] = tag_list

                response = await rds.create_db_snapshot(**params)
                
                return {
                    "snapshot": response.get("DBSnapshot"),
                    "status": "creating",
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS RDS error ({error_code}): {e}"
            ) from e
