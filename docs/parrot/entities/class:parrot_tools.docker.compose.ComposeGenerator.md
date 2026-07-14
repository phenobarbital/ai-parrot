---
type: Wiki Entity
title: ComposeGenerator
id: class:parrot_tools.docker.compose.ComposeGenerator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generates docker-compose YAML from Pydantic models.
---

# ComposeGenerator

Defined in [`parrot_tools.docker.compose`](../summaries/mod:parrot_tools.docker.compose.md).

```python
class ComposeGenerator
```

Generates docker-compose YAML from Pydantic models.

Converts ComposeServiceDef instances into valid docker-compose v3.8 YAML,
extracts named volumes into the top-level volumes section, and writes
to disk at the configured DOCKER_FILE_LOCATION or a user-specified path.

Example:
    generator = ComposeGenerator()
    services = {
        "redis": ComposeServiceDef(image="redis:alpine", ports=["6379:6379"]),
    }
    compose_dict = generator.to_dict("myproject", services)
    path = await generator.generate("myproject", services)

## Methods

- `def to_dict(self, project_name: str, services: Dict[str, ComposeServiceDef]) -> dict` — Convert service definitions to a compose dict.
- `async def generate(self, project_name: str, services: Dict[str, ComposeServiceDef], output_path: Optional[str]=None) -> str` — Generate and write a docker-compose.yml file.
- `async def validate(self, compose_path: str) -> bool` — Validate a docker-compose file using docker compose config.
