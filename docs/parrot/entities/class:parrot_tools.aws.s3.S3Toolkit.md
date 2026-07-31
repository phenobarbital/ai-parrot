---
type: Wiki Entity
title: S3Toolkit
id: class:parrot_tools.aws.s3.S3Toolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for inspecting and analyzing AWS S3 buckets.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# S3Toolkit

Defined in [`parrot_tools.aws.s3`](../summaries/mod:parrot_tools.aws.s3.md).

```python
class S3Toolkit(AbstractToolkit)
```

Toolkit for inspecting and analyzing AWS S3 buckets.

Available Operations:
- aws_s3_list_buckets: List all S3 buckets
- aws_s3_get_bucket_details: Get detailed bucket information
- aws_s3_analyze_bucket_security: Analyze bucket security config
- aws_s3_find_public_buckets: Find publicly accessible buckets

## Methods

- `async def aws_s3_list_buckets(self) -> Dict[str, Any]` — List all S3 buckets in the AWS account.
- `async def aws_s3_get_bucket_details(self, bucket_name: str) -> Dict[str, Any]` — Get detailed information about a specific S3 bucket.
- `async def aws_s3_analyze_bucket_security(self, bucket_name: str) -> Dict[str, Any]` — Analyze the security configuration of an S3 bucket.
- `async def aws_s3_find_public_buckets(self) -> Dict[str, Any]` — Find all publicly accessible S3 buckets in the account.
