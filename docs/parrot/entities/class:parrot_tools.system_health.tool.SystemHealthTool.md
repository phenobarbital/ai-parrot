---
type: Wiki Entity
title: SystemHealthTool
id: class:parrot_tools.system_health.tool.SystemHealthTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Read-only system health monitor.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# SystemHealthTool

Defined in [`parrot_tools.system_health.tool`](../summaries/mod:parrot_tools.system_health.tool.md).

```python
class SystemHealthTool(AbstractTool)
```

Read-only system health monitor.

Returns a structured snapshot of host metrics so the agent can
reason about resource usage, capacity, and running services
without any ability to modify the system.

Categories:
- **cpu**: core count, per-core and average usage, load averages.
- **memory**: total / available / used RAM and swap.
- **disk**: per-partition usage (mount, total, used, free, percent).
- **network**: per-interface bytes sent/received, packets, errors.
- **processes**: total count, top 10 by CPU and top 10 by memory (name only).
- **system**: hostname, platform, uptime, open-fd count, thread count.
- **docker**: list of running containers (name, image, status, ports).
- **gpu**: per-GPU utilization, temperature, VRAM usage (NVIDIA via pynvml, PyTorch fallback).
