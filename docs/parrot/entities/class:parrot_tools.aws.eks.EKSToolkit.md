---
type: Wiki Entity
title: EKSToolkit
id: class:parrot_tools.aws.eks.EKSToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for inspecting AWS EKS Kubernetes clusters.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# EKSToolkit

Defined in [`parrot_tools.aws.eks`](../summaries/mod:parrot_tools.aws.eks.md).

```python
class EKSToolkit(AbstractToolkit)
```

Toolkit for inspecting AWS EKS Kubernetes clusters.

Each public method is exposed as a separate tool with the `aws_eks_` prefix.

Available Operations:
- aws_eks_list_clusters: List EKS clusters
- aws_eks_describe_cluster: Get EKS cluster details
- aws_eks_list_nodegroups: List EKS nodegroups
- aws_eks_describe_nodegroup: Get nodegroup details
- aws_eks_list_fargate_profiles: List EKS Fargate profiles
- aws_eks_describe_fargate_profile: Get Fargate profile details
- aws_eks_list_pods: List Kubernetes pods

## Methods

- `async def aws_eks_list_clusters(self) -> Dict[str, Any]` — List all EKS clusters in the AWS account.
- `async def aws_eks_describe_cluster(self, cluster_name: str) -> Dict[str, Any]` — Get details for a specific EKS cluster.
- `async def aws_eks_list_nodegroups(self, cluster_name: str) -> Dict[str, Any]` — List EKS nodegroups for a cluster.
- `async def aws_eks_describe_nodegroup(self, cluster_name: str, nodegroup_name: str) -> Dict[str, Any]` — Get details for a specific EKS nodegroup.
- `async def aws_eks_list_fargate_profiles(self, cluster_name: str) -> Dict[str, Any]` — List EKS Fargate profiles for a cluster.
- `async def aws_eks_describe_fargate_profile(self, cluster_name: str, fargate_profile_name: str) -> Dict[str, Any]` — Get details for a specific EKS Fargate profile.
- `async def aws_eks_list_pods(self, cluster_name: str, namespace: Optional[str]=None) -> Dict[str, Any]` — List Kubernetes pods in an EKS cluster.
