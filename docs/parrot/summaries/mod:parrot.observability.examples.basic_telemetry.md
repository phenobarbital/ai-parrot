---
type: Wiki Summary
title: parrot.observability.examples.basic_telemetry
id: mod:parrot.observability.examples.basic_telemetry
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Basic telemetry demo for AI-Parrot.
relates_to:
- concept: func:parrot.observability.examples.basic_telemetry.main
  rel: defines
- concept: mod:parrot.observability
  rel: references
---

# `parrot.observability.examples.basic_telemetry`

Basic telemetry demo for AI-Parrot.

FEAT-177 TASK-1237.

Demonstrates end-to-end observability with OpenTelemetry + OpenLIT.

Prerequisites:
  1. Start the stack: docker compose -f docker-compose.observability.yml up -d
  2. Wait ~15 s for OpenLIT to initialize.
  3. Set OPENAI_API_KEY (or use an OpenAI-compatible local server).

Usage:
  python basic_telemetry.py

Then open http://localhost:3000 to see traces and metrics in OpenLIT UI.

## Functions

- `async def main() -> None` — Run 3 demo ask() calls and send traces/metrics to OpenLIT.
