---
type: Wiki Summary
title: parrot.autonomous.deploy.installer
id: mod:parrot.autonomous.deploy.installer
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generates deployment configs for AutonomousOrchestrator agents.
relates_to:
- concept: class:parrot.autonomous.deploy.installer.AgentInstaller
  rel: defines
- concept: func:parrot.autonomous.deploy.installer.create_sample_agent
  rel: defines
- concept: mod:parrot.autonomous.deploy.templates
  rel: references
---

# `parrot.autonomous.deploy.installer`

Generates deployment configs for AutonomousOrchestrator agents.

## Classes

- **`AgentInstaller`** — Generates gunicorn, supervisord, and systemd configs for an agent.

## Functions

- `def create_sample_agent(output_path: Path) -> Path` — Write a sample AutonomousOrchestrator agent script to *output_path*.
