---
type: Wiki Summary
title: parrot_tools.docker.executor
id: mod:parrot_tools.docker.executor
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Docker executor for running Docker CLI commands.
relates_to:
- concept: class:parrot_tools.docker.executor.DockerExecutor
  rel: defines
- concept: mod:parrot_tools.docker.config
  rel: references
- concept: mod:parrot_tools.docker.models
  rel: references
- concept: mod:parrot_tools.security.base_executor
  rel: references
---

# `parrot_tools.docker.executor`

Docker executor for running Docker CLI commands.

Extends BaseExecutor to provide Docker-specific CLI argument building,
output parsing, and daemon/compose detection. Supports container lifecycle,
image building, and command execution operations.

## Classes

- **`DockerExecutor(BaseExecutor)`** — Async executor for Docker CLI commands.
