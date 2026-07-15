---
type: Wiki Summary
title: parrot_tools.aws.ecs
id: mod:parrot_tools.aws.ecs
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AWS ECS Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.ecs.DescribeTasksInput
  rel: defines
- concept: class:parrot_tools.aws.ecs.ECSToolkit
  rel: defines
- concept: class:parrot_tools.aws.ecs.GetFargateLogsInput
  rel: defines
- concept: class:parrot_tools.aws.ecs.ListClustersInput
  rel: defines
- concept: class:parrot_tools.aws.ecs.ListServicesInput
  rel: defines
- concept: class:parrot_tools.aws.ecs.ListTasksInput
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.ecs`

AWS ECS Toolkit for AI-Parrot.

Provides inspection of ECS/Fargate tasks.

## Classes

- **`ListClustersInput(BaseModel)`** — Input for listing ECS clusters.
- **`ListServicesInput(BaseModel)`** — Input for listing ECS services in a cluster.
- **`ListTasksInput(BaseModel)`** — Input for listing ECS tasks with optional filters.
- **`DescribeTasksInput(BaseModel)`** — Input for describing specific ECS tasks.
- **`GetFargateLogsInput(BaseModel)`** — Input for fetching Fargate task logs from CloudWatch.
- **`ECSToolkit(AbstractToolkit)`** — Toolkit for inspecting AWS ECS/Fargate resources.
