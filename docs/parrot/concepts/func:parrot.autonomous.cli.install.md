---
type: Concept
title: install()
id: func:parrot.autonomous.cli.install
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generate gunicorn, supervisord, and systemd configs for an agent.
---

# install

```python
def install(agent: str, name: str | None, bind: str, workers: int | None, venv: str | None, enable_service: bool) -> None
```

Generate gunicorn, supervisord, and systemd configs for an agent.

Example:

    parrot autonomous install --agent ./my_agent.py --bind 0.0.0.0:8080

With service registration:

    parrot autonomous install --agent ./my_agent.py --enable-service
