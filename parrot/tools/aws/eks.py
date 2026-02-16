"""AWS EKS Toolkit for AI-Parrot.

Provides inspection of EKS Kubernetes clusters, nodegroups, and pods.
"""
from __future__ import annotations

import base64
import ssl
from typing import Any, Dict, Optional
import aiohttp
from botocore.exceptions import ClientError
from botocore import session as boto_session
from botocore.signers import RequestSigner
from pydantic import BaseModel, Field

from ...interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit


# ------------------------------------------------------------------
# Input Schemas
# ------------------------------------------------------------------


class ListClustersInput(BaseModel):
    """Input for listing EKS clusters."""


class DescribeClusterInput(BaseModel):
    """Input for describing an EKS cluster."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )


class ListNodegroupsInput(BaseModel):
    """Input for listing EKS nodegroups."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )


class DescribeNodegroupInput(BaseModel):
    """Input for describing an EKS nodegroup."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )
    nodegroup_name: str = Field(
        ..., description="EKS nodegroup name"
    )


class ListFargateProfilesInput(BaseModel):
    """Input for listing EKS Fargate profiles."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )


class DescribeFargateProfileInput(BaseModel):
    """Input for describing an EKS Fargate profile."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )
    fargate_profile_name: str = Field(
        ..., description="EKS Fargate profile name"
    )


class ListPodsInput(BaseModel):
    """Input for listing Kubernetes pods in an EKS cluster."""

    cluster_name: str = Field(
        ..., description="EKS cluster name"
    )
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace to filter pods (default: all)",
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class EKSToolkit(AbstractToolkit):
    """Toolkit for inspecting AWS EKS Kubernetes clusters.

    Each public method is exposed as a separate tool with the `aws_eks_` prefix.

    Available Operations:
    - aws_eks_list_clusters: List EKS clusters
    - aws_eks_describe_cluster: Get EKS cluster details
    - aws_eks_list_nodegroups: List EKS nodegroups
    - aws_eks_describe_nodegroup: Get nodegroup details
    - aws_eks_list_fargate_profiles: List EKS Fargate profiles
    - aws_eks_describe_fargate_profile: Get Fargate profile details
    - aws_eks_list_pods: List Kubernetes pods
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
    # EKS Operations
    # ------------------------------------------------------------------

    @tool_schema(ListClustersInput)
    async def aws_eks_list_clusters(self) -> Dict[str, Any]:
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

    @tool_schema(DescribeClusterInput)
    async def aws_eks_describe_cluster(
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

    @tool_schema(ListNodegroupsInput)
    async def aws_eks_list_nodegroups(
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

    @tool_schema(DescribeNodegroupInput)
    async def aws_eks_describe_nodegroup(
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

    @tool_schema(ListFargateProfilesInput)
    async def aws_eks_list_fargate_profiles(
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

    @tool_schema(DescribeFargateProfileInput)
    async def aws_eks_describe_fargate_profile(
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

    @tool_schema(ListPodsInput)
    async def aws_eks_list_pods(
        self,
        cluster_name: str,
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List Kubernetes pods in an EKS cluster."""
        try:
            cluster_info = await self.aws_eks_describe_cluster(
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
