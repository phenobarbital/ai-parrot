"""
AWS ECS and EKS Tool for AI-Parrot

Provides helpers to inspect Fargate tasks, ECS services, and EKS clusters.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone
import re
import base64
import ssl
from enum import Enum
from botocore.exceptions import ClientError
from botocore import session as boto_session
from botocore.signers import RequestSigner
from pydantic import Field, field_validator
import aiohttp
from ..interfaces.aws import AWSInterface
from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult


class ECSOperation(str, Enum):
    """Supported ECS/EKS operations."""

    LIST_ECS_CLUSTERS = "list_ecs_clusters"
    LIST_ECS_SERVICES = "list_ecs_services"
    LIST_SERVICES = "list_services"
    LIST_ECS_TASKS = "list_ecs_tasks"
    LIST_TASKS = "list_tasks"
    DESCRIBE_ECS_TASKS = "describe_ecs_tasks"
    DESCRIBE_TASKS = "describe_tasks"
    GET_FARGATE_TASK_LOGS = "get_fargate_task_logs"
    GET_FARGATE_LOGS = "get_fargate_logs"
    DESCRIBE_EKS_CLUSTER = "describe_eks_cluster"
    GET_EKS_CLUSTER_INFO = "get_eks_cluster_info"
    LIST_EKS_CLUSTERS = "list_eks_clusters"
    LIST_EKS_NODEGROUPS = "list_eks_nodegroups"
    DESCRIBE_EKS_NODEGROUP = "describe_eks_nodegroup"
    LIST_EKS_FARGATE_PROFILES = "list_eks_fargate_profiles"
    DESCRIBE_EKS_FARGATE_PROFILE = "describe_eks_fargate_profile"
    LIST_EKS_PODS = "list_eks_pods"
    LIST_EC2_INSTANCES = "list_ec2_instances"


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
    namespace: Optional[str] = Field(
        None, description="Kubernetes namespace to filter pods (default: all namespaces)"
    )
    instance_state: Optional[str] = Field(
        None, description="Filter EC2 instances by state (e.g., 'running', 'stopped', 'terminated')"
    )
    instance_ids: Optional[List[str]] = Field(
        None, description="Specific EC2 instance IDs to describe"
    )

    @field_validator("start_time", mode="before")
    @classmethod
    def validate_start_time(cls, value):
        if value is None or value == "now":
            return value
        return value


class ECSTool(AbstractTool):
    """
    Tool for inspecting AWS ECS/Fargate tasks, EKS Kubernetes clusters, and EC2 instances.

    Capabilities include:
    - Listing ECS clusters, services, and tasks
    - Describing ECS tasks (useful for Fargate workloads)
    - Fetching Fargate task logs from CloudWatch
    - Inspecting EKS cluster, nodegroup, and Fargate profile metadata
    - Listing Kubernetes pods in EKS clusters
    - Listing and describing EC2 instances
    """

    name: str = "aws_ecs_eks_tool"
    description: str = "Inspect AWS ECS/Fargate tasks, EKS Kubernetes clusters, and EC2 instances"
    args_schema: type[AbstractToolArgsSchema] = ECSToolArgs

    def __init__(self, aws_id: str = "default", region_name: Optional[str] = None, **kwargs):
        super().__init__()
        self.aws = AWSInterface(aws_id=aws_id, region_name=region_name, **kwargs)

    def _parse_time(self, value: Optional[str]) -> Optional[datetime]:
        if value is None or value == "now":
            return datetime.utc(tz=timezone.utc)

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

        if value.startswith("-"):
            raw = value[1:]
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

            return datetime.now(timezone.utc) - delta

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

    async def _describe_eks_cluster(self, cluster_name: str) -> Dict[str, Any]:
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

    async def _get_eks_cluster_info(self, cluster_name: str) -> Dict[str, Any]:
        """Backward-compatible alias for describing an EKS cluster."""
        return await self._describe_eks_cluster(cluster_name)

    async def _list_eks_clusters(self) -> List[str]:
        async with self.aws.client("eks") as eks:
            response = await eks.list_clusters()
            return response.get("clusters", [])

    async def list_eks_clusters(self) -> List[str]:
        """Public helper for listing available EKS clusters."""

        return await self._list_eks_clusters()

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

    async def _get_eks_token(self, cluster_name: str) -> str:
        """Generate an authentication token for EKS cluster using STS."""
        try:
            session = boto_session.Session()
            client = session.create_client('sts', region_name=self.aws._region)

            service_id = client.meta.service_model.service_id
            signer = RequestSigner(
                service_id,
                self.aws._region,
                'sts',
                'v4',
                session.get_credentials(),
                session.get_component('event_emitter')
            )

            params = {
                'method': 'GET',
                'url': f'https://sts.{self.aws._region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15',
                'body': {},
                'headers': {
                    'x-k8s-aws-id': cluster_name
                },
                'context': {}
            }

            signed_url = signer.generate_presigned_url(
                params,
                region_name=self.aws._region,
                expires_in=60,
                operation_name=''
            )

            token = f"k8s-aws-v1.{base64.urlsafe_b64encode(signed_url.encode()).decode().rstrip('=')}"
            return token
        except Exception as exc:
            raise ValueError(f"Failed to generate EKS token: {exc}")

    async def _list_eks_pods(
        self, cluster_name: str, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List all pods in an EKS cluster.

        This method authenticates with the EKS cluster using AWS STS and queries
        the Kubernetes API to retrieve pod information.
        """
        try:
            # Import aiohttp for making HTTP requests to k8s API
            # Get cluster endpoint and certificate
            cluster_info = await self._describe_eks_cluster(cluster_name)
            endpoint = cluster_info.get("endpoint")
            ca_data = cluster_info.get("resources_vpc_config", {})

            if not endpoint:
                raise ValueError(f"Could not get endpoint for cluster {cluster_name}")

            # Get authentication token
            token = await self._get_eks_token(cluster_name)

            # Prepare the API URL
            if namespace:
                url = f"{endpoint}/api/v1/namespaces/{namespace}/pods"
            else:
                url = f"{endpoint}/api/v1/pods"

            # Create SSL context (skip verification for simplicity, or use cluster CA)
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, ssl=ssl_context) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise ValueError(
                            f"Failed to list pods: HTTP {response.status} - {error_text}"
                        )

                    data = await response.json()
                    items = data.get("items", [])

                    # Extract relevant pod information
                    pods = []
                    for item in items:
                        metadata = item.get("metadata", {})
                        spec = item.get("spec", {})
                        status = item.get("status", {})

                        pod_info = {
                            "name": metadata.get("name"),
                            "namespace": metadata.get("namespace"),
                            "uid": metadata.get("uid"),
                            "creation_timestamp": metadata.get("creationTimestamp"),
                            "labels": metadata.get("labels", {}),
                            "annotations": metadata.get("annotations", {}),
                            "node_name": spec.get("nodeName"),
                            "phase": status.get("phase"),
                            "pod_ip": status.get("podIP"),
                            "host_ip": status.get("hostIP"),
                            "start_time": status.get("startTime"),
                            "conditions": status.get("conditions", []),
                            "container_statuses": status.get("containerStatuses", []),
                        }
                        pods.append(pod_info)

                    return pods

        except ImportError as e:
            raise ValueError(
                "aiohttp is required to list EKS pods. Install it with: pip install aiohttp"
            ) from e
        except Exception as exc:
            raise ValueError(
                f"Failed to list EKS pods: {exc}"
            ) from exc

    async def _list_ec2_instances(
        self,
        instance_state: Optional[str] = None,
        instance_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        List EC2 instances in the AWS account.

        Args:
            instance_state: Filter by instance state (e.g., 'running', 'stopped')
            instance_ids: Specific instance IDs to describe

        Returns:
            List of EC2 instance information dictionaries
        """
        params: Dict[str, Any] = {}

        # Build filters
        filters = []
        if instance_state:
            filters.append(
                {"Name": "instance-state-name", "Values": [instance_state]}
            )

        if filters:
            params["Filters"] = filters

        if instance_ids:
            params["InstanceIds"] = instance_ids

        async with self.aws.client("ec2") as ec2:
            response = await ec2.describe_instances(**params)

            instances = []
            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    # Extract relevant instance information
                    instance_info = {
                        "instance_id": instance.get("InstanceId"),
                        "instance_type": instance.get("InstanceType"),
                        "state": instance.get("State", {}).get("Name"),
                        "state_code": instance.get("State", {}).get("Code"),
                        "launch_time": instance.get("LaunchTime").isoformat()
                        if instance.get("LaunchTime")
                        else None,
                        "availability_zone": instance.get("Placement", {}).get(
                            "AvailabilityZone"
                        ),
                        "private_ip": instance.get("PrivateIpAddress"),
                        "public_ip": instance.get("PublicIpAddress"),
                        "private_dns": instance.get("PrivateDnsName"),
                        "public_dns": instance.get("PublicDnsName"),
                        "vpc_id": instance.get("VpcId"),
                        "subnet_id": instance.get("SubnetId"),
                        "architecture": instance.get("Architecture"),
                        "image_id": instance.get("ImageId"),
                        "key_name": instance.get("KeyName"),
                        "platform": instance.get("Platform"),
                        "tags": {
                            tag.get("Key"): tag.get("Value")
                            for tag in instance.get("Tags", [])
                        },
                        "security_groups": [
                            {
                                "id": sg.get("GroupId"),
                                "name": sg.get("GroupName"),
                            }
                            for sg in instance.get("SecurityGroups", [])
                        ],
                    }
                    instances.append(instance_info)

            return instances

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
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if operation in (
                ECSOperation.LIST_ECS_SERVICES,
                ECSOperation.LIST_SERVICES,
            ):
                if not kwargs.get("cluster_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name is required for list_ecs_services",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                services = await self._list_services(kwargs["cluster_name"])
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"services": services, "count": len(services)},
                    metadata={
                        "operation": ECSOperation.LIST_ECS_SERVICES.value,
                        "cluster": kwargs["cluster_name"],
                    },
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if operation in (ECSOperation.LIST_ECS_TASKS, ECSOperation.LIST_TASKS):
                if not kwargs.get("cluster_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name is required for list_ecs_tasks",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat(),
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
                        "operation": ECSOperation.LIST_ECS_TASKS.value,
                        "cluster": kwargs["cluster_name"],
                        "service": kwargs.get("service_name"),
                    },
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if operation in (
                ECSOperation.DESCRIBE_ECS_TASKS,
                ECSOperation.DESCRIBE_TASKS,
            ):
                if not kwargs.get("cluster_name") or not kwargs.get("task_arns"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name and task_arns are required for describe_ecs_tasks",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                details = await self._describe_tasks(
                    cluster=kwargs["cluster_name"], task_arns=kwargs["task_arns"]
                )
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"tasks": details, "count": len(details)},
                    metadata={
                        "operation": ECSOperation.DESCRIBE_ECS_TASKS.value,
                        "cluster": kwargs["cluster_name"],
                    },
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if operation in (
                ECSOperation.GET_FARGATE_TASK_LOGS,
                ECSOperation.GET_FARGATE_LOGS,
            ):
                if not kwargs.get("log_group_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="log_group_name is required for get_fargate_task_logs",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat(),
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
                        "operation": ECSOperation.GET_FARGATE_TASK_LOGS.value,
                        "log_group": kwargs["log_group_name"],
                        "log_stream_prefix": kwargs.get("log_stream_prefix"),
                    },
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if operation in (
                ECSOperation.DESCRIBE_EKS_CLUSTER,
                ECSOperation.GET_EKS_CLUSTER_INFO,
            ):
                if not kwargs.get("cluster_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name is required for describe_eks_cluster",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                info = await self._describe_eks_cluster(kwargs["cluster_name"])
                return ToolResult(
                    success=True,
                    status="completed",
                    result=info,
                    metadata={
                        "operation": ECSOperation.DESCRIBE_EKS_CLUSTER.value,
                        "cluster": kwargs["cluster_name"],
                    },
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if operation == ECSOperation.LIST_EKS_CLUSTERS:
                clusters = await self._list_eks_clusters()
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"clusters": clusters, "count": len(clusters)},
                    metadata={"operation": ECSOperation.LIST_EKS_CLUSTERS.value},
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if operation == ECSOperation.LIST_EKS_NODEGROUPS:
                if not kwargs.get("cluster_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name is required for list_eks_nodegroups",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                nodegroups = await self._list_eks_nodegroups(kwargs["cluster_name"])
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"nodegroups": nodegroups, "count": len(nodegroups)},
                    metadata={
                        "operation": ECSOperation.LIST_EKS_NODEGROUPS.value,
                        "cluster": kwargs["cluster_name"],
                    },
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if operation == ECSOperation.DESCRIBE_EKS_NODEGROUP:
                if not kwargs.get("cluster_name") or not kwargs.get("eks_nodegroup"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name and eks_nodegroup are required for describe_eks_nodegroup",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                nodegroup = await self._describe_eks_nodegroup(
                    cluster_name=kwargs["cluster_name"], nodegroup=kwargs["eks_nodegroup"]
                )
                return ToolResult(
                    success=True,
                    status="completed",
                    result=nodegroup,
                    metadata={
                        "operation": ECSOperation.DESCRIBE_EKS_NODEGROUP.value,
                        "cluster": kwargs["cluster_name"],
                        "nodegroup": kwargs["eks_nodegroup"],
                    },
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if operation == ECSOperation.LIST_EKS_FARGATE_PROFILES:
                if not kwargs.get("cluster_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name is required for list_eks_fargate_profiles",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                profiles = await self._list_eks_fargate_profiles(kwargs["cluster_name"])
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"fargate_profiles": profiles, "count": len(profiles)},
                    metadata={
                        "operation": ECSOperation.LIST_EKS_FARGATE_PROFILES.value,
                        "cluster": kwargs["cluster_name"],
                    },
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
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
                        timestamp=datetime.now(timezone.utc).isoformat(),
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
                        "operation": ECSOperation.DESCRIBE_EKS_FARGATE_PROFILE.value,
                        "cluster": kwargs["cluster_name"],
                        "fargate_profile": kwargs["eks_fargate_profile"],
                    },
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if operation == ECSOperation.LIST_EKS_PODS:
                if not kwargs.get("cluster_name"):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="cluster_name is required for list_eks_pods",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                pods = await self._list_eks_pods(
                    cluster_name=kwargs["cluster_name"],
                    namespace=kwargs.get("namespace"),
                )
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"pods": pods, "count": len(pods)},
                    metadata={
                        "operation": ECSOperation.LIST_EKS_PODS.value,
                        "cluster": kwargs["cluster_name"],
                        "namespace": kwargs.get("namespace", "all"),
                    },
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if operation == ECSOperation.LIST_EC2_INSTANCES:
                instances = await self._list_ec2_instances(
                    instance_state=kwargs.get("instance_state"),
                    instance_ids=kwargs.get("instance_ids"),
                )
                return ToolResult(
                    success=True,
                    status="completed",
                    result={"instances": instances, "count": len(instances)},
                    metadata={
                        "operation": ECSOperation.LIST_EC2_INSTANCES.value,
                        "instance_state": kwargs.get("instance_state"),
                    },
                    error=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Unknown operation: {operation}",
                metadata={"operation": str(operation)},
                timestamp=datetime.now(timezone.utc).isoformat(),
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
                timestamp=datetime.now(timezone.utc).isoformat(),
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
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
