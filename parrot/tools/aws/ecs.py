"""AWS ECS Toolkit for AI-Parrot.

Provides inspection of ECS/Fargate tasks.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from botocore.exceptions import ClientError

from ...interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit


# ------------------------------------------------------------------
# Input Schemas
# ------------------------------------------------------------------


class ListClustersInput(BaseModel):
    """Input for listing ECS clusters."""


class ListServicesInput(BaseModel):
    """Input for listing ECS services in a cluster."""

    cluster_name: str = Field(
        ..., description="ECS cluster name or ARN"
    )


class ListTasksInput(BaseModel):
    """Input for listing ECS tasks with optional filters."""

    cluster_name: str = Field(
        ..., description="ECS cluster name or ARN"
    )
    service_name: Optional[str] = Field(
        None, description="ECS service name to filter tasks"
    )
    desired_status: Optional[str] = Field(
        None,
        description="Filter by desired status (e.g. 'RUNNING', 'STOPPED')",
    )
    launch_type: Optional[str] = Field(
        None,
        description="Filter by launch type (e.g. 'FARGATE', 'EC2')",
    )


class DescribeTasksInput(BaseModel):
    """Input for describing specific ECS tasks."""

    cluster_name: str = Field(
        ..., description="ECS cluster name or ARN"
    )
    task_arns: List[str] = Field(
        ..., description="Task ARNs to describe"
    )


class GetFargateLogsInput(BaseModel):
    """Input for fetching Fargate task logs from CloudWatch."""

    log_group_name: str = Field(
        ..., description="CloudWatch log group used by Fargate tasks"
    )
    log_stream_prefix: Optional[str] = Field(
        None, description="Prefix for CloudWatch log streams"
    )
    start_time: Optional[str] = Field(
        None,
        description="Start time (ISO format or relative like '-1h', '-24h')",
    )
    limit: int = Field(
        100, description="Maximum number of log events"
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class ECSToolkit(AbstractToolkit):
    """Toolkit for inspecting AWS ECS/Fargate resources.

    Each public method is exposed as a separate tool with the `aws_ecs_` prefix.

    Available Operations:
    - aws_ecs_list_clusters: List ECS clusters
    - aws_ecs_list_services: List services in a cluster
    - aws_ecs_list_tasks: List tasks with filters
    - aws_ecs_describe_tasks: Describe specific tasks
    - aws_ecs_get_fargate_logs: Get Fargate task logs
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
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_time(self, value: Optional[str]) -> Optional[datetime]:
        """Parse time string to datetime."""
        if value is None or value == "now":
            return datetime.now(tz=timezone.utc)

        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            pass

        if value.startswith("-"):
            raw = value[1:]
            match = re.match(r"(\d+)([smhd])", raw)
            if not match:
                raise ValueError(f"Invalid time format: {value}")

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
                raise ValueError(f"Unsupported time unit: {unit}")

            return datetime.now(timezone.utc) - delta

        raise ValueError(f"Invalid time format: {value}")

    # ------------------------------------------------------------------
    # ECS Operations
    # ------------------------------------------------------------------

    @tool_schema(ListClustersInput)
    async def aws_ecs_list_clusters(self) -> Dict[str, Any]:
        """List all ECS clusters in the AWS account."""
        try:
            async with self.aws.client("ecs") as ecs:
                response = await ecs.list_clusters()
                clusters = response.get("clusterArns", [])
                return {"clusters": clusters, "count": len(clusters)}
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS ECS error ({error_code}): {e}"
            ) from e

    @tool_schema(ListServicesInput)
    async def aws_ecs_list_services(
        self, cluster_name: str
    ) -> Dict[str, Any]:
        """List ECS services in a cluster."""
        try:
            async with self.aws.client("ecs") as ecs:
                response = await ecs.list_services(
                    cluster=cluster_name
                )
                services = response.get("serviceArns", [])
                return {
                    "cluster": cluster_name,
                    "services": services,
                    "count": len(services),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS ECS error ({error_code}): {e}"
            ) from e

    @tool_schema(ListTasksInput)
    async def aws_ecs_list_tasks(
        self,
        cluster_name: str,
        service_name: Optional[str] = None,
        desired_status: Optional[str] = None,
        launch_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List ECS tasks with optional filters."""
        try:
            params: Dict[str, Any] = {"cluster": cluster_name}
            if service_name:
                params["serviceName"] = service_name
            if desired_status:
                params["desiredStatus"] = desired_status
            if launch_type:
                params["launchType"] = launch_type

            async with self.aws.client("ecs") as ecs:
                response = await ecs.list_tasks(**params)
                tasks = response.get("taskArns", [])
                return {
                    "cluster": cluster_name,
                    "tasks": tasks,
                    "count": len(tasks),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS ECS error ({error_code}): {e}"
            ) from e

    @tool_schema(DescribeTasksInput)
    async def aws_ecs_describe_tasks(
        self, cluster_name: str, task_arns: List[str]
    ) -> Dict[str, Any]:
        """Describe specific ECS tasks."""
        try:
            async with self.aws.client("ecs") as ecs:
                response = await ecs.describe_tasks(
                    cluster=cluster_name, tasks=task_arns
                )
                tasks = response.get("tasks", [])
                return {
                    "cluster": cluster_name,
                    "tasks": tasks,
                    "count": len(tasks),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS ECS error ({error_code}): {e}"
            ) from e

    @tool_schema(GetFargateLogsInput)
    async def aws_ecs_get_fargate_logs(
        self,
        log_group_name: str,
        log_stream_prefix: Optional[str] = None,
        start_time: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Get Fargate task logs from CloudWatch."""
        try:
            params: Dict[str, Any] = {
                "logGroupName": log_group_name,
                "limit": limit,
            }
            if log_stream_prefix:
                params["logStreamNamePrefix"] = log_stream_prefix
            if start_time:
                parsed = self._parse_time(start_time)
                if parsed:
                    params["startTime"] = int(
                        parsed.timestamp() * 1000
                    )

            async with self.aws.client("logs") as logs:
                response = await logs.filter_log_events(**params)
                events = [
                    {
                        "timestamp": datetime.fromtimestamp(
                            event["timestamp"] / 1000
                        ).isoformat(),
                        "message": event.get("message"),
                        "log_stream": event.get("logStreamName"),
                    }
                    for event in response.get("events", [])
                ]
                return {
                    "log_group": log_group_name,
                    "events": events,
                    "count": len(events),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS ECS error ({error_code}): {e}"
            ) from e
