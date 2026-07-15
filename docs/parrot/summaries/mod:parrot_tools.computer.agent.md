---
type: Wiki Summary
title: parrot_tools.computer.agent
id: mod:parrot_tools.computer.agent
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ComputerAgent — Agent subclass for vision-based browser automation (FEAT-227).
relates_to:
- concept: class:parrot_tools.computer.agent.ComputerAgent
  rel: defines
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.human
  rel: references
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot_tools.computer.toolkit
  rel: references
- concept: mod:parrot_tools.scraping.toolkit
  rel: references
---

# `parrot_tools.computer.agent`

ComputerAgent — Agent subclass for vision-based browser automation (FEAT-227).

Configured for Google Gemini computer-use models. Composes
ComputerInteractionToolkit + optional WebScrapingToolkit. Manages
screenshot memory pruning and safety decision handling.

## Classes

- **`ComputerAgent(Agent)`** — Agent configured for vision-based browser automation via computer-use.
