---
type: Wiki Entity
title: EcrCollectionResult
id: class:parrot_tools.cloudsploit.models.EcrCollectionResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Top-level container — mirrors the JSON output of collect_ecr_findings.js.
---

# EcrCollectionResult

Defined in [`parrot_tools.cloudsploit.models`](../summaries/mod:parrot_tools.cloudsploit.models.md).

```python
class EcrCollectionResult(BaseModel)
```

Top-level container — mirrors the JSON output of collect_ecr_findings.js.

Shape::

    {
        "generated_at": "<ISO-8601 UTC>",
        "region": "<AWS region>",
        "repos": [ <EcrRepoFindings>, ... ],
        "skipped": [ {"repo": ..., "reason": ...}, ... ],
    }
