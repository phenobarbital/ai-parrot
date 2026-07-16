---
type: Wiki Entity
title: SandboxSpec
id: class:parrot.eval.sandbox.base.SandboxSpec
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for a sandbox instance.
---

# SandboxSpec

Defined in [`parrot.eval.sandbox.base`](../summaries/mod:parrot.eval.sandbox.base.md).

```python
class SandboxSpec(BaseModel)
```

Configuration for a sandbox instance.

Attributes:
    kind: Sandbox implementation selector.
    image: Docker image tag (only used by ``DockerSandbox``).
    setup: Shell commands to run after the sandbox starts.
    seed_state: Initial world state to load into state-based sandboxes.
    git_truncate_after: Git ref to truncate history to (SWE-bench use).
