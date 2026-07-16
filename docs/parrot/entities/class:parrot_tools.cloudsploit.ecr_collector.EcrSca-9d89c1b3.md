---
type: Wiki Entity
title: EcrScanCollector
id: class:parrot_tools.cloudsploit.ecr_collector.EcrScanCollector
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Aggregate ECR vulnerability scan findings across many repos.
---

# EcrScanCollector

Defined in [`parrot_tools.cloudsploit.ecr_collector`](../summaries/mod:parrot_tools.cloudsploit.ecr_collector.md).

```python
class EcrScanCollector
```

Aggregate ECR vulnerability scan findings across many repos.

Orchestrates the multi-repo / tag-priority loop that was previously
implemented in the JS script ``collect_ecr_findings.js``.  For each
repo in the plan it tries the specified tags in priority order, stopping
at the first tag whose image has scan findings (first-match-wins).
Concurrency across repos is bounded by ``asyncio.Semaphore``.

Attributes:
    aws: The ``AWSInterface`` instance used for all ECR API calls.
    logger: Standard Python logger named after this class.

## Methods

- `async def collect(self, plan: EcrCollectionPlan) -> EcrCollectionResult` — Run the collection plan with bounded concurrency.
