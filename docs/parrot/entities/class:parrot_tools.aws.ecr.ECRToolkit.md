---
type: Wiki Entity
title: ECRToolkit
id: class:parrot_tools.aws.ecr.ECRToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for inspecting AWS ECR repositories and container images.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# ECRToolkit

Defined in [`parrot_tools.aws.ecr`](../summaries/mod:parrot_tools.aws.ecr.md).

```python
class ECRToolkit(AbstractToolkit)
```

Toolkit for inspecting AWS ECR repositories and container images.

Available Operations:
- aws_ecr_list_repositories: List ECR repositories
- aws_ecr_get_repository_policy: Get repository IAM policy
- aws_ecr_get_image_scan_findings: Get vulnerability scan findings
- aws_ecr_list_repository_images: List images in a repository

## Methods

- `async def aws_ecr_list_repositories(self, max_results: int=100, next_token: Optional[str]=None) -> Dict[str, Any]` — List all ECR repositories in the AWS account.
- `async def aws_ecr_get_repository_policy(self, repository_name: str) -> Dict[str, Any]` — Get the IAM policy for an ECR repository.
- `async def aws_ecr_get_image_scan_findings(self, repository_name: str, image_tag: str='latest', include_attributes: bool=False) -> Dict[str, Any]` — Get vulnerability scan findings for a container image.
- `async def aws_ecr_list_repository_images(self, repository_name: str, max_results: int=100) -> Dict[str, Any]` — List container images in an ECR repository.
