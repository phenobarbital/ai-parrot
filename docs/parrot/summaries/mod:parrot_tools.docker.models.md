---
type: Wiki Summary
title: parrot_tools.docker.models
id: mod:parrot_tools.docker.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Docker data models for container, image, and compose operations.
relates_to:
- concept: class:parrot_tools.docker.models.ComposeGenerateInput
  rel: defines
- concept: class:parrot_tools.docker.models.ComposeServiceDef
  rel: defines
- concept: class:parrot_tools.docker.models.ContainerInfo
  rel: defines
- concept: class:parrot_tools.docker.models.ContainerRunInput
  rel: defines
- concept: class:parrot_tools.docker.models.DockerBuildInput
  rel: defines
- concept: class:parrot_tools.docker.models.DockerExecInput
  rel: defines
- concept: class:parrot_tools.docker.models.DockerOperationResult
  rel: defines
- concept: class:parrot_tools.docker.models.ImageInfo
  rel: defines
- concept: class:parrot_tools.docker.models.PortMapping
  rel: defines
- concept: class:parrot_tools.docker.models.PruneResult
  rel: defines
- concept: class:parrot_tools.docker.models.VolumeMapping
  rel: defines
---

# `parrot_tools.docker.models`

Docker data models for container, image, and compose operations.

Defines all Pydantic models used by the Docker Toolkit (FEAT-033).
These models provide structured input/output for Docker CLI operations.

## Classes

- **`ContainerInfo(BaseModel)`** — Information about a Docker container.
- **`ImageInfo(BaseModel)`** — Information about a Docker image.
- **`PortMapping(BaseModel)`** — Port mapping for a container.
- **`VolumeMapping(BaseModel)`** — Volume mapping for a container.
- **`ContainerRunInput(BaseModel)`** — Input for docker_run operation.
- **`ComposeServiceDef(BaseModel)`** — Definition of a single service in a docker-compose file.
- **`ComposeGenerateInput(BaseModel)`** — Input for generating a docker-compose file.
- **`DockerOperationResult(BaseModel)`** — Result of a Docker operation.
- **`PruneResult(BaseModel)`** — Result of a Docker prune operation.
- **`DockerBuildInput(BaseModel)`** — Input for docker_build operation.
- **`DockerExecInput(BaseModel)`** — Input for docker_exec operation.
