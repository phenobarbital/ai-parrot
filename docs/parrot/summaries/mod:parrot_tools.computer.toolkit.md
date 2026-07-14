---
type: Wiki Summary
title: parrot_tools.computer.toolkit
id: mod:parrot_tools.computer.toolkit
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ComputerInteractionToolkit — AbstractToolkit subclass for computer-use actions.
relates_to:
- concept: class:parrot_tools.computer.toolkit.ComputerInteractionToolkit
  rel: defines
- concept: mod:parrot.tools.toolkit
  rel: references
- concept: mod:parrot_tools.computer.backend
  rel: references
- concept: mod:parrot_tools.computer.models
  rel: references
---

# `parrot_tools.computer.toolkit`

ComputerInteractionToolkit — AbstractToolkit subclass for computer-use actions.

Exposes 13 predefined computer-use actions, screenshot/recording capabilities,
and task/loop execution as agent-callable tools. Handles coordinate normalization
(0-1000 → viewport pixels) and delegates all browser operations to AsyncComputerBackend.

## Classes

- **`ComputerInteractionToolkit(AbstractToolkit)`** — AbstractToolkit for vision-based browser automation via computer-use.
