---
type: Wiki Summary
title: parrot_tools.computer.backend
id: mod:parrot_tools.computer.backend
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AsyncComputerBackend — async Playwright wrapper for computer-use actions.
relates_to:
- concept: class:parrot_tools.computer.backend.AsyncComputerBackend
  rel: defines
- concept: mod:parrot_tools.computer.models
  rel: references
---

# `parrot_tools.computer.backend`

AsyncComputerBackend — async Playwright wrapper for computer-use actions.

Translates coordinate-based computer-use model actions into Playwright API
calls. Every action returns an EnvState with a screenshot and current URL.

## Classes

- **`AsyncComputerBackend`** — Async Playwright wrapper implementing the computer-use action interface.
