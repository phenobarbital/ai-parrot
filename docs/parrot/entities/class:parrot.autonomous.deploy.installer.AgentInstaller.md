---
type: Wiki Entity
title: AgentInstaller
id: class:parrot.autonomous.deploy.installer.AgentInstaller
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generates gunicorn, supervisord, and systemd configs for an agent.
---

# AgentInstaller

Defined in [`parrot.autonomous.deploy.installer`](../summaries/mod:parrot.autonomous.deploy.installer.md).

```python
class AgentInstaller
```

Generates gunicorn, supervisord, and systemd configs for an agent.

## Methods

- `def generate_gunicorn_config(self) -> Path` — Write a ``<name>_gunicorn.py`` file next to the agent script.
- `def generate_supervisord_config(self) -> Path` — Write a ``<name>.supervisor.conf`` file next to the agent script.
- `def generate_systemd_service(self) -> Path` — Write a ``<name>.service`` file next to the agent script.
- `def install(self) -> dict[str, Path]` — Generate all deployment artifacts.
