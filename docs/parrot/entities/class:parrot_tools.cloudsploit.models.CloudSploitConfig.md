---
type: Wiki Entity
title: CloudSploitConfig
id: class:parrot_tools.cloudsploit.models.CloudSploitConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for CloudSploit execution.
---

# CloudSploitConfig

Defined in [`parrot_tools.cloudsploit.models`](../summaries/mod:parrot_tools.cloudsploit.models.md).

```python
class CloudSploitConfig(BaseModel)
```

Configuration for CloudSploit execution.

CloudSploit Docker Setup:
    git clone https://github.com/aquasecurity/cloudsploit.git
    cd cloudsploit
    docker build . -t cloudsploit:0.0.1
