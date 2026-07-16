---
type: Wiki Entity
title: IAMToolkit
id: class:parrot_tools.aws.iam.IAMToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for inspecting AWS IAM roles, users, policies, and access keys.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# IAMToolkit

Defined in [`parrot_tools.aws.iam`](../summaries/mod:parrot_tools.aws.iam.md).

```python
class IAMToolkit(AbstractToolkit)
```

Toolkit for inspecting AWS IAM roles, users, policies, and access keys.

Available Operations:
- aws_iam_list_roles: List IAM roles
- aws_iam_get_role: Get detailed role information
- aws_iam_list_users: List IAM users
- aws_iam_get_user: Get detailed user information
- aws_iam_get_policy_details: Get policy details by ARN
- aws_iam_find_access_key: Find which user owns an access key
- aws_iam_list_active_access_keys: List all active access keys

## Methods

- `async def aws_iam_list_roles(self, max_items: int=100, path_prefix: Optional[str]=None) -> Dict[str, Any]` — List IAM roles in the AWS account.
- `async def aws_iam_get_role(self, role_name: str) -> Dict[str, Any]` — Get detailed information about an IAM role including trust policy.
- `async def aws_iam_list_users(self, max_items: int=100, path_prefix: Optional[str]=None) -> Dict[str, Any]` — List IAM users in the AWS account.
- `async def aws_iam_get_user(self, user_name: str) -> Dict[str, Any]` — Get detailed information about an IAM user.
- `async def aws_iam_get_policy_details(self, policy_arn: str, include_versions: bool=False) -> Dict[str, Any]` — Get detailed information about an IAM policy.
- `async def aws_iam_find_access_key(self, access_key_id: str) -> Dict[str, Any]` — Find which IAM user owns a specific access key.
- `async def aws_iam_list_active_access_keys(self) -> Dict[str, Any]` — List all active IAM access keys across all users.
