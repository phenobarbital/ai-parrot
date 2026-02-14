"""AWS ECS/EKS Toolkit for AI-Parrot.

Provides inspection of ECS/Fargate tasks, EKS Kubernetes clusters, and EC2 instances.
"""
from __future__ import annotations

import re
import ssl
import base64
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

import aiohttp
from pydantic import BaseModel, Field
from botocore.exceptions import ClientError
from botocore import session as boto_session
from botocore.signers import RequestSigner

from ...interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit


# ------------------------------------------------------------------
# Input Schemas
# ------------------------------------------------------------------


class ListECSClustersInput(BaseModel):
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


class DescribeEKSClusterInput(BaseModel):
    """Input for describing an EKS cluster."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )


class ListEKSClustersInput(BaseModel):
    """Input for listing EKS clusters."""


class ListEKSNodegroupsInput(BaseModel):
    """Input for listing EKS nodegroups."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )


class DescribeEKSNodegroupInput(BaseModel):
    """Input for describing an EKS nodegroup."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )
    nodegroup_name: str = Field(
        ..., description="EKS nodegroup name"
    )


class ListEKSFargateProfilesInput(BaseModel):
    """Input for listing EKS Fargate profiles."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )


class DescribeEKSFargateProfileInput(BaseModel):
    """Input for describing an EKS Fargate profile."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )
    fargate_profile_name: str = Field(
        ..., description="EKS Fargate profile name"
    )


class ListEKSPodsInput(BaseModel):
    """Input for listing Kubernetes pods in an EKS cluster."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace to filter pods (default: all)",
    )


