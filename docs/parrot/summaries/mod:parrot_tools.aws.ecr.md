---
type: Wiki Summary
title: parrot_tools.aws.ecr
id: mod:parrot_tools.aws.ecr
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AWS ECR Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.ecr.ECRToolkit
  rel: defines
- concept: class:parrot_tools.aws.ecr.GetImageScanFindingsInput
  rel: defines
- concept: class:parrot_tools.aws.ecr.GetRepositoryPolicyInput
  rel: defines
- concept: class:parrot_tools.aws.ecr.ListRepositoriesInput
  rel: defines
- concept: class:parrot_tools.aws.ecr.ListRepositoryImagesInput
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.ecr`

AWS ECR Toolkit for AI-Parrot.

Provides inspection of ECR repositories, images, policies, and scan findings.

## Classes

- **`ListRepositoriesInput(BaseModel)`** — Input for listing ECR repositories.
- **`GetRepositoryPolicyInput(BaseModel)`** — Input for getting an ECR repository IAM policy.
- **`GetImageScanFindingsInput(BaseModel)`** — Input for getting vulnerability scan findings.
- **`ListRepositoryImagesInput(BaseModel)`** — Input for listing images in an ECR repository.
- **`ECRToolkit(AbstractToolkit)`** — Toolkit for inspecting AWS ECR repositories and container images.
