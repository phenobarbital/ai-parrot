---
type: Wiki Summary
title: parrot.autonomous.cli
id: mod:parrot.autonomous.cli
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CLI commands for AutonomousOrchestrator deployment.
relates_to:
- concept: func:parrot.autonomous.cli.autonomous
  rel: defines
- concept: func:parrot.autonomous.cli.create
  rel: defines
- concept: func:parrot.autonomous.cli.install
  rel: defines
- concept: mod:parrot.autonomous.deploy.installer
  rel: references
---

# `parrot.autonomous.cli`

CLI commands for AutonomousOrchestrator deployment.

Provides:
    parrot autonomous create --agent <path>
    parrot autonomous install --agent <path> [--name ...] [--bind ...] [--workers ...]

## Functions

- `def autonomous() -> None` — Manage AutonomousOrchestrator agents.
- `def create(agent: str, force: bool) -> None` — Generate a sample AutonomousOrchestrator agent script.
- `def install(agent: str, name: str | None, bind: str, workers: int | None, venv: str | None, enable_service: bool) -> None` — Generate gunicorn, supervisord, and systemd configs for an agent.
