---
type: Wiki Summary
title: parrot_tools.aws.iam
id: mod:parrot_tools.aws.iam
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AWS IAM Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.iam.FindAccessKeyInput
  rel: defines
- concept: class:parrot_tools.aws.iam.GetPolicyDetailsInput
  rel: defines
- concept: class:parrot_tools.aws.iam.GetRoleInput
  rel: defines
- concept: class:parrot_tools.aws.iam.GetUserInput
  rel: defines
- concept: class:parrot_tools.aws.iam.IAMToolkit
  rel: defines
- concept: class:parrot_tools.aws.iam.ListActiveAccessKeysInput
  rel: defines
- concept: class:parrot_tools.aws.iam.ListRolesInput
  rel: defines
- concept: class:parrot_tools.aws.iam.ListUsersInput
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.iam`

AWS IAM Toolkit for AI-Parrot.

Provides inspection of IAM roles, users, policies, and access keys.

## Classes

- **`ListRolesInput(BaseModel)`** — Input for listing IAM roles.
- **`GetRoleInput(BaseModel)`** — Input for getting IAM role details.
- **`ListUsersInput(BaseModel)`** — Input for listing IAM users.
- **`GetUserInput(BaseModel)`** — Input for getting IAM user details.
- **`GetPolicyDetailsInput(BaseModel)`** — Input for getting IAM policy details.
- **`FindAccessKeyInput(BaseModel)`** — Input for finding the owner of an access key.
- **`ListActiveAccessKeysInput(BaseModel)`** — Input for listing all active access keys.
- **`IAMToolkit(AbstractToolkit)`** — Toolkit for inspecting AWS IAM roles, users, policies, and access keys.
