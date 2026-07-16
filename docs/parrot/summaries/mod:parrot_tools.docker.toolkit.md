---
type: Wiki Summary
title: parrot_tools.docker.toolkit
id: mod:parrot_tools.docker.toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Docker Toolkit for managing containers and compose stacks.
relates_to:
- concept: class:parrot_tools.docker.toolkit.DockerToolkit
  rel: defines
- concept: mod:parrot.tools.toolkit
  rel: references
- concept: mod:parrot_tools.docker.compose
  rel: references
- concept: mod:parrot_tools.docker.config
  rel: references
- concept: mod:parrot_tools.docker.executor
  rel: references
- concept: mod:parrot_tools.docker.models
  rel: references
---

# `parrot_tools.docker.toolkit`

Docker Toolkit for managing containers and compose stacks.

Exposes all Docker operations as agent tools via AbstractToolkit.
Implements spec Section 3 — Module 5 (FEAT-033).

## Classes

- **`DockerToolkit(AbstractToolkit)`** — Toolkit for managing Docker containers and compose stacks.
