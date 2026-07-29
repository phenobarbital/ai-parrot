---
type: Wiki Summary
title: parrot_tools.system_health.tool
id: mod:parrot_tools.system_health.tool
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Read-only system health monitoring tool.
relates_to:
- concept: class:parrot_tools.system_health.tool.HealthCategory
  rel: defines
- concept: class:parrot_tools.system_health.tool.SystemHealthArgs
  rel: defines
- concept: class:parrot_tools.system_health.tool.SystemHealthTool
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.system_health.tool`

Read-only system health monitoring tool.

Exposes host-level metrics (CPU, RAM, disk, network, processes, Docker
containers) to the LLM without any write or exec capabilities.

Security guarantees:
- Uses psutil Python API, never shell commands (except read-only ``docker ps``).
- Reports process *counts* and top consumers by name only — no PIDs exposed.
- Reports open file descriptor *count*, never file paths or contents.
- Does not expose environment variables or secrets.
- Docker: only ``docker ps`` (list running containers), no exec/run/stop.

Example:
    from parrot_tools.system_health import SystemHealthTool

    tool = SystemHealthTool()
    result = await tool.execute(category="all")
    print(result.result)

## Classes

- **`HealthCategory(str, Enum)`** — Available health-check categories.
- **`SystemHealthArgs(AbstractToolArgsSchema)`** — Arguments for the system health tool.
- **`SystemHealthTool(AbstractTool)`** — Read-only system health monitor.
