"""AWS DocumentDB Toolkit for AI-Parrot.

Provides inspection and management of DocumentDB clusters, instances,
snapshots, logs, and events.
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


class ListClustersInput(BaseModel):
    """Input for listing DocumentDB clusters."""

    limit: int = Field(
        100,
        ge=20,
        le=100,
        description="Maximum number of clusters to return (AWS allows 20-100)",
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token from a previous response"
    )


class GetClusterDetailsInput(BaseModel):
    """Input for getting DocumentDB cluster details."""

    cluster_identifier: str = Field(
        ...,
        description="DocumentDB cluster identifier",
    )


class ListClusterInstancesInput(BaseModel):
    """Input for listing instances in a DocumentDB cluster."""

    cluster_identifier: str = Field(
        ...,
        description="DocumentDB cluster identifier to list instances for",
    )
    limit: int = Field(
        100,
        ge=20,
        le=100,
        description="Maximum number of instances to return (AWS allows 20-100)",
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token from a previous response"
    )


class GetInstanceDetailsInput(BaseModel):
    """Input for getting DocumentDB instance details."""

    instance_identifier: str = Field(
        ...,
        description="DocumentDB instance identifier",
    )


class StartClusterInput(BaseModel):
    """Input for starting a DocumentDB cluster."""

    cluster_identifier: str = Field(
        ...,
        description="DocumentDB cluster identifier to start",
    )


class StopClusterInput(BaseModel):
    """Input for stopping a DocumentDB cluster."""

    cluster_identifier: str = Field(
        ...,
        description="DocumentDB cluster identifier to stop",
    )


class RebootInstanceInput(BaseModel):
    """Input for rebooting a DocumentDB instance."""

    instance_identifier: str = Field(
        ...,
        description="DocumentDB instance identifier to reboot",
    )
    force_failover: bool = Field(
        False,
        description="Whether to force a failover (for Multi-AZ clusters)",
    )


class ListSnapshotsInput(BaseModel):
    """Input for listing DocumentDB cluster snapshots."""

    cluster_identifier: Optional[str] = Field(
        None,
        description="Filter snapshots by cluster identifier",
    )
    snapshot_type: Optional[str] = Field(
        None,
        description="Filter by snapshot type (automated, manual, shared, public)",
    )
    limit: int = Field(
        20,
        ge=20,
        le=100,
        description="Maximum number of snapshots to return (AWS allows 20-100)",
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token from a previous response"
    )


class CreateSnapshotInput(BaseModel):
    """Input for creating a manual DocumentDB cluster snapshot."""

    cluster_identifier: str = Field(
        ...,
        description="DocumentDB cluster identifier to snapshot",
    )
    snapshot_identifier: str = Field(
        ...,
        description="Name for the new cluster snapshot",
    )
    tags: Optional[Dict[str, str]] = Field(
        None,
        description="Tags to assign to the snapshot",
    )


class ListLogFilesInput(BaseModel):
    """Input for listing available DB log files."""

    instance_identifier: str = Field(
        ...,
        description="DocumentDB instance identifier",
    )
    filename_contains: Optional[str] = Field(
        None,
        description="Filter log files by filename substring (e.g. 'audit', 'slow', 'profiler')",
    )
    last_written_after: Optional[int] = Field(
        None,
        description="Only return files written after this POSIX timestamp (milliseconds)",
    )
    limit: int = Field(
        100,
        ge=1,
        le=1000,
        description="Maximum number of log files to return",
    )


class DownloadLogInput(BaseModel):
    """Input for downloading DocumentDB log file content."""

    instance_identifier: str = Field(
        ...,
        description="DocumentDB instance identifier",
    )
    log_file_name: str = Field(
        ...,
        description="Log file name from list_log_files",
    )
    marker: Optional[str] = Field(
        None,
        description="Pagination marker for large log files",
    )
    number_of_lines: int = Field(
        500,
        ge=1,
        le=10000,
        description="Maximum number of lines to download",
    )


class DescribeEventsInput(BaseModel):
    """Input for listing DocumentDB operational events."""

    source_identifier: Optional[str] = Field(
        None,
        description="Cluster or instance identifier to filter events",
    )
    source_type: str = Field(
        "db-cluster",
        description="Source type: db-cluster, db-instance, db-parameter-group, db-cluster-snapshot",
    )
    duration_minutes: int = Field(
        1440,
        ge=1,
        le=20160,
        description="How far back to look in minutes (default 1440 = 24h, max ~14 days)",
    )
    event_categories: Optional[List[str]] = Field(
        None,
        description="Filter by event categories (e.g. ['availability', 'failure', 'notification'])",
    )
    limit: int = Field(
        100,
        ge=1,
        le=1000,
        description="Maximum number of events to return",
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class DocumentDBToolkit(AbstractToolkit):
    """Toolkit for managing AWS DocumentDB clusters, instances, and snapshots.

    Each public method is exposed as a separate tool with the `aws_docdb_` prefix.

    Available Operations:
    - aws_docdb_list_clusters: List DocumentDB clusters
    - aws_docdb_get_cluster_details: Get cluster details
    - aws_docdb_list_instances: List instances in a cluster
    - aws_docdb_get_instance_details: Get instance details
    - aws_docdb_start_cluster: Start a stopped cluster
    - aws_docdb_stop_cluster: Stop a running cluster
    - aws_docdb_reboot_instance: Reboot a cluster instance
    - aws_docdb_list_snapshots: List cluster snapshots
    - aws_docdb_create_snapshot: Create a manual cluster snapshot
    - aws_docdb_list_log_files: List available DB log files
    - aws_docdb_download_log: Download DB log file content
    - aws_docdb_describe_events: List operational events/alerts
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
    # List Clusters
    # ------------------------------------------------------------------

    @tool_schema(ListClustersInput)
    async def aws_docdb_list_clusters(
        self,
        limit: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List DocumentDB clusters with pagination."""
        try:
            async with self.aws.client("docdb") as docdb:
                params: Dict[str, Any] = {
                    "MaxRecords": max(20, min(limit, 100)),
                    "Filters": [
                        {
                            "Name": "engine",
                            "Values": ["docdb"],
                        }
                    ],
                }
                if next_token:
                    params["Marker"] = next_token

                response = await docdb.describe_db_clusters(**params)

                clusters = response.get("DBClusters", [])
                next_marker = response.get("Marker")

                simplified = [
                    {
                        "DBClusterIdentifier": c.get("DBClusterIdentifier"),
                        "Status": c.get("Status"),
                        "Engine": c.get("Engine"),
                        "EngineVersion": c.get("EngineVersion"),
                        "Endpoint": c.get("Endpoint"),
                        "ReaderEndpoint": c.get("ReaderEndpoint"),
                        "Port": c.get("Port"),
                        "MasterUsername": c.get("MasterUsername"),
                        "DBClusterMembers": [
                            {
                                "DBInstanceIdentifier": m.get(
                                    "DBInstanceIdentifier"
                                ),
                                "IsClusterWriter": m.get(
                                    "IsClusterWriter"
                                ),
                            }
                            for m in c.get("DBClusterMembers", [])
                        ],
                        "StorageEncrypted": c.get("StorageEncrypted"),
                        "MultiAZ": c.get("MultiAZ"),
                    }
                    for c in clusters
                ]

                return {
                    "clusters": simplified,
                    "count": len(clusters),
                    "next_token": next_marker,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Cluster Details
    # ------------------------------------------------------------------

    @tool_schema(GetClusterDetailsInput)
    async def aws_docdb_get_cluster_details(
        self, cluster_identifier: str
    ) -> Dict[str, Any]:
        """Get detailed information about a specific DocumentDB cluster."""
        try:
            async with self.aws.client("docdb") as docdb:
                response = await docdb.describe_db_clusters(
                    DBClusterIdentifier=cluster_identifier
                )

                clusters = response.get("DBClusters", [])
                if not clusters:
                    raise RuntimeError(
                        f"DocumentDB cluster '{cluster_identifier}' not found"
                    )

                return {"cluster": clusters[0]}
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Instances
    # ------------------------------------------------------------------

    @tool_schema(ListClusterInstancesInput)
    async def aws_docdb_list_instances(
        self,
        cluster_identifier: str,
        limit: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List DocumentDB instances belonging to a cluster."""
        try:
            async with self.aws.client("docdb") as docdb:
                params: Dict[str, Any] = {
                    "MaxRecords": max(20, min(limit, 100)),
                    "Filters": [
                        {
                            "Name": "db-cluster-id",
                            "Values": [cluster_identifier],
                        }
                    ],
                }
                if next_token:
                    params["Marker"] = next_token

                response = await docdb.describe_db_instances(**params)

                instances = response.get("DBInstances", [])
                next_marker = response.get("Marker")

                simplified = [
                    {
                        "DBInstanceIdentifier": inst.get(
                            "DBInstanceIdentifier"
                        ),
                        "DBInstanceClass": inst.get("DBInstanceClass"),
                        "Engine": inst.get("Engine"),
                        "DBInstanceStatus": inst.get("DBInstanceStatus"),
                        "Endpoint": inst.get("Endpoint"),
                        "AvailabilityZone": inst.get("AvailabilityZone"),
                        "DBClusterIdentifier": inst.get(
                            "DBClusterIdentifier"
                        ),
                    }
                    for inst in instances
                ]

                return {
                    "instances": simplified,
                    "count": len(instances),
                    "next_token": next_marker,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Instance Details
    # ------------------------------------------------------------------

    @tool_schema(GetInstanceDetailsInput)
    async def aws_docdb_get_instance_details(
        self, instance_identifier: str
    ) -> Dict[str, Any]:
        """Get detailed information about a specific DocumentDB instance."""
        try:
            async with self.aws.client("docdb") as docdb:
                response = await docdb.describe_db_instances(
                    DBInstanceIdentifier=instance_identifier
                )

                instances = response.get("DBInstances", [])
                if not instances:
                    raise RuntimeError(
                        f"DocumentDB instance '{instance_identifier}' not found"
                    )

                return {"instance": instances[0]}
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Start Cluster
    # ------------------------------------------------------------------

    @tool_schema(StartClusterInput)
    async def aws_docdb_start_cluster(
        self, cluster_identifier: str
    ) -> Dict[str, Any]:
        """Start a stopped DocumentDB cluster."""
        try:
            async with self.aws.client("docdb") as docdb:
                response = await docdb.start_db_cluster(
                    DBClusterIdentifier=cluster_identifier
                )
                return {
                    "cluster": response.get("DBCluster"),
                    "status": "starting",
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Stop Cluster
    # ------------------------------------------------------------------

    @tool_schema(StopClusterInput)
    async def aws_docdb_stop_cluster(
        self, cluster_identifier: str
    ) -> Dict[str, Any]:
        """Stop a running DocumentDB cluster."""
        try:
            async with self.aws.client("docdb") as docdb:
                response = await docdb.stop_db_cluster(
                    DBClusterIdentifier=cluster_identifier
                )
                return {
                    "cluster": response.get("DBCluster"),
                    "status": "stopping",
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Reboot Instance
    # ------------------------------------------------------------------

    @tool_schema(RebootInstanceInput)
    async def aws_docdb_reboot_instance(
        self,
        instance_identifier: str,
        force_failover: bool = False,
    ) -> Dict[str, Any]:
        """Reboot a DocumentDB instance."""
        try:
            async with self.aws.client("docdb") as docdb:
                response = await docdb.reboot_db_instance(
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
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Snapshots
    # ------------------------------------------------------------------

    @tool_schema(ListSnapshotsInput)
    async def aws_docdb_list_snapshots(
        self,
        cluster_identifier: Optional[str] = None,
        snapshot_type: Optional[str] = None,
        limit: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List DocumentDB cluster snapshots with optional filtering."""
        try:
            async with self.aws.client("docdb") as docdb:
                params: Dict[str, Any] = {
                    "MaxRecords": max(20, min(limit, 100)),
                }

                if cluster_identifier:
                    params["DBClusterIdentifier"] = cluster_identifier
                if snapshot_type:
                    params["SnapshotType"] = snapshot_type
                if next_token:
                    params["Marker"] = next_token

                response = await docdb.describe_db_cluster_snapshots(
                    **params
                )

                snapshots = response.get("DBClusterSnapshots", [])
                next_marker = response.get("Marker")

                return {
                    "snapshots": snapshots,
                    "count": len(snapshots),
                    "next_token": next_marker,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Create Snapshot
    # ------------------------------------------------------------------

    @tool_schema(CreateSnapshotInput)
    async def aws_docdb_create_snapshot(
        self,
        cluster_identifier: str,
        snapshot_identifier: str,
        tags: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Create a manual DocumentDB cluster snapshot."""
        try:
            async with self.aws.client("docdb") as docdb:
                params = {
                    "DBClusterIdentifier": cluster_identifier,
                    "DBClusterSnapshotIdentifier": snapshot_identifier,
                }

                if tags:
                    tag_list = [
                        {"Key": k, "Value": v} for k, v in tags.items()
                    ]
                    params["Tags"] = tag_list

                response = await docdb.create_db_cluster_snapshot(**params)

                return {
                    "snapshot": response.get("DBClusterSnapshot"),
                    "status": "creating",
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Log Files
    # ------------------------------------------------------------------

    @tool_schema(ListLogFilesInput)
    async def aws_docdb_list_log_files(
        self,
        instance_identifier: str,
        filename_contains: Optional[str] = None,
        last_written_after: Optional[int] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List available DB log files for a DocumentDB instance."""
        try:
            async with self.aws.client("docdb") as docdb:
                params: Dict[str, Any] = {
                    "DBInstanceIdentifier": instance_identifier,
                    "MaxRecords": min(limit, 1000),
                }
                if filename_contains:
                    params["FilenameContains"] = filename_contains
                if last_written_after is not None:
                    params["FileLastWritten"] = last_written_after

                response = await docdb.describe_db_log_files(**params)

                log_files = [
                    {
                        "LogFileName": lf.get("LogFileName"),
                        "LastWritten": lf.get("LastWritten"),
                        "Size": lf.get("Size"),
                    }
                    for lf in response.get("DescribeDBLogFiles", [])
                ]

                return {
                    "log_files": log_files,
                    "count": len(log_files),
                    "marker": response.get("Marker"),
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Download Log
    # ------------------------------------------------------------------

    @tool_schema(DownloadLogInput)
    async def aws_docdb_download_log(
        self,
        instance_identifier: str,
        log_file_name: str,
        marker: Optional[str] = None,
        number_of_lines: int = 500,
    ) -> Dict[str, Any]:
        """Download a portion of a DocumentDB log file."""
        try:
            async with self.aws.client("docdb") as docdb:
                params: Dict[str, Any] = {
                    "DBInstanceIdentifier": instance_identifier,
                    "LogFileName": log_file_name,
                    "NumberOfLines": number_of_lines,
                }
                if marker:
                    params["Marker"] = marker

                response = await docdb.download_db_log_file_portion(
                    **params
                )

                return {
                    "log_data": response.get("LogFileData", ""),
                    "marker": response.get("Marker"),
                    "additional_data_pending": response.get(
                        "AdditionalDataPending", False
                    ),
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Describe Events
    # ------------------------------------------------------------------

    @tool_schema(DescribeEventsInput)
    async def aws_docdb_describe_events(
        self,
        source_identifier: Optional[str] = None,
        source_type: str = "db-cluster",
        duration_minutes: int = 1440,
        event_categories: Optional[List[str]] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List DocumentDB operational events and alerts."""
        try:
            async with self.aws.client("docdb") as docdb:
                params: Dict[str, Any] = {
                    "SourceType": source_type,
                    "Duration": duration_minutes,
                    "MaxRecords": min(max(20, limit), 100),
                }
                if source_identifier:
                    params["SourceIdentifier"] = source_identifier
                if event_categories:
                    params["EventCategories"] = event_categories

                response = await docdb.describe_events(**params)

                events = [
                    {
                        "Date": str(ev.get("Date", "")),
                        "SourceIdentifier": ev.get("SourceIdentifier"),
                        "SourceType": ev.get("SourceType"),
                        "Message": ev.get("Message"),
                        "EventCategories": ev.get("EventCategories", []),
                    }
                    for ev in response.get("Events", [])
                ]

                return {
                    "events": events,
                    "count": len(events),
                    "marker": response.get("Marker"),
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS DocumentDB error ({error_code}): {e}"
            ) from e
