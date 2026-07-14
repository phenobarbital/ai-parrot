---
type: Wiki Summary
title: parrot_tools.aws.eks
id: mod:parrot_tools.aws.eks
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AWS EKS Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.eks.DescribeClusterInput
  rel: defines
- concept: class:parrot_tools.aws.eks.DescribeFargateProfileInput
  rel: defines
- concept: class:parrot_tools.aws.eks.DescribeNodegroupInput
  rel: defines
- concept: class:parrot_tools.aws.eks.EKSToolkit
  rel: defines
- concept: class:parrot_tools.aws.eks.ListClustersInput
  rel: defines
- concept: class:parrot_tools.aws.eks.ListFargateProfilesInput
  rel: defines
- concept: class:parrot_tools.aws.eks.ListNodegroupsInput
  rel: defines
- concept: class:parrot_tools.aws.eks.ListPodsInput
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.eks`

AWS EKS Toolkit for AI-Parrot.

Provides inspection of EKS Kubernetes clusters, nodegroups, and pods.

## Classes

- **`ListClustersInput(BaseModel)`** — Input for listing EKS clusters.
- **`DescribeClusterInput(BaseModel)`** — Input for describing an EKS cluster.
- **`ListNodegroupsInput(BaseModel)`** — Input for listing EKS nodegroups.
- **`DescribeNodegroupInput(BaseModel)`** — Input for describing an EKS nodegroup.
- **`ListFargateProfilesInput(BaseModel)`** — Input for listing EKS Fargate profiles.
- **`DescribeFargateProfileInput(BaseModel)`** — Input for describing an EKS Fargate profile.
- **`ListPodsInput(BaseModel)`** — Input for listing Kubernetes pods in an EKS cluster.
- **`EKSToolkit(AbstractToolkit)`** — Toolkit for inspecting AWS EKS Kubernetes clusters.
