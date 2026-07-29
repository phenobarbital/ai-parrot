---
type: Wiki Entity
title: AWSInterface
id: class:parrot.interfaces.aws.AWSInterface
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base interface for AWS services using aioboto3.
---

# AWSInterface

Defined in [`parrot.interfaces.aws`](../summaries/mod:parrot.interfaces.aws.md).

```python
class AWSInterface
```

Base interface for AWS services using aioboto3.

Provides async context manager for creating service clients.
Handles credential management and session lifecycle.

Example:
    >>> aws = AWSInterface(aws_id='default')
    >>> async with aws.client('s3') as s3:
    ...     response = await s3.list_buckets()

## Methods

- `def region(self) -> str` — Get configured AWS region
- `async def client(self, service_name: str, **kwargs) -> AsyncIterator[Any]` — Async context manager for AWS service client.
- `async def resource(self, service_name: str, **kwargs) -> AsyncIterator[Any]` — Async context manager for AWS service resource.
- `async def validate_credentials(self) -> bool` — Validate AWS credentials by making a simple API call.
- `async def get_caller_identity(self) -> Dict[str, Any]` — Get AWS caller identity information.
