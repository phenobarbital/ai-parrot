---
type: Wiki Entity
title: PortMapping
id: class:parrot_tools.docker.models.PortMapping
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Port mapping for a container.
---

# PortMapping

Defined in [`parrot_tools.docker.models`](../summaries/mod:parrot_tools.docker.models.md).

```python
class PortMapping(BaseModel)
```

Port mapping for a container.

Accepts either structured dicts or Docker-style strings:
- ``"11211:11211"`` → host=11211, container=11211, tcp
- ``"8080:80/udp"`` → host=8080, container=80, udp
- ``"443"``         → host=443, container=443, tcp