class ListEC2InstancesInput(BaseModel):
    """Input for listing EC2 instances."""

    instance_state: Optional[str] = Field(
        None,
        description="Filter by state (e.g. 'running', 'stopped', 'terminated')",
    )
    instance_ids: Optional[List[str]] = Field(
        None, description="Specific EC2 instance IDs to describe"
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class ECSToolkit(AbstractToolkit):
    """Toolkit for inspecting AWS ECS/Fargate, EKS, and EC2 resources.

    Each public method is exposed as a separate tool with the `aws_ecs_` prefix.

    Available Operations:
    - aws_ecs_list_clusters: List ECS clusters
    - aws_ecs_list_services: List services in a cluster
    - aws_ecs_list_tasks: List tasks with filters
    - aws_ecs_describe_tasks: Describe specific tasks
    - aws_ecs_get_fargate_logs: Get Fargate task logs
    - aws_ecs_describe_eks_cluster: Get EKS cluster details
    - aws_ecs_list_eks_clusters: List EKS clusters
    - aws_ecs_list_eks_nodegroups: List EKS nodegroups
    - aws_ecs_describe_eks_nodegroup: Get nodegroup details
    - aws_ecs_list_eks_fargate_profiles: List EKS Fargate profiles
    - aws_ecs_describe_eks_fargate_profile: Get Fargate profile details
    - aws_ecs_list_eks_pods: List Kubernetes pods
    - aws_ecs_list_ec2_instances: List EC2 instances
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

    async def _get_eks_token(self, cluster_name: str) -> str:
        """Generate an authentication token for EKS cluster using STS."""
        try:
            session = boto_session.Session()
            client = session.create_client(
                "sts", region_name=self.aws._region
            )

            service_id = client.meta.service_model.service_id
            signer = RequestSigner(
                service_id,
                self.aws._region,
                "sts",
                "v4",
                session.get_credentials(),
                session.get_component("event_emitter"),
            )

            params = {
                "method": "GET",
                "url": (
                    f"https://sts.{self.aws._region}.amazonaws.com/"
                    "?Action=GetCallerIdentity&Version=2011-06-15"
                ),
                "body": {},
                "headers": {"x-k8s-aws-id": cluster_name},
                "context": {},
            }

            signed_url = signer.generate_presigned_url(
                params,
                region_name=self.aws._region,
                expires_in=60,
                operation_name="",
            )

            return (
                "k8s-aws-v1."
                + base64.urlsafe_b64encode(
                    signed_url.encode()
                )
                .decode()
                .rstrip("=")
            )
        except Exception as exc:
            raise ValueError(
                f"Failed to generate EKS token: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # ECS Operations
    # ------------------------------------------------------------------

    @tool_schema(ListECSClustersInput)
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

    # ------------------------------------------------------------------
    # EKS Operations
    # ------------------------------------------------------------------

    @tool_schema(ListEKSClustersInput)
    async def aws_ecs_list_eks_clusters(self) -> Dict[str, Any]:
        """List all EKS clusters in the AWS account."""
        try:
            async with self.aws.client("eks") as eks:
                response = await eks.list_clusters()
                clusters = response.get("clusters", [])
                return {"clusters": clusters, "count": len(clusters)}
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EKS error ({error_code}): {e}"
            ) from e

    @tool_schema(DescribeEKSClusterInput)
    async def aws_ecs_describe_eks_cluster(
        self, cluster_name: str
    ) -> Dict[str, Any]:
        """Get details for a specific EKS cluster."""
        try:
            async with self.aws.client("eks") as eks:
                response = await eks.describe_cluster(
                    name=cluster_name
                )
                cluster = response.get("cluster", {})
                return {
                    "name": cluster.get("name"),
                    "status": cluster.get("status"),
                    "version": cluster.get("version"),
                    "endpoint": cluster.get("endpoint"),
                    "arn": cluster.get("arn"),
                    "created_at": (
                        cluster.get("createdAt").isoformat()
                        if cluster.get("createdAt")
                        else None
                    ),
                    "role_arn": cluster.get("roleArn"),
                    "platform_version": cluster.get(
                        "platformVersion"
                    ),
                    "kubernetes_network_config": cluster.get(
                        "kubernetesNetworkConfig"
                    ),
                    "logging": cluster.get("logging"),
                    "resources_vpc_config": cluster.get(
                        "resourcesVpcConfig"
                    ),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EKS error ({error_code}): {e}"
            ) from e

    @tool_schema(ListEKSNodegroupsInput)
    async def aws_ecs_list_eks_nodegroups(
        self, cluster_name: str
    ) -> Dict[str, Any]:
        """List EKS nodegroups for a cluster."""
        try:
            async with self.aws.client("eks") as eks:
                response = await eks.list_nodegroups(
                    clusterName=cluster_name
                )
                nodegroups = response.get("nodegroups", [])
                return {
                    "cluster": cluster_name,
                    "nodegroups": nodegroups,
                    "count": len(nodegroups),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EKS error ({error_code}): {e}"
            ) from e

    @tool_schema(DescribeEKSNodegroupInput)
    async def aws_ecs_describe_eks_nodegroup(
        self, cluster_name: str, nodegroup_name: str
    ) -> Dict[str, Any]:
        """Get details for a specific EKS nodegroup."""
        try:
            async with self.aws.client("eks") as eks:
                response = await eks.describe_nodegroup(
                    clusterName=cluster_name,
                    nodegroupName=nodegroup_name,
                )
                return response.get("nodegroup", {})
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EKS error ({error_code}): {e}"
            ) from e

    @tool_schema(ListEKSFargateProfilesInput)
    async def aws_ecs_list_eks_fargate_profiles(
        self, cluster_name: str
    ) -> Dict[str, Any]:
        """List EKS Fargate profiles for a cluster."""
        try:
            async with self.aws.client("eks") as eks:
                response = await eks.list_fargate_profiles(
                    clusterName=cluster_name
                )
                profiles = response.get("fargateProfileNames", [])
                return {
                    "cluster": cluster_name,
                    "fargate_profiles": profiles,
                    "count": len(profiles),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EKS error ({error_code}): {e}"
            ) from e

    @tool_schema(DescribeEKSFargateProfileInput)
    async def aws_ecs_describe_eks_fargate_profile(
        self,
        cluster_name: str,
        fargate_profile_name: str,
    ) -> Dict[str, Any]:
        """Get details for a specific EKS Fargate profile."""
        try:
            async with self.aws.client("eks") as eks:
                response = await eks.describe_fargate_profile(
                    clusterName=cluster_name,
                    fargateProfileName=fargate_profile_name,
                )
                return response.get("fargateProfile", {})
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EKS error ({error_code}): {e}"
            ) from e

    @tool_schema(ListEKSPodsInput)
    async def aws_ecs_list_eks_pods(
        self,
        cluster_name: str,
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List Kubernetes pods in an EKS cluster."""
        try:
            cluster_info = await self.aws_ecs_describe_eks_cluster(
                cluster_name
            )
            endpoint = cluster_info.get("endpoint")
            if not endpoint:
                raise ValueError(
                    f"Could not get endpoint for cluster {cluster_name}"
                )

            token = await self._get_eks_token(cluster_name)

            url = (
                f"{endpoint}/api/v1/namespaces/{namespace}/pods"
                if namespace
                else f"{endpoint}/api/v1/pods"
            )

            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers, ssl=ssl_context
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise ValueError(
                            f"Failed to list pods: "
                            f"HTTP {response.status} - {error_text}"
                        )

                    data = await response.json()
                    items = data.get("items", [])

                    pods = []
                    for item in items:
                        metadata = item.get("metadata", {})
                        spec = item.get("spec", {})
                        status = item.get("status", {})

                        pods.append(
                            {
                                "name": metadata.get("name"),
                                "namespace": metadata.get("namespace"),
                                "uid": metadata.get("uid"),
                                "creation_timestamp": metadata.get(
                                    "creationTimestamp"
                                ),
                                "labels": metadata.get("labels", {}),
                                "node_name": spec.get("nodeName"),
                                "phase": status.get("phase"),
                                "pod_ip": status.get("podIP"),
                                "host_ip": status.get("hostIP"),
                                "start_time": status.get("startTime"),
                                "conditions": status.get(
                                    "conditions", []
                                ),
                                "container_statuses": status.get(
                                    "containerStatuses", []
                                ),
                            }
                        )

                    return {
                        "cluster": cluster_name,
                        "namespace": namespace or "all",
                        "pods": pods,
                        "count": len(pods),
                    }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS EKS error ({error_code}): {e}"
            ) from e
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to list EKS pods: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # EC2 Operations
    # ------------------------------------------------------------------

    @tool_schema(ListEC2InstancesInput)
    async def aws_ecs_list_ec2_instances(
        self,
        instance_state: Optional[str] = None,
        instance_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """List EC2 instances with optional filters."""
        try:
            params: Dict[str, Any] = {}

            filters = []
            if instance_state:
                filters.append(
                    {
                        "Name": "instance-state-name",
                        "Values": [instance_state],
                    }
                )
            if filters:
                params["Filters"] = filters
            if instance_ids:
                params["InstanceIds"] = instance_ids

            async with self.aws.client("ec2") as ec2:
                response = await ec2.describe_instances(**params)

                instances = []
                for reservation in response.get(
                    "Reservations", []
                ):
                    for instance in reservation.get(
                        "Instances", []
                    ):
                        instances.append(
                            {
                                "instance_id": instance.get(
                                    "InstanceId"
                                ),
                                "instance_type": instance.get(
                                    "InstanceType"
                                ),
                                "state": instance.get(
                                    "State", {}
                                ).get("Name"),
                                "state_code": instance.get(
                                    "State", {}
                                ).get("Code"),
                                "launch_time": (
                                    instance.get(
                                        "LaunchTime"
                                    ).isoformat()
                                    if instance.get("LaunchTime")
                                    else None
                                ),
                                "availability_zone": instance.get(
                                    "Placement", {}
                                ).get("AvailabilityZone"),
                                "private_ip": instance.get(
                                    "PrivateIpAddress"
                                ),
                                "public_ip": instance.get(
                                    "PublicIpAddress"
                                ),
                                "private_dns": instance.get(
                                    "PrivateDnsName"
                                ),
                                "public_dns": instance.get(
                                    "PublicDnsName"
                                ),
                                "vpc_id": instance.get("VpcId"),
                                "subnet_id": instance.get(
                                    "SubnetId"
                                ),
                                "architecture": instance.get(
                                    "Architecture"
                                ),
                                "image_id": instance.get(
                                    "ImageId"
                                ),
                                "key_name": instance.get(
                                    "KeyName"
                                ),
                                "platform": instance.get(
                                    "Platform"
                                ),
                                "tags": {
                                    tag.get("Key"): tag.get("Value")
                                    for tag in instance.get(
                                        "Tags", []
                                    )
                                },
                                "security_groups": [
                                    {
                                        "id": sg.get("GroupId"),
                                        "name": sg.get("GroupName"),
                                    }
                                    for sg in instance.get(
                                        "SecurityGroups", []
                                    )
                                ],
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
