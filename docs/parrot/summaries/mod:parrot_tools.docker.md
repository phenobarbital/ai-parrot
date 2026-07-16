---
type: Wiki Summary
title: parrot_tools.docker
id: mod:parrot_tools.docker
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Docker Toolkit — manage containers and compose stacks.
relates_to:
- concept: mod:parrot_tools
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.docker`

Docker Toolkit — manage containers and compose stacks.

Provides agent tools for Docker operations:
- docker_ps: List containers
- docker_images: List images
- docker_run: Launch containers
- docker_stop / docker_rm: Container lifecycle
- docker_logs / docker_inspect: Container inspection
- docker_build: Build images from Dockerfiles
- docker_exec: Run commands inside containers
- docker_prune: Clean up unused resources
- docker_compose_generate / docker_compose_up / docker_compose_down: Compose workflows
- docker_test: Health-check containers

Example:
    from parrot_tools.docker import DockerToolkit

    toolkit = DockerToolkit()
    agent = Agent(tools=toolkit.get_tools())

Or with custom configuration:
    from parrot_tools.docker import DockerToolkit, DockerConfig

    config = DockerConfig(
        docker_cli="docker",
        cpu_limit="2",
        memory_limit="4g",
    )
    toolkit = DockerToolkit(config)
