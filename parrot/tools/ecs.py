"""
AWS ECS and EKS Tool for AI-Parrot

Provides helpers to inspect Fargate tasks, ECS services, and EKS clusters.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError
from pydantic import Field, field_validator

from ..interfaces.aws import AWSInterface
from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult


class ECSOperation(str, Enum):
    """Supported ECS/EKS operations."""

    LIST_ECS_CLUSTERS = "list_ecs_clusters"
    LIST_SERVICES = "list_services"
    LIST_TASKS = "list_tasks"
    DESCRIBE_TASKS = "describe_tasks"
    GET_FARGATE_LOGS = "get_fargate_logs"
    GET_EKS_CLUSTER_INFO = "get_eks_cluster_info"
    LIST_EKS_CLUSTERS = "list_eks_clusters"
    LIST_EKS_NODEGROUPS = "list_eks_nodegroups"
    DESCRIBE_EKS_NODEGROUP = "describe_eks_nodegroup"
    LIST_EKS_FARGATE_PROFILES = "list_eks_fargate_profiles"
    DESCRIBE_EKS_FARGATE_PROFILE = "describe_eks_fargate_profile"


class ECSToolArgs(AbstractToolArgsSchema):
    """Arguments schema for ECS/EKS operations."""

    operation: ECSOperation = Field(
        ..., description="Operation to perform for ECS/Fargate or EKS"
    )

    cluster_name: Optional[str] = Field(
        None, description="ECS or EKS cluster name"
    )
    service_name: Optional[str] = Field(
        None, description="ECS service name"
    )
    task_arns: Optional[List[str]] = Field(
        None, description="Specific task ARNs to describe"
    )
    launch_type: Optional[str] = Field(
        None, description="Filter tasks by launch type (e.g., 'FARGATE')"
    )
    desired_status: Optional[str] = Field(
        None, description="Filter tasks by desired status (e.g., 'RUNNING')"
    )
    log_group_name: Optional[str] = Field(
        None, description="CloudWatch log group used by Fargate tasks"
    )
    log_stream_prefix: Optional[str] = Field(
        None, description="Prefix for CloudWatch log streams"
    )
    start_time: Optional[str] = Field(
        None,
        description=(
            "Start time for log retrieval (ISO format or relative like '-1h', '-24h')."
        ),
    )
    limit: Optional[int] = Field(
        100, description="Maximum number of log events to return"
    )
    eks_nodegroup: Optional[str] = Field(
        None, description="EKS nodegroup name to describe"
    )
    eks_fargate_profile: Optional[str] = Field(
        None, description="EKS Fargate profile name to describe"
    )

    @field_validator("start_time", mode="before")
    @classmethod
    def validate_start_time(cls, value):
        if value is None or value == "now":
            return value
        return value


class ECSTool(AbstractTool):
    """
    Tool for inspecting AWS ECS/Fargate tasks and EKS Kubernetes clusters.

    Capabilities include:
    - Listing ECS clusters, services, and tasks
    - Describing ECS tasks (useful for Fargate workloads)
    - Fetching Fargate task logs from CloudWatch
    - Inspecting EKS cluster, nodegroup, and Fargate profile metadata
    """

    name: str = "ecs"
    description: str = "Inspect AWS ECS/Fargate tasks and EKS Kubernetes clusters"
    args_schema: type[AbstractToolArgsSchema] = ECSToolArgs

    def __init__(self, aws_id: str = "default", region_name: Optional[str] = None, **kwargs):
        super().__init__()
        self.aws = AWSInterface(aws_id=aws_id, region_name=region_name, **kwargs)

    def _parse_time(self, value: Optional[str]) -> Optional[datetime]:
        if value is None or value == "now":
            return datetime.utcnow()

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

        if value.startswith("-"):
            raw = value[1:]
            import re

            match = re.match(r"(\d+)([smhd])", raw)
            if not match:
                raise ValueError(f"Invalid time format: {value}")

            amount, unit = match.groups()
            amount = int(amount)
            if unit == "s":
                delta = timedelta(seconds=amount)
            elif unit == "m":
                delta = timedelta(minutes=amount)
            elif unit == "h":
                delta = timedelta(hours=amount)
            elif unit == "d":
                delta = timedelta(days=amount)
            else:
                raise ValueError(f"Unsupported time unit: {unit}")

            return datetime.utcnow() - delta

        raise ValueError(f"Invalid time format: {value}")

    async def _list_ecs_clusters(self) -> List[str]:
        async with self.aws.client("ecs") as ecs:
            response = await ecs.list_clusters()
            return response.get("clusterArns", [])

    async def _list_services(self, cluster: str) -> List[str]:
        async with self.aws.client("ecs") as ecs:
            response = await ecs.list_services(cluster=cluster)
            return response.get("serviceArns", [])

    async def _list_tasks(
        self,
        cluster: str,
        service_name: Optional[str] = None,
        desired_status: Optional[str] = None,
        launch_type: Optional[str] = None,
    ) -> List[str]:
        params: Dict[str, Any] = {"cluster": cluster}
        if service_name:
            params["serviceName"] = service_name
        if desired_status:
            params["desiredStatus"] = desired_status
        if launch_type:
            params["launchType"] = launch_type

        async with self.aws.client("ecs") as ecs:
            response = await ecs.list_tasks(**params)
            return response.get("taskArns", [])

    async def _describe_tasks(self, cluster: str, task_arns: List[str]) -> List[Dict[str, Any]]:
        async with self.aws.client("ecs") as ecs:
            response = await ecs.describe_tasks(cluster=cluster, tasks=task_arns)
            return response.get("tasks", [])

    async def _get_fargate_logs(
        self,
        log_group_name: str,
        log_stream_prefix: Optional[str] = None,
        start_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "logGroupName": log_group_name,
            "limit": limit,
        }
        if log_stream_prefix:
            params["logStreamNamePrefix"] = log_stream_prefix
        if start_time:
            params["startTime"] = int(start_time.timestamp() * 1000)

        async with self.aws.client("logs") as logs:
            response = await logs.filter_log_events(**params)
            return [
                {
                    "timestamp": datetime.fromtimestamp(event["timestamp"] / 1000).isoformat(),
                    "message": event.get("message"),
                    "log_stream": event.get("logStreamName"),
                }
                for event in response.get("events", [])
            ]

    async def _get_eks_cluster_info(self, cluster_name: str) -> Dict[str, Any]:
        async with self.aws.client("eks") as eks:
            response = await eks.describe_cluster(name=cluster_name)
            cluster = response.get("cluster", {})
            return {
                "name": cluster.get("name"),
                "status": cluster.get("status"),
                "version": cluster.get("version"),
                "endpoint": cluster.get("endpoint"),
                "arn": cluster.get("arn"),
                "created_at": cluster.get("createdAt").isoformat()
                if cluster.get("createdAt")
                else None,
                "role_arn": cluster.get("roleArn"),
                "platform_version": cluster.get("platformVersion"),
                "kubernetes_network_config": cluster.get("kubernetesNetworkConfig"),
                "logging": cluster.get("logging"),
                "resources_vpc_config": cluster.get("resourcesVpcConfig"),
            }

    async def _list_eks_clusters(self) -> List[str]:
        async with self.aws.client("eks") as eks:
            response = await eks.list_clusters()
            return response.get("clusters", [])

    async def _list_eks_nodegroups(self, cluster_name: str) -> List[str]:
        async with self.aws.client("eks") as eks:
            response = await eks.list_nodegroups(clusterName=cluster_name)
            return response.get("nodegroups", [])

    async def _describe_eks_nodegroup(self, cluster_name: str, nodegroup: str) -> Dict[str, Any]:
        async with self.aws.client("eks") as eks:
            response = await eks.describe_nodegroup(clusterName=cluster_name, nodegroupName=nodegroup)
            return response.get("nodegroup", {})

    async def _list_eks_fargate_profiles(self, cluster_name: str) -> List[str]:
        async with self.aws.client("eks") as eks:
            response = await eks.list_fargate_profiles(clusterName=cluster_name)
            return response.get("fargateProfileNames", [])

    async def _describe_eks_fargate_profile(
        self, cluster_name: str, fargate_profile: str
    ) -> Dict[str, Any]:
        async with self.aws.client("eks") as eks:
            response = await eks.describe_fargate_profile(
                clusterName=cluster_name, fargateProfileName=fargate_profile
            )
            return response.get("fargateProfile", {})

    async def _execute(self, **kwargs) -> ToolResult:
        try:
            operation = kwargs.get("operation")

            if operation == ECSOperation.LIST_ECS_CLUSTERS:
                clusters = await self._list_ecs_clusters()
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"clusters": clusters, "count": len(clusters)},
                    metadata={"operation": "list_ecs_clusters"},
                    error=None,
                    timestamp=datetime.utcnow().isoformat(),
                )

            if operation == ECSOperation.LIST_SERVICES:
                if not kwargs.get("cluster_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name is required for list_services",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat(),
                    )
                services = await self._list_services(kwargs["cluster_name"])
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"services": services, "count": len(services)},
                    metadata={
                        "operation": "list_services",
                        "cluster": kwargs["cluster_name"],
                    },
                    error=None,
                    timestamp=datetime.utcnow().isoformat(),
                )

            if operation == ECSOperation.LIST_TASKS:
                if not kwargs.get("cluster_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name is required for list_tasks",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat(),
                    )
                tasks = await self._list_tasks(
                    cluster=kwargs["cluster_name"],
                    service_name=kwargs.get("service_name"),
                    desired_status=kwargs.get("desired_status"),
                    launch_type=kwargs.get("launch_type"),
                )
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"tasks": tasks, "count": len(tasks)},
                    metadata={
                        "operation": "list_tasks",
                        "cluster": kwargs["cluster_name"],
                        "service": kwargs.get("service_name"),
                    },
                    error=None,
                    timestamp=datetime.utcnow().isoformat(),
                )

            if operation == ECSOperation.DESCRIBE_TASKS:
                if not kwargs.get("cluster_name") or not kwargs.get("task_arns"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name and task_arns are required for describe_tasks",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat(),
                    )
                details = await self._describe_tasks(
                    cluster=kwargs["cluster_name"], task_arns=kwargs["task_arns"]
                )
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"tasks": details, "count": len(details)},
                    metadata={
                        "operation": "describe_tasks",
                        "cluster": kwargs["cluster_name"],
                    },
                    error=None,
                    timestamp=datetime.utcnow().isoformat(),
                )

            if operation == ECSOperation.GET_FARGATE_LOGS:
                if not kwargs.get("log_group_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="log_group_name is required for get_fargate_logs",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat(),
                    )
                start_time = self._parse_time(kwargs.get("start_time")) if kwargs.get("start_time") else None
                events = await self._get_fargate_logs(
                    log_group_name=kwargs["log_group_name"],
                    log_stream_prefix=kwargs.get("log_stream_prefix"),
                    start_time=start_time,
                    limit=kwargs.get("limit", 100),
                )
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"events": events, "count": len(events)},
                    metadata={
                        "operation": "get_fargate_logs",
                        "log_group": kwargs["log_group_name"],
                        "log_stream_prefix": kwargs.get("log_stream_prefix"),
                    },
                    error=None,
                    timestamp=datetime.utcnow().isoformat(),
                )

            if operation == ECSOperation.GET_EKS_CLUSTER_INFO:
                if not kwargs.get("cluster_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name is required for get_eks_cluster_info",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat(),
                    )
                info = await self._get_eks_cluster_info(kwargs["cluster_name"])
                return ToolResult(
                    success=True,
                    status="completed",
                    result=info,
                    metadata={"operation": "get_eks_cluster_info", "cluster": kwargs["cluster_name"]},
                    error=None,
                    timestamp=datetime.utcnow().isoformat(),
                )

            if operation == ECSOperation.LIST_EKS_CLUSTERS:
                clusters = await self._list_eks_clusters()
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"clusters": clusters, "count": len(clusters)},
                    metadata={"operation": "list_eks_clusters"},
                    error=None,
                    timestamp=datetime.utcnow().isoformat(),
                )

            if operation == ECSOperation.LIST_EKS_NODEGROUPS:
                if not kwargs.get("cluster_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name is required for list_eks_nodegroups",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat(),
                    )
                nodegroups = await self._list_eks_nodegroups(kwargs["cluster_name"])
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"nodegroups": nodegroups, "count": len(nodegroups)},
                    metadata={
                        "operation": "list_eks_nodegroups",
                        "cluster": kwargs["cluster_name"],
                    },
                    error=None,
                    timestamp=datetime.utcnow().isoformat(),
                )

            if operation == ECSOperation.DESCRIBE_EKS_NODEGROUP:
                if not kwargs.get("cluster_name") or not kwargs.get("eks_nodegroup"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name and eks_nodegroup are required for describe_eks_nodegroup",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat(),
                    )
                nodegroup = await self._describe_eks_nodegroup(
                    cluster_name=kwargs["cluster_name"], nodegroup=kwargs["eks_nodegroup"]
                )
                return ToolResult(
                    success=True,
                    status="completed",
                    result=nodegroup,
                    metadata={
                        "operation": "describe_eks_nodegroup",
                        "cluster": kwargs["cluster_name"],
                        "nodegroup": kwargs["eks_nodegroup"],
                    },
                    error=None,
                    timestamp=datetime.utcnow().isoformat(),
                )

            if operation == ECSOperation.LIST_EKS_FARGATE_PROFILES:
                if not kwargs.get("cluster_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name is required for list_eks_fargate_profiles",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat(),
                    )
                profiles = await self._list_eks_fargate_profiles(kwargs["cluster_name"])
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"fargate_profiles": profiles, "count": len(profiles)},
                    metadata={
                        "operation": "list_eks_fargate_profiles",
                        "cluster": kwargs["cluster_name"],
                    },
                    error=None,
                    timestamp=datetime.utcnow().isoformat(),
                )

            if operation == ECSOperation.DESCRIBE_EKS_FARGATE_PROFILE:
                if not kwargs.get("cluster_name") or not kwargs.get("eks_fargate_profile"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error=(
                            "cluster_name and eks_fargate_profile are required for "
                            "describe_eks_fargate_profile"
                        ),
                        metadata={},
                        timestamp=datetime.utcnow().isoformat(),
                    )
                profile = await self._describe_eks_fargate_profile(
                    cluster_name=kwargs["cluster_name"],
                    fargate_profile=kwargs["eks_fargate_profile"],
                )
                return ToolResult(
                    success=True,
                    status="completed",
                    result=profile,
                    metadata={
                        "operation": "describe_eks_fargate_profile",
                        "cluster": kwargs["cluster_name"],
                        "fargate_profile": kwargs["eks_fargate_profile"],
                    },
                    error=None,
                    timestamp=datetime.utcnow().isoformat(),
                )

            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Unknown operation: {operation}",
                metadata={"operation": str(operation)},
                timestamp=datetime.utcnow().isoformat(),
            )

        except ClientError as exc:
            error_code = exc.response["Error"].get("Code")
            error_msg = exc.response["Error"].get("Message")
            return ToolResult(
                success=False,
                status="aws_error",
                result=None,
                error=f"AWS Error ({error_code}): {error_msg}",
                metadata={"operation": kwargs.get("operation"), "error_code": error_code},
                timestamp=datetime.utcnow().isoformat(),
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"ECS/EKS operation failed: {exc}",
                metadata={
                    "operation": kwargs.get("operation"),
                    "exception_type": type(exc).__name__,
                },
                timestamp=datetime.utcnow().isoformat(),
            )
