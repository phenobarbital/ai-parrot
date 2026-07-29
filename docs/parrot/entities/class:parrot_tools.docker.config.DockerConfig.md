---
type: Wiki Entity
title: DockerConfig
id: class:parrot_tools.docker.config.DockerConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for Docker executor.
relates_to:
- concept: class:parrot_tools.security.base_executor.BaseExecutorConfig
  rel: extends
---

# DockerConfig

Defined in [`parrot_tools.docker.config`](../summaries/mod:parrot_tools.docker.config.md).

```python
class DockerConfig(BaseExecutorConfig)
```

Configuration for Docker executor.

Extends BaseExecutorConfig with Docker-specific settings for
CLI paths, networking, and default resource limits.

Example:
    config = DockerConfig(
        docker_cli="docker",
        compose_cli="docker compose",
        cpu_limit="2",
        memory_limit="4g",
    )
