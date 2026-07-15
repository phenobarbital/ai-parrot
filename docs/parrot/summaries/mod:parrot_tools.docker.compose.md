---
type: Wiki Summary
title: parrot_tools.docker.compose
id: mod:parrot_tools.docker.compose
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Docker Compose file generator.
relates_to:
- concept: class:parrot_tools.docker.compose.ComposeGenerator
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot_tools.docker.models
  rel: references
---

# `parrot_tools.docker.compose`

Docker Compose file generator.

Generates valid docker-compose YAML files from Pydantic ComposeServiceDef models.
Implements spec Section 3 — Module 4 (FEAT-033).

## Classes

- **`ComposeGenerator`** — Generates docker-compose YAML from Pydantic models.
