"""AWS RDS Toolkit for AI-Parrot.

Provides inspection and management of RDS instances, snapshots,
logs, events, and Performance Insights.
"""
from __future__ import annotations
import contextlib
import re
from datetime import datetime, timedelta, timezone
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
        20,
        ge=20,
        le=100,
        description="Maximum number of instances to return (AWS allows 20-100)",
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
        20,
        ge=20,
        le=100,
        description="Maximum number of snapshots to return (AWS allows 20-100)",
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


class ListLogFilesInput(BaseModel):
    """Input for listing available DB log files."""

    instance_identifier: str = Field(
        ...,
        description="RDS instance identifier",
    )
    filename_contains: Optional[str] = Field(
        None,
        description="Filter log files by filename substring (e.g. 'slowquery', 'error', 'postgresql')",
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
    """Input for downloading RDS log file content."""

    instance_identifier: str = Field(
        ...,
        description="RDS instance identifier",
    )
    log_file_name: str = Field(
        ...,
        description="Log file name from list_log_files (e.g. 'error/postgresql.log.2026-02-16-18')",
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
    """Input for listing RDS operational events."""

    source_identifier: Optional[str] = Field(
        None,
        description="Instance or cluster identifier to filter events",
    )
    source_type: str = Field(
        "db-instance",
        description="Source type: db-instance, db-cluster, db-parameter-group, db-security-group, db-snapshot",
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


class PerformanceInsightsInput(BaseModel):
    """Input for fetching Performance Insights metrics."""

    instance_identifier: str = Field(
        ...,
        description="RDS instance identifier (PI must be enabled on this instance)",
    )
    metric_queries: Optional[List[str]] = Field(
        None,
        description="Metric types to query (defaults to ['db.load.avg'])",
    )
    start_time: str = Field(
        "-1h",
        description="Start time (ISO format or relative like '-1h', '-30m', '-7d')",
    )
    end_time: str = Field(
        "now",
        description="End time (ISO format or 'now')",
    )
    period_seconds: int = Field(
        60,
        ge=1,
        description="Period in seconds for data points",
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class RDSToolkit(AbstractToolkit):
    """Toolkit for managing AWS RDS instances, snapshots, logs, and diagnostics.

    Each public method is exposed as a separate tool with the `aws_rds_` prefix.

    Available Operations:
    - aws_rds_list_instances: List RDS instances
    - aws_rds_get_instance_details: Get instance details
    - aws_rds_start_instance: Start an RDS instance
    - aws_rds_stop_instance: Stop an RDS instance
    - aws_rds_reboot_instance: Reboot an RDS instance
    - aws_rds_list_snapshots: List DB snapshots
    - aws_rds_create_snapshot: Create a manual DB snapshot
    - aws_rds_list_log_files: List available DB log files
    - aws_rds_download_log: Download DB log file content
    - aws_rds_describe_events: List RDS operational events/alerts
    - aws_rds_get_performance_insights: Fetch PI metrics (blocking queries, waits)
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
                params: Dict[str, Any] = {"MaxRecords": max(20, min(limit, 100))}
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
                params: Dict[str, Any] = {"MaxRecords": max(20, min(limit, 100))}
                
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

    # ------------------------------------------------------------------
    # List Log Files
    # ------------------------------------------------------------------

    @tool_schema(ListLogFilesInput)
    async def aws_rds_list_log_files(
        self,
        instance_identifier: str,
        filename_contains: Optional[str] = None,
        last_written_after: Optional[int] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List available DB log files for an RDS instance."""
        try:
            async with self.aws.client("rds") as rds:
                params: Dict[str, Any] = {
                    "DBInstanceIdentifier": instance_identifier,
                    "MaxRecords": min(limit, 1000),
                }
                if filename_contains:
                    params["FilenameContains"] = filename_contains
                if last_written_after is not None:
                    params["FileLastWritten"] = last_written_after

                response = await rds.describe_db_log_files(**params)

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
                f"AWS RDS error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Download Log
    # ------------------------------------------------------------------

    @tool_schema(DownloadLogInput)
    async def aws_rds_download_log(
        self,
        instance_identifier: str,
        log_file_name: str,
        marker: Optional[str] = None,
        number_of_lines: int = 500,
    ) -> Dict[str, Any]:
        """Download a portion of an RDS log file."""
        try:
            async with self.aws.client("rds") as rds:
                params: Dict[str, Any] = {
                    "DBInstanceIdentifier": instance_identifier,
                    "LogFileName": log_file_name,
                    "NumberOfLines": number_of_lines,
                }
                if marker:
                    params["Marker"] = marker

                response = await rds.download_db_log_file_portion(**params)

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
                f"AWS RDS error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Describe Events
    # ------------------------------------------------------------------

    @tool_schema(DescribeEventsInput)
    async def aws_rds_describe_events(
        self,
        source_identifier: Optional[str] = None,
        source_type: str = "db-instance",
        duration_minutes: int = 1440,
        event_categories: Optional[List[str]] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List RDS operational events and alerts."""
        try:
            async with self.aws.client("rds") as rds:
                params: Dict[str, Any] = {
                    "SourceType": source_type,
                    "Duration": duration_minutes,
                    "MaxRecords": min(max(20, limit), 100),
                }
                if source_identifier:
                    params["SourceIdentifier"] = source_identifier
                if event_categories:
                    params["EventCategories"] = event_categories

                response = await rds.describe_events(**params)

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
                f"AWS RDS error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Performance Insights
    # ------------------------------------------------------------------

    def _parse_relative_time(self, time_str: str) -> datetime:
        """Parse relative time strings like '-1h', '-30m', '-7d'."""
        if time_str == "now" or time_str is None:
            return datetime.now(timezone.utc)

        with contextlib.suppress(ValueError, AttributeError):
            return datetime.fromisoformat(
                time_str.replace("Z", "+00:00")
            )

        if time_str.startswith("-"):
            raw = time_str[1:]
            match = re.match(r"(\d+)([smhd])", raw)
            if not match:
                raise ValueError(f"Invalid time format: {time_str}")

            amount, unit = match.groups()
            amount = int(amount)
            deltas = {
                "s": timedelta(seconds=amount),
                "m": timedelta(minutes=amount),
                "h": timedelta(hours=amount),
                "d": timedelta(days=amount),
            }
            delta = deltas.get(unit)
            if delta is None:
                raise ValueError(f"Unknown time unit: {unit}")
            return datetime.now(timezone.utc) - delta

        raise ValueError(f"Invalid time format: {time_str}")

    @tool_schema(PerformanceInsightsInput)
    async def aws_rds_get_performance_insights(
        self,
        instance_identifier: str,
        metric_queries: Optional[List[str]] = None,
        start_time: str = "-1h",
        end_time: str = "now",
        period_seconds: int = 60,
    ) -> Dict[str, Any]:
        """Fetch Performance Insights metrics for blocking queries and wait events."""
        if metric_queries is None:
            metric_queries = ["db.load.avg"]

        # Resolve DbiResourceId from instance identifier.
        try:
            async with self.aws.client("rds") as rds:
                resp = await rds.describe_db_instances(
                    DBInstanceIdentifier=instance_identifier
                )
                instances = resp.get("DBInstances", [])
                if not instances:
                    raise RuntimeError(
                        f"RDS instance '{instance_identifier}' not found"
                    )
                inst = instances[0]
                resource_id = inst.get("DbiResourceId")
                if not resource_id:
                    raise RuntimeError(
                        f"DbiResourceId not available for '{instance_identifier}'. "
                        "Performance Insights may not be enabled."
                    )
                pi_enabled = inst.get(
                    "PerformanceInsightsEnabled", False
                )
                if not pi_enabled:
                    return {
                        "error": (
                            f"Performance Insights is not enabled on "
                            f"'{instance_identifier}'. Enable it in the "
                            f"RDS console or via modify-db-instance."
                        ),
                        "metrics": [],
                    }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS RDS error ({error_code}): {e}"
            ) from e

        # Fetch PI metrics.
        start_dt = self._parse_relative_time(start_time)
        end_dt = self._parse_relative_time(end_time)

        queries = [
            {
                "Metric": metric,
                "GroupBy": {
                    "Group": "db.wait_event",
                    "Limit": 10,
                },
            }
            for metric in metric_queries
        ]

        try:
            async with self.aws.client("pi") as pi:
                response = await pi.get_resource_metrics(
                    ServiceType="RDS",
                    Identifier=resource_id,
                    MetricQueries=queries,
                    StartTime=start_dt,
                    EndTime=end_dt,
                    PeriodInSeconds=period_seconds,
                )

                metric_list = response.get("MetricList", [])
                results = []
                for m in metric_list:
                    key = m.get("Key", {})
                    data_points = m.get("DataPoints", [])
                    simplified_points = [
                        {
                            "Timestamp": str(dp.get("Timestamp", "")),
                            "Value": dp.get("Value"),
                        }
                        for dp in data_points
                    ]
                    results.append({
                        "Metric": key.get("Metric"),
                        "Dimensions": key.get("Dimensions", {}),
                        "DataPoints": simplified_points,
                    })

                return {
                    "instance": instance_identifier,
                    "resource_id": resource_id,
                    "metrics": results,
                    "aligned_start": str(
                        response.get("AlignedStartTime", "")
                    ),
                    "aligned_end": str(
                        response.get("AlignedEndTime", "")
                    ),
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS PI error ({error_code}): {e}"
            ) from e
