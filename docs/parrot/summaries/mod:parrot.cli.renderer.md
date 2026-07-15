---
type: Wiki Summary
title: parrot.cli.renderer
id: mod:parrot.cli.renderer
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Response renderer for AI-Parrot CLI agent REPL.
relates_to:
- concept: class:parrot.cli.renderer.ResponseRenderer
  rel: defines
- concept: mod:parrot.models.responses
  rel: references
---

# `parrot.cli.renderer`

Response renderer for AI-Parrot CLI agent REPL.

Renders ``AIMessage`` objects to the terminal using Rich for markdown,
code blocks, tool call panels, usage stats, and streaming live display.

## Classes

- **`ResponseRenderer`** — Renders AIMessage responses to the terminal via Rich.
