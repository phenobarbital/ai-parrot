---
type: Wiki Entity
title: ECSToolkit
id: class:parrot_tools.aws.ecs.ECSToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for inspecting AWS ECS/Fargate resources.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# ECSToolkit

Defined in [`parrot_tools.aws.ecs`](../summaries/mod:parrot_tools.aws.ecs.md).

```python
class ECSToolkit(AbstractToolkit)
```

Toolkit for inspecting AWS ECS/Fargate resources.

Each public method is exposed as a separate tool with the `aws_ecs_` prefix.

Available Operations:
- aws_ecs_list_clusters: List ECS clusters
- aws_ecs_list_services: List services in a cluster
- aws_ecs_list_tasks: List tasks with filters
- aws_ecs_describe_tasks: Describe specific tasks
- aws_ecs_get_fargate_logs: Get Fargate task logs

## Methods

- `async def aws_ecs_list_clusters(self) -> Dict[str, Any]` — List all ECS clusters in the AWS account.
- `async def aws_ecs_list_services(self, cluster_name: str) -> Dict[str, Any]` — List ECS services in a cluster.
- `async def aws_ecs_list_tasks(self, cluster_name: str, service_name: Optional[str]=None, desired_status: Optional[str]=None, launch_type: Optional[str]=None) -> Dict[str, Any]` — List ECS tasks with optional filters.
- `async def aws_ecs_describe_tasks(self, cluster_name: str, task_arns: List[str]) -> Dict[str, Any]` — Describe specific ECS tasks.
- `async def aws_ecs_get_fargate_logs(self, log_group_name: str, log_stream_prefix: Optional[str]=None, start_time: Optional[str]=None, limit: int=100) -> Dict[str, Any]` — Get Fargate task logs from CloudWatch.
